"""The context manager: the gatherer's database, run under a policy.

`Manager` is the one implementation of `ag.ag_interface.ContextManager`. It
owns what every policy shares -- creating a gatherer, its event types, storing
events, finding them again, logging reads -- and hands the one question that
differs between policies, what the context is, to its `Policy`
(ag/ag_interface/policy.py):

    Manager(policy, pollers=...)
      .init(gatherer, types)        shared tables, policy.init(store), the policy's event types, then `types`
      .insert(gatherer, event)      a row in `events`; neither the policy nor the pollers are involved
      .read(gatherer, row_id)       the pollers (`poll`), policy.read(store, Read(...)), then the read log

It also brings in events from outside the conversation: its POLLERS
(`ag.ag_interface.Poller`). When it reads, it first asks each poller for what
happened since it last asked -- the mark kept per gatherer and per poller in
`_polls` -- and stores what they return with only the properties the poller
declares (`Poller.properties`), none of which a read gives, so every read
sees them and the policy builds the context from them too.
`insert` only stores.

The tokenizer counts each event at insert: the one given, else the
policy's, else tiktoken; a policy without one is given it, so both count
alike.
"""

import os
import sqlite3
import time
from dataclasses import replace
from datetime import datetime
from typing import Iterable, List, Optional, Tuple

from ag.ag_interface import AG, ContextManager, Event, EventType, Poller, Tokenizer, is_ag
from ag.ag_interface.policy import Context, Policy, Read
from .store import operations as store
from .store import schema
from .store.paths import db_path
from .store.gatherer import Store, StoreGatherers
from .store.notify import notify
from ag.ag_tools.log import warn
from ag.ag_tools.tokenizers import Tiktoken


class Manager(ContextManager):
    def __init__(self, policy: Policy, tokenizer: Optional[Tokenizer] = None, pollers: Iterable[Poller] = ()):
        self.policy = policy
        self.name = policy.name
        self.tokenizer = tokenizer or getattr(policy, "tokenizer", None) or Tiktoken()
        # What the policy is given when its constructor was not: the tokenizer
        # events are counted with, and Gatherers, to open a gatherer's store
        # outside a read (a background job).
        if getattr(policy, "tokenizer", None) is None:
            policy.tokenizer = self.tokenizer
        if getattr(policy, "gatherers", None) is None:
            policy.gatherers = StoreGatherers()
        self.pollers: List[Poller] = []
        for poller in pollers:
            self.add_poller(poller)
        self._prepared = set()          # database files this manager has set up
        self._specs = {}                # database file -> its properties (store.Spec), while no type is added

    def _conn(self, gatherer_id: str):
        """The process's connection to the gatherer, with the shared tables and
        the policy's in place (checked once per file per manager)."""
        conn = schema.connection(gatherer_id)
        path = db_path(gatherer_id)
        if path not in self._prepared:
            schema.create(conn)
            self._prepare(conn, gatherer_id)
            self._prepared.add(path)
        return conn

    def store(self, gatherer_id: str) -> Store:
        """The gatherer's store, as a policy is given it (ag.ag_interface.GathererStore)."""
        return Store(self._conn(gatherer_id), gatherer_id)

    def _prepare(self, conn, gatherer_id: str) -> None:
        """The policy's tables, then the types it expects (its contract with
        the harness), in its order, so their ids are the same in every
        gatherer it runs -- and with them a column for every property they
        declare, so whatever the policy's events may carry has its place."""
        self.policy.init(Store(conn, gatherer_id))
        for event_type in self.policy.event_types:
            store.register_type(conn, event_type)

    def init(self, gatherer_id: str, event_types: Iterable[EventType] = ()) -> None:
        """The shared tables; the policy's tables and the types it expects;
        then a row in `event_types` for each of `event_types` (by name, in
        order): a new type, or new properties for one already there."""
        self._specs.pop(db_path(gatherer_id), None)
        conn = schema.connect(gatherer_id)
        try:
            self._prepare(conn, gatherer_id)
            for event_type in event_types:
                store.register_type(conn, event_type)
        finally:
            conn.close()

    def add_event_type(self, gatherer_id: str, event_type: EventType) -> int:
        """One more row in `event_types`, unless the name is defined already;
        either way, that type's id."""
        self._specs.pop(db_path(gatherer_id), None)
        return store.register_type(self._conn(gatherer_id), event_type)

    def _spec(self, gatherer_id: str, type_id=None):
        """The gatherer's properties, as last loaded; loaded again when `type_id`
        is not among its types (added since, maybe by another process)."""
        path = db_path(gatherer_id)
        spec = self._specs.get(path)
        if spec is None or (type_id is not None and type_id not in spec.types):
            spec = self._specs[path] = store.spec(self._conn(gatherer_id))
        return spec

    def insert(self, gatherer_id: str, event: Event) -> Optional[int]:
        """One row in `events`, in its own transaction. Returns the event's
        `row_id`, or None if it was already stored: a duplicate is the same
        event id with the same identifying properties (whatever the others
        say), and the first insert wins. Without an
        id, every insert is a new row. Its `tokens` are stored as given, else
        the tokenizer's count of the payload's JSON. Creates the database if
        `init` was not called. The pollers are not asked: `read` does that.

        Raises:
            TypeError: `event` is not an Event with an int `type_id`, or its
                payload is not JSON-serializable. Nothing is stored.
            LookupError: the gatherer has no event type with that id.
            ValueError: its properties are not what its type declares.
        """
        conn = self._conn(gatherer_id)
        row_id = store.insert(conn, event, self.tokenizer, self._spec(gatherer_id, getattr(event, "type_id", None)))
        if row_id is not None:
            notify(gatherer_id, "events", event.properties, row_id)
        return row_id

    def locate(self, gatherer_id: str, event_id: str, *, properties: Optional[dict] = None) -> Optional[int]:
        """The row id of the event with this id that a read with `properties`
        sees (with them, or with them unset; whichever came first), or None."""
        if not os.path.exists(db_path(gatherer_id)):
            return None
        return store.locate(self._conn(gatherer_id), properties, event_id)

    def event_types(self, gatherer_id: str) -> List[EventType]:
        """The gatherer's types, in the order defined, with their ids."""
        if not os.path.exists(db_path(gatherer_id)):
            return []
        return store.event_types(self._conn(gatherer_id))

    def last_inserted_at(self, gatherer_id: str) -> Optional[float]:
        """Not part of the interface: when the gatherer's most recent event was
        stored, as seconds since the epoch (UTC), or None when it has none."""
        if not os.path.exists(db_path(gatherer_id)):
            return None
        stamp = store.last_inserted_at(self._conn(gatherer_id))
        return datetime.fromisoformat(stamp).timestamp() if stamp else None

    # ------------------------------------------------------------ pollers

    def add_poller(self, poller: Poller) -> None:
        """Attach a source of outside events; one per name (a second with
        the same name replaces the first). It must declare its `outputs`."""
        if not getattr(poller, "outputs", ()):
            raise ValueError(f"poller {poller.name!r} declares no outputs")
        self.pollers = [p for p in self.pollers if p.name != poller.name] + [poller]

    def set_pollers(self, pollers: Iterable[Poller]) -> None:
        """Replace every poller with `pollers` (one per name): what a
        gatherer's config says, re-read when it changes. A poller dropped
        keeps its mark, so it resumes where it was if it comes back."""
        self.pollers = []
        for poller in pollers:
            self.add_poller(poller)

    def poll(self, gatherer_id: str) -> int:
        """Ask every poller for what happened since it was last asked for
        this gatherer, and store it, with the properties the poller sets. Returns
        how many events were newly stored. `read` does this before the
        policy builds the context; a harness may also call it at a moment of
        its own choosing.

        Only the properties the poller declares (`properties`: e.g. its id),
        because what happens outside the conversation -- a file changed, a
        message posted -- is no one read's: a read sees an event whose
        properties it does not name or that are unset, although the poll
        mark is the gatherer's and only one read found it.

        Right before it is asked, a poller is told what the conversation's raw part says
        (`Poller.watch`: the texts of the events the channels were last sent verbatim, and of
        those since): one that only looks at what the conversation refers to takes it from there.

        A poller's `since` is its mark in `_polls`, or None the first time it
        is asked for this gatherer: there is no earlier moment, and each
        poller decides what that means (the file poller returns nothing). The mark is taken before the poller
        runs, so nothing that happens while it runs is lost (a duplicate is
        harmless). A poller that raises, or returns an event of a type it
        does not declare (`outputs`), with a property it does not declare
        (`properties`), or one the store refuses, is reported and skipped:
        polling never fails a read.
        """
        if not self.pollers:
            return 0
        conn = self._conn(gatherer_id)
        types = store.event_types(conn)
        names = {t.id: t.name for t in types}
        stored = 0
        watching = [p for p in self.pollers if getattr(type(p), "watch", Poller.watch) is not Poller.watch]
        texts = store.raw_texts(conn) if watching else []        # what the conversation's raw part says
        for poller in self.pollers:
            since = store.polled_at(conn, poller.name)
            now = time.time()
            try:
                if poller in watching:
                    poller.watch(texts)
                events = list(poller.poll(since, types))
            except Exception as exc:  # noqa: BLE001 - an outside source must not break a read
                warn(f"poller {poller.name!r} failed: {exc!r}")
                continue
            store.mark_polled(conn, poller.name, now)
            last = None
            for event in events:
                if names.get(event.type_id) not in poller.outputs:
                    warn(f"poller {poller.name!r}: an event of type {names.get(event.type_id, event.type_id)!r}, "
                         f"which it does not declare ({', '.join(poller.outputs)}); dropped")
                    continue
                undeclared = sorted(k for k, v in (event.properties or {}).items()
                                    if v is not None and k not in getattr(poller, "properties", ()))
                if undeclared:
                    warn(f"poller {poller.name!r}: an event with the properties {', '.join(undeclared)}, "
                         f"which it does not declare ({', '.join(getattr(poller, 'properties', ())) or 'none'}); "
                         f"dropped")
                    continue
                try:
                    row_id = store.insert(conn, event, self.tokenizer)
                    if row_id is not None:
                        stored, last = stored + 1, row_id
                except (TypeError, LookupError, ValueError) as exc:
                    warn(f"poller {poller.name!r}: event refused: {exc}")
            if last is not None:
                notify(gatherer_id, "events", None, last)        # no one read's (above): every channel's
        return stored

    # ------------------------------------------------------------ reads

    def read(self, gatherer_id: str, row_id: int, *, properties: Optional[dict] = None) -> list:
        """The policy's context for the next model call of `properties`, in
        response to the event `row_id`, logged as a read (with that row id,
        the policy's name and its basis). First the pollers are asked
        (`poll`) and what they return is stored after
        everything inserted so far, so the context is built from it too. A
        gatherer with no database reads as empty, and is not polled."""
        return self._context(gatherer_id, row_id, properties)[0].items

    def _context(self, gatherer_id: str, row_id: int, properties: Optional[dict],
                 limit: Optional[int] = None, preamble: Optional[List[dict]] = None,
                 process: Optional[dict] = None, run: Optional[str] = None) -> Tuple[Context, Optional[int]]:
        """(the policy's context, the read_id it was logged as; None: an empty context, not logged).
        `limit` is the harness's own limit the call stated (`Read.limit`); `preamble` what it sends
        besides its messages ([{name, text}]), kept with the read, as are `process`, the harness's process
        that made the call ({"pid", "started"}), and `run`, the harness's run that made it."""
        if not os.path.exists(db_path(gatherer_id)):
            return Context(), None
        self.poll(gatherer_id)
        conn = self._conn(gatherer_id)
        ids = [store.record_preamble(conn, p["name"], p["text"], self.tokenizer) for p in preamble or ()]
        ctx = self.policy.read(Store(conn, gatherer_id), Read(gatherer_id, dict(properties or {}), row_id, limit,
                                                              fixed_tokens=store.preamble_tokens(conn, preamble)))
        read_id = None
        if ctx.items:
            read_id = store.record_read(conn, properties, ctx.refs, manager=self.policy.name, basis=ctx.basis,
                                        row_id=row_id, est_tokens=ctx.tokens, limit_tokens=limit, preamble_ids=ids,
                                        sent_tokens=self.sent_tokens(conn, ctx, preamble), process=process, run=run)
            notify(gatherer_id, "read", properties, read_id)
        return ctx, read_id

    @staticmethod
    def sent_tokens(conn, ctx: Context, preamble: Optional[List[dict]]) -> int:
        """All a read's context sends -- every item, and the preamble -- by the sizes stored now."""
        rows = store.rows_by_id(conn, [r.row_id for r in ctx.refs if r.row_id is not None])
        made = store.made_items(conn, [r.made_id for r in ctx.refs if r.made_id is not None])
        return (sum(rows[r.row_id].tokens or 0 for r in ctx.refs if r.row_id in rows)
                + sum(made[r.made_id][2] or 0 for r in ctx.refs if r.made_id in made)
                + store.preamble_tokens(conn, preamble))

    def compacted(self, gatherer_id: str, row_id: int, *, properties: Optional[dict] = None,
                  limit: Optional[int] = None, preamble: Optional[List[dict]] = None) -> str:
        """Not part of the interface: the harness compacted its own history, in response to the event
        `row_id` -- the policy builds (its `compacted`, if it has one) and waits for it. What it came
        to, in the policy's words; "" for a policy that does not build, or a gatherer with no database."""
        hook = getattr(self.policy, "compacted", None)
        if hook is None or not os.path.exists(db_path(gatherer_id)):
            return ""
        conn = self._conn(gatherer_id)
        return hook(Store(conn, gatherer_id), Read(gatherer_id, dict(properties or {}), row_id, limit,
                                                   fixed_tokens=store.preamble_tokens(conn, preamble)))

    def requested(self, gatherer_id: str, *, properties: Optional[dict] = None, min_messages: int = 0) -> dict:
        """Not part of the interface: a build a reader asked for, outside any call -- the policy's
        `requested`, if it has one: started in the background, not waited for. What came of it, in the
        policy's words; {} for a policy that does not build, or a gatherer with no database."""
        hook = getattr(self.policy, "requested", None)
        if hook is None or not os.path.exists(db_path(gatherer_id)):
            return {}
        conn = self._conn(gatherer_id)
        return hook(Store(conn, gatherer_id), Read(gatherer_id, dict(properties or {}), store.high_water(conn)),
                    min_messages=min_messages)

    def context_only(self, gatherer_id: str, row_id: int, *, properties: Optional[dict] = None,
                     limit: Optional[int] = None, preamble: Optional[List[dict]] = None) -> Tuple[List[dict], dict]:
        """Not part of the interface: the policy's context for `properties` in response to the event
        `row_id`, as `read_logged` answers it, but read only -- the gatherer's state is as it was:
        nothing polled, no read logged, no build or check started, and whatever else the policy writes
        as it reads (its notices, a build it adopts, a step it stubs) written to a copy of the
        database, thrown away after. For a harness's side call (a prompt suggestion) that should see
        the context the next call would, without being one. (events, {"tokens", "budget", "basis",
        "sent_tokens"}); ([], {}) for a gatherer with no database."""
        if not os.path.exists(db_path(gatherer_id)):
            return [], {}
        conn = self._conn(gatherer_id)
        copy = sqlite3.connect(":memory:", check_same_thread=False)
        try:
            conn.backup(copy)                       # the policy reads, and writes, the copy alone
            jobs, self.policy.jobs = getattr(self.policy, "jobs", None), None
            try:
                ctx = self.policy.read(Store(copy, gatherer_id, db_path(gatherer_id), quiet=True),
                                       Read(gatherer_id, dict(properties or {}), row_id, limit,
                                            fixed_tokens=store.preamble_tokens(conn, preamble)))
            finally:
                self.policy.jobs = jobs
            sizes = {"tokens": ctx.tokens, "budget": ctx.budget, "basis": ctx.basis}
            if not ctx.items:
                return [], sizes
            sizes["sent_tokens"] = self.sent_tokens(copy, ctx, preamble)
            return self.as_events(copy, ctx, made_ids=False), sizes
        finally:
            copy.close()

    def read_events(self, gatherer_id: str, row_id: int, *, properties: Optional[dict] = None) -> List[dict]:
        """Not part of the interface: `read`, as events -- what the server
        answers. A stored event comes back as it was given, `{"type": its
        type's name, "id": its id, "payload": its payload}`; the policy's own
        message is an `ag` message, `{"type": "ag", "name", "text"}`
        (ag/ag_interface/format.py). Any other item a policy made is left
        out."""
        return self.read_logged(gatherer_id, row_id, properties=properties)[0]

    def read_logged(self, gatherer_id: str, row_id: int, *, properties: Optional[dict] = None,
                    limit: Optional[int] = None, preamble: Optional[List[dict]] = None,
                    process: Optional[dict] = None, run: Optional[str] = None) -> Tuple[List[dict], Optional[int], dict]:
        """Not part of the interface: `read_events`, with the read_id the read
        was logged as (None: nothing returned, nothing logged) -- what the
        provider's count of the call is later recorded against (`record_real_tokens`) --
        and its sizes by the policy's count: {"tokens", "budget", "basis"} (`Context`: what the
        policy budgets, its budget, and what it was built from), and "sent_tokens", all the call sends -- every
        item and the preamble -- as the provider counts it too. `limit` is the harness's
        own limit the call stated (`Read.limit`); `preamble`, what it sends besides its
        messages ([{name, text}]); `process`, the harness's process that made the call ({"pid", "started"});
        `run`, the harness's run that made it, as its launcher named it."""
        ctx, read_id = self._context(gatherer_id, row_id, properties, limit, preamble, process, run)
        sizes = {"tokens": ctx.tokens, "budget": ctx.budget, "basis": ctx.basis}
        if not ctx.items:
            return [], None, sizes
        conn = self._conn(gatherer_id)
        sizes["sent_tokens"] = self.sent_tokens(conn, ctx, preamble)          # as the read log keeps it
        return self.as_events(conn, ctx), read_id, sizes

    @staticmethod
    def as_events(conn, ctx: Context, made_ids: bool = True) -> List[dict]:
        """A context as the server answers it: a stored event as it was given, `{"type", "id",
        "payload"}`; the policy's own message an `ag` message, `{"type": "ag", "name", "text"}`, with
        its `made_id` (unless `made_ids` is false: an id in a copy of the database names nothing)."""
        rows = store.rows_by_id(conn, [r.row_id for r in ctx.refs if r.row_id is not None])
        out = []
        for item, ref in zip(ctx.items, ctx.refs):
            if ref.row_id is not None and ref.row_id in rows:
                row = rows[ref.row_id]
                out.append({"type": row.type.name, "id": row.event_id, "payload": row.payload})
            elif is_ag(item):
                ag = {"type": AG, "name": item.get("name"), "text": item["text"]}
                out.append(dict(ag, made_id=ref.made_id) if made_ids else ag)
        return out

    def claim(self, gatherer_id: str, session: str, process: dict, by: str = "call") -> dict:
        """Not part of the interface: `process` ({"pid", "started"}) opens `session`, unless another
        process that still runs has it open and does not yield (`store.claim`): {"claimed", "holder"?,
        "took_over"?}."""
        got = store.claim(self._conn(gatherer_id), session, process, by)
        if got["claimed"]:
            notify(gatherer_id, "open")          # no property named: every stream of the gatherer looks
        return got

    def record_real_tokens(self, gatherer_id: str, read_id: int, tokens: int) -> bool:
        """Not part of the interface: record the provider's count of the context
        read `read_id` returned -- the model call's input tokens, reported after
        it -- for the policy to see on the read log (`last_read`). Whether that
        read exists."""
        if not os.path.exists(db_path(gatherer_id)):
            return False
        found = store.record_real_tokens(self._conn(gatherer_id), read_id, tokens)
        if found:
            notify(gatherer_id, "counts", None, read_id)
        return found

    def record_failed(self, gatherer_id: str, read_id: int, status: Optional[int], error: str) -> bool:
        """Not part of the interface: record that the model call read `read_id` was for failed --
        the HTTP status its endpoint answered (None: none came) and why (`store.record_failed`) --
        for a reader of the gatherer (the dashboard) to tell a turn that stopped on an error from
        one under way. Whether that read exists."""
        if not os.path.exists(db_path(gatherer_id)):
            return False
        found = store.record_failed(self._conn(gatherer_id), read_id, status, error)
        if found:
            notify(gatherer_id, "failed", None, read_id)
        return found

    def record_counts(self, gatherer_id: str, properties: Optional[dict], events: dict, made: dict,
                      preamble: list, left_out: Optional[dict] = None) -> dict:
        """Not part of the interface: sizes the model's provider counted after the fact -- of
        events by id, made items by id, preamble parts (name, text, tokens) -- in place of the
        tokenizer's (`store.record_counts`): what the policy then sizes contexts by."""
        if not os.path.exists(db_path(gatherer_id)):
            return {"events": 0, "made": 0, "preamble": 0}
        counted = store.record_counts(self._conn(gatherer_id), properties, events, made, preamble, left_out)
        if any(counted.values()) or left_out:
            notify(gatherer_id, "counts", properties)
        return counted

    def record_pending(self, gatherer_id: str, properties: Optional[dict], events: List[dict],
                       answer: Optional[str] = None, stop: Optional[str] = None,
                       read_id: Optional[int] = None) -> int:
        """Not part of the interface: keep what the model answered -- its events, {"type",
        "payload", "text"?}, and why it stopped -- until the next call with these properties stores its events
        (`clear_pending`): what a reader of the gatherer can see of an answer no call has
        carried back yet (`store.record_pending`); and on read `read_id`, the one the answered call's
        context came from, when the answer came. How many were kept."""
        kept = store.record_pending(self._conn(gatherer_id), properties, events, answer, stop, read_id)
        if kept:
            notify(gatherer_id, "pending", properties)
        return kept

    def record_recap(self, gatherer_id: str, session: str, text: str) -> int:
        """Not part of the interface: keep a harness's recap of `session` (`store.record_recap`),
        for a reader of the gatherer; never history. Its recap_id."""
        recap_id = store.record_recap(self._conn(gatherer_id), session, text)
        notify(gatherer_id, "recap", None, recap_id)   # no property named: every stream of the gatherer looks
        return recap_id

    def record_name(self, gatherer_id: str, session: str, text: str, by: str) -> None:
        """Not part of the interface: keep `by`'s name for `session` (`store.record_name`), for a reader
        of the gatherer; never history."""
        store.record_name(self._conn(gatherer_id), session, text, by)
        notify(gatherer_id, "name")              # no property named: every stream of the gatherer looks

    def names(self, gatherer_id: str, session: Optional[str] = None) -> List[dict]:
        """Not part of the interface: every session's names, or one session's (`store.names`)."""
        if not os.path.exists(db_path(gatherer_id)):
            return []
        return store.names(self._conn(gatherer_id), session)

    def record_touches(self, gatherer_id: str, session: str, touches: List[dict]) -> int:
        """Not part of the interface: keep what tool calls of `session` did to files, as the hook server
        found them on disk (`store.record_touches`), for a reader of the gatherer; never history. How
        many were kept."""
        kept = store.record_touches(self._conn(gatherer_id), session, touches)
        if kept:
            notify(gatherer_id, "touches")       # no property named: every stream of the gatherer looks
        return kept

    def recaps(self, gatherer_id: str, session: Optional[str] = None) -> List[dict]:
        """Not part of the interface: each session's newest recap, or one session's every recap
        (`store.recaps`)."""
        if not os.path.exists(db_path(gatherer_id)):
            return []
        return store.recaps(self._conn(gatherer_id), session)

    def pending(self, gatherer_id: str, *, properties: Optional[dict] = None) -> List[dict]:
        """Not part of the interface: the pending events with these properties, oldest first
        (`store.pending`)."""
        if not os.path.exists(db_path(gatherer_id)):
            return []
        return store.pending(self._conn(gatherer_id), properties)

    def clear_pending(self, gatherer_id: str, properties: Optional[dict]) -> int:
        """Not part of the interface: delete the pending events with these identifying properties,
        once a call with them has stored new events (`store.clear_pending`). How many."""
        if not os.path.exists(db_path(gatherer_id)):
            return 0
        cleared = store.clear_pending(self._conn(gatherer_id), properties)
        if cleared:
            notify(gatherer_id, "pending", properties)
        return cleared

    def bulk_load(self, gatherer_id: str, events, *, properties: Optional[dict] = None):
        """Not part of the interface: store a whole recorded history in one
        transaction (`store.insert_many`: duplicates skipped, nothing stored
        on an error), each event with `properties` besides its own (its own
        win), then let the policy prepare from it (`Policy.bulk_loaded`, with
        `properties`); returns what the policy returns. The pollers are not
        asked."""
        conn = self._conn(gatherer_id)
        given = dict(properties or {})
        events = [replace(e, properties={**given, **(e.properties or {})}) if given and isinstance(e, Event) else e
                  for e in events]
        store.insert_many(conn, events, self.tokenizer)
        notify(gatherer_id, "events", given)
        return self.policy.bulk_loaded(Store(conn, gatherer_id), gatherer_id, given)
