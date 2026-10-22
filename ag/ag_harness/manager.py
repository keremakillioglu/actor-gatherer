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
        event id with the same properties, and the first insert wins. Without an
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
        return store.insert(conn, event, self.tokenizer, self._spec(gatherer_id, getattr(event, "type_id", None)))

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
        for poller in self.pollers:
            since = store.polled_at(conn, poller.name)
            now = time.time()
            try:
                events = list(poller.poll(since, types))
            except Exception as exc:  # noqa: BLE001 - an outside source must not break a read
                warn(f"poller {poller.name!r} failed: {exc!r}")
                continue
            store.mark_polled(conn, poller.name, now)
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
                    if store.insert(conn, event, self.tokenizer) is not None:
                        stored += 1
                except (TypeError, LookupError, ValueError) as exc:
                    warn(f"poller {poller.name!r}: event refused: {exc}")
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
                 limit: Optional[int] = None) -> Tuple[Context, Optional[int]]:
        """(the policy's context, the read_id it was logged as; None: an empty context, not logged).
        `limit` is the harness's own limit the call stated (`Read.limit`)."""
        if not os.path.exists(db_path(gatherer_id)):
            return Context(), None
        self.poll(gatherer_id)
        conn = self._conn(gatherer_id)
        ctx = self.policy.read(Store(conn, gatherer_id), Read(gatherer_id, dict(properties or {}), row_id, limit))
        read_id = None
        if ctx.items:
            read_id = store.record_read(conn, properties, ctx.refs, manager=self.policy.name, basis=ctx.basis,
                                        row_id=row_id, est_tokens=ctx.tokens, limit_tokens=limit)
        return ctx, read_id

    def read_events(self, gatherer_id: str, row_id: int, *, properties: Optional[dict] = None) -> List[dict]:
        """Not part of the interface: `read`, as events -- what the server
        answers. A stored event comes back as it was given, `{"type": its
        type's name, "id": its id, "payload": its payload}`; the policy's own
        message is an `ag` message, `{"type": "ag", "name", "text"}`
        (ag/ag_interface/format.py). Any other item a policy made is left
        out."""
        return self.read_logged(gatherer_id, row_id, properties=properties)[0]

    def read_logged(self, gatherer_id: str, row_id: int, *, properties: Optional[dict] = None,
                    limit: Optional[int] = None) -> Tuple[List[dict], Optional[int]]:
        """Not part of the interface: `read_events`, with the read_id the read
        was logged as (None: nothing returned, nothing logged) -- what the
        provider's count of the call is later recorded against (`record_real_tokens`).
        `limit` is the harness's own limit the call stated (`Read.limit`)."""
        ctx, read_id = self._context(gatherer_id, row_id, properties, limit)
        if not ctx.items:
            return [], None
        rows = store.rows_by_id(self._conn(gatherer_id), [r.row_id for r in ctx.refs if r.row_id is not None])
        out = []
        for item, ref in zip(ctx.items, ctx.refs):
            if ref.row_id is not None and ref.row_id in rows:
                row = rows[ref.row_id]
                out.append({"type": row.type.name, "id": row.event_id, "payload": row.payload})
            elif is_ag(item):
                out.append({"type": AG, "name": item.get("name"), "text": item["text"]})
        return out, read_id

    def record_real_tokens(self, gatherer_id: str, read_id: int, tokens: int) -> bool:
        """Not part of the interface: record the provider's count of the context
        read `read_id` returned -- the model call's input tokens, reported after
        it -- for the policy to see on the read log (`last_read`). Whether that
        read exists."""
        if not os.path.exists(db_path(gatherer_id)):
            return False
        return store.record_real_tokens(self._conn(gatherer_id), read_id, tokens)

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
        return self.policy.bulk_loaded(Store(conn, gatherer_id), gatherer_id, given)
