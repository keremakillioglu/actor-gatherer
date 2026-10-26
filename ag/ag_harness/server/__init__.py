"""The context manager behind stdio: the one way every harness reaches it.

    <harness> --> ag/integrations/harnesses/<harness>/ag_orchestrator/ --(JSON lines, ag/integrations/tools/ag_connection/)--> python -m ag.ag_harness.server

The server knows no harness. The harness side (`ag/integrations/`) turns its
agent's messages into EVENTS and the context back into messages
(`ag/integrations/harnesses/<harness>/adaptor/`); this side stores the events and runs the
policy.

An event, as the harness side sends it:

    {"type": <type name>, "id": <stable id, or null>, "payload": <any JSON>, "tokens": <int, optional>,
     "text": <string, optional>}

`type` names one of the gatherer's event types -- those its policy declares
(e.g. `user_message`, `tool_call`) -- or any other, added the first time it is
seen (declaring, as optional, the properties the request gives), which no
policy uses. `id` makes a re-sent event a duplicate. `payload` is stored and returned
exactly as given. `text` is its readable text -- a message's words, a tool
call's name and arguments, a tool's output, without the harness's ids and
metadata: what the policies show and count of it (its payload as JSON when
there is none). `tokens` is its cost, if the sender knows better than
counting its text (e.g. 0 for an opaque blob).

The context, as it comes back -- what the model should see, in order:

    {"type": <type name>, "id": ..., "payload": ...}      an event, as it was sent
    {"type": "ag", "name": <what it is>, "text": ...}     the context manager's own message

An `ag` message is text the policy wrote (a condensation of earlier history,
a notice, a stream message; ag/ag_interface/format.py): the harness side decides
how to show it to its model.

One JSON request per line on stdin, one answer per line on stdout, with the
request's `id`. Every request is stateless: the gatherer's manager is made
for it from the gatherer's directory (its gatherer.toml and its database) and
dropped after. `properties` are the request's: every event it inserts
carries them, and its read is made with them -- {name: value}, the names the
policy's event types declare (e.g. {"channel": <the harness's thread>});
none: {}. `cwd` is the working directory the gatherer's pollers look at.

    {"op": "rewrite", "gatherer", "properties", "cwd", "events", "measured"?, "limit"?, "preamble"?, "process"?, "run"?}
        -> {"context": [...] or null, "note", "read_id", "tokens", "budget", "sent_tokens", "basis"}
                                                one model call: insert, then read
                                                in response to the last event; null: send
                                                your own. `read_id` names the read, for
                                                `measured`; a `measured` given here is
                                                recorded before the read. `limit` is the
                                                harness's own limit for the call (where it
                                                compacts, or its window ends), in its
                                                provider's tokens; the policy keeps under it.
                                                `preamble`, [{"name", "text"}], is what the
                                                harness sends besides its messages (its system
                                                prompt, its tool definitions), kept with the read,
                                                as is `process`, {"pid", "started"}: the
                                                harness's process that made the call, and `run`:
                                                the harness's run that made it, as its launcher
                                                named it (codex's: the id of the process ag
                                                started).
                                                `tokens` is the context's size by the policy's
                                                count, `budget` the size it keeps it under (null:
                                                none), `sent_tokens` all the call sends by that
                                                count (every item, and the preamble), `basis`
                                                what it was built from (null: the history as it
                                                is); an `ag` item carries its `made_id`. A harness
                                                that counts the context exactly before sending
                                                it, and finds it over `budget`, reports that
                                                count (`measured`) and asks again
    {"op": "context", "gatherer", "properties", "cwd", "events", "limit"?, "preamble"?}
        -> {"context": [...] or null, "note", "tokens", "budget", "sent_tokens", "basis"}
                                                a rewrite's context, read only: the events are
                                                inserted, then the context the next call would get
                                                is made, and nothing else changes -- nothing
                                                polled, no read logged, no build or check started
                                                (what the policy writes as it reads goes to a
                                                copy of the database). For a side call (a prompt
                                                suggestion) that sees the context without being one
    {"op": "compaction", "gatherer", "properties", "cwd", "events", "limit"?, "preamble"?}
        -> as `context`                         the harness is compacting its own history (Claude
                                                Code's /compact): the events are inserted, the
                                                policy builds -- a build that closes the running
                                                task and is adopted at the next read whatever its
                                                size -- and waits for it, and the context is
                                                answered read only, for the compaction call
    {"op": "measured", "gatherer", "read_id", "tokens"} -> {"recorded": bool}
                                                the provider's count of read `read_id`'s
                                                context: the call's input tokens, cached
                                                ones included, reported after the call (or
                                                counted exactly before it)
    {"op": "failed", "gatherer", "read_id", "status"?, "error"} -> {"recorded": bool}
                                                the model call read `read_id` was for failed:
                                                the HTTP status its endpoint answered (none:
                                                no answer came) and why, kept on the read
                                                (`_reads`) for a reader of the gatherer
    {"op": "counted", "gatherer", "properties", "counts"?: {event_id: n}, "made"?: {made_id: n},
     "preamble_counts"?: [{"name", "text", "tokens"}], "left_out"?: {read_id: n}}
        -> {"events", "made", "preamble"}       sizes the model's provider counted after the
                                                fact (a harness that can ask it), in place of
                                                the tokenizer's: of the events with these ids
                                                (and properties), the made items, the preamble
                                                parts; and what the harness left out of a
                                                read's context before sending it, taken off the
                                                read's sent_tokens. How many of each were found
    {"op": "insert", "gatherer", "properties", "events"} -> {"rows": [row id or null, ...], "last"}
    {"op": "pending", "gatherer", "properties", "events", "answer"?, "stop"?, "read_id"?} -> {"kept"}
                                                what the model answered, as events, which no
                                                call has carried back yet: kept (`_pending`, not
                                                as events, ids ignored) until the next rewrite,
                                                context or compaction with the same properties
                                                stores new events, and then deleted; a call that
                                                stores none (Claude Code's idle compaction, whose
                                                history ends before the reply) keeps them. `answer`
                                                names the answer (the provider's id), `stop`
                                                why it stopped (end_turn, tool_use, ...), or
                                                "streaming": the parts of an answer complete
                                                while it streams, each time replacing those kept
                                                for it before, until all of it does (a named
                                                answer's events always replace its earlier
                                                ones; none drops them); a rewrite that stores
                                                nothing drops those still streaming;
                                                `read_id`, the read the answered call's
                                                context came from: when the answer came is
                                                kept on it (`_reads.answered_at`), for good
    {"op": "recap", "gatherer", "session", "text"} -> {"recap_id"}
                                                the harness's recap of a session (Claude Code's
                                                "while you were away" summary), kept with when it
                                                was made (`_recaps`): never an event, never in a
                                                context; for a reader of the gatherer
    {"op": "name", "gatherer", "session", "text", "by"} -> {}
                                                a session's name as `by` gave it (codex's title
                                                for its thread), in place of the one `by` gave
                                                before (`_names`): never an event, never in a
                                                context; for a reader of the gatherer
    {"op": "touches", "gatherer", "session", "touches": [...]} -> {"kept"}
                                                what the session's tool calls did to files, as
                                                the harness side found them on disk once each
                                                call's result was in (ag/integrations/tools/
                                                file_touches/): each {"call_id", "path"?, "how"?,
                                                "checked"?, "named"?, "detail"?}, kept (`_touches`)
                                                for a reader of the gatherer; never history
    {"op": "read", "gatherer", "properties", "cwd", "row", "limit"?, "process"?, "run"?} -> {"context": [...], "read_id", "tokens", "budget", "sent_tokens", "basis"}
    {"op": "claim", "gatherer", "session", "process", "by"?} -> {"claimed": true, "took_over"?} or {"claimed": false, "holder"}
                                                `process` ({"pid", "started"}) opens the session
                                                (`_open`), unless another process that still runs
                                                has it and does not yield: then `holder`, that one
                                                ({"pid", "started", "opened_at", "opened_by"}), and
                                                nothing changes. One that yields (idle: the
                                                dashboard's agent between turns) is stopped, and
                                                named `took_over`. A harness's call is refused when
                                                it is not claimed
    {"op": "locate", "gatherer", "properties", "event_id"} -> {"row"}      (`id` is the request's own)
    {"op": "init", "gatherer", "event_types"?: [TYPE]} -> {"event_types": [TYPE with its id]}
    {"op": "event_types", "gatherer"} -> {"event_types": [...]}
    {"op": "add_event_type", "gatherer", TYPE's fields} -> {"type_id"}
    {"op": "open", "gatherer", "properties"} -> {"gatherer", "properties", "policy", "pollers", "config", "database"}

where TYPE is {"name", "properties"?: [{"name", "required"?, "identifies"?}]}.
    {"op": "ping"} -> {"pong": true}

A request that fails is answered `{"id", "error"}`; a rewrite that fails is
answered with a null context, so the harness sends its own messages.
Nothing but answers is written to stdout: whatever else would go there (a
print in a policy or a plugin) goes to stderr. Requests are answered one at
a time, in the order they arrive. What each request came to goes to the
gatherer's `server.log` (`logs/gatherers/<gatherer>/`).
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from ag.ag_interface import Event, EventType, Property
from ..store import paths
from ..store.operations import STREAMING


def log_line(gatherer: str, line: str) -> None:
    """A line on stderr, and in the gatherer's server.log."""
    print(f"[{gatherer}] {line}", file=sys.stderr, flush=True)
    path = paths.server_log(gatherer)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {line}\n")
    except OSError:
        pass


def _type(t: EventType) -> dict:
    return {"id": t.id, "name": t.name,
            "properties": [{"name": p.name, "required": p.required, "identifies": p.identifies}
                           for p in t.properties]}


def type_of(t) -> EventType:
    """The EventType a request's TYPE is.

    Raises:
        BadEvent: it is not {"name": <non-empty>, "properties"?: [{"name", "required"?, "identifies"?}]}.
    """
    if not isinstance(t, dict) or not isinstance(t.get("name"), str) or not t["name"]:
        raise BadEvent(f"not an event type: {str(t)[:120]}")
    props = t.get("properties") or []
    if not isinstance(props, list) or not all(isinstance(p, dict) and isinstance(p.get("name"), str) for p in props):
        raise BadEvent(f"event type {t['name']!r}: properties must be [{{name, required?, identifies?}}], "
                       f"not {str(props)[:120]}")
    return EventType(t["name"], tuple(Property(p["name"], bool(p.get("required")), bool(p.get("identifies")))
                                      for p in props))


def properties_of(request: dict) -> Dict[str, Any]:
    """The request's properties.

    Raises:
        BadEvent: they are not an object.
    """
    props = request.get("properties")
    if props is None:
        return {}
    if not isinstance(props, dict):
        raise BadEvent(f"properties must be an object, not {str(props)[:120]}")
    return props


def limit_of(value) -> Optional[int]:
    """A harness's stated limit: a positive int, else None (none stated)."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def preamble_of(value) -> Optional[List[dict]]:
    """A harness's stated preamble: the [{"name", "text"}] whose name and text are non-empty
    strings; None for none."""
    if not isinstance(value, list):
        return None
    out = [{"name": p["name"], "text": p["text"]} for p in value
           if isinstance(p, dict) and isinstance(p.get("name"), str) and p["name"] and isinstance(p.get("text"), str) and p["text"]]
    return out or None


def process_of(value) -> Optional[dict]:
    """A harness's process, as the hook server found it: {"pid": a positive int, "started": a
    non-empty string}; None if it is not one."""
    if not isinstance(value, dict):
        return None
    pid, started = value.get("pid"), value.get("started")
    if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0 and isinstance(started, str) and started:
        return {"pid": pid, "started": started[:200]}
    return None


def run_of(value) -> Optional[str]:
    """A harness's run, as its launcher named it: letters, digits, `.`, `_` and `-`; None if it is not one."""
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9._-]{1,64}", value) else None


def counted_of(request) -> Optional[tuple]:
    """(events {id: tokens}, made {made_id: tokens}, preamble [(name, text, tokens)], left_out
    {read_id: tokens}) from a `counted` request, what is not a whole number of tokens left out;
    None if it holds none."""
    def size(v):
        return isinstance(v, int) and not isinstance(v, bool) and v >= 0
    events = {k: v for k, v in (request.get("counts") or {}).items() if isinstance(k, str) and size(v)} \
        if isinstance(request.get("counts"), dict) else {}
    made = {}
    for k, v in (request.get("made") or {}).items() if isinstance(request.get("made"), dict) else ():
        if str(k).isdigit() and size(v):
            made[int(k)] = v
    preamble = [(p["name"], p["text"], p["tokens"]) for p in request.get("preamble_counts") or ()
                if isinstance(p, dict) and isinstance(p.get("name"), str) and isinstance(p.get("text"), str)
                and size(p.get("tokens"))]
    left_out = {}
    for k, v in (request.get("left_out") or {}).items() if isinstance(request.get("left_out"), dict) else ():
        if str(k).isdigit() and size(v):
            left_out[int(k)] = v
    return (events, made, preamble, left_out) if events or made or preamble or left_out else None


def measured_of(value) -> Optional[dict]:
    """{"read_id", "tokens"} from a `measured` (or a `measured` request), both
    positive ints; None if it is not one -- a size that is not given, or not
    one, is no size."""
    if not isinstance(value, dict):
        return None
    read_id, tokens = value.get("read_id"), value.get("tokens")
    ok = all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in (read_id, tokens))
    return {"read_id": read_id, "tokens": tokens} if ok else None


def tag(properties: Dict[str, Any]) -> str:
    """How the log shows a request's properties: `[v1/v2] `, or nothing."""
    values = [str(v) for v in properties.values() if v is not None]
    return f"[{'/'.join(values)}] " if values else ""


class BadEvent(ValueError):
    """An event that is not `{"type": <non-empty name>, "payload", ...}`."""


class Server:
    """The manager functions, over generic events.

    Args:
        factory: (gatherer) -> a new manager (a `Manager`).
        pollers: (gatherer, cwd or None) -> the gatherer's pollers for a read.
        log: (gatherer, line) -> None.
        describe: (gatherer) -> what `open` answers besides the gatherer.
    """

    def __init__(self, factory: Callable, pollers: Callable = lambda gatherer, cwd: [],
                 log: Callable[[str, str], None] = lambda gatherer, line: None,
                 describe: Callable = lambda gatherer: {}):
        self.factory, self.pollers, self.log, self.describe = factory, pollers, log, describe

    def manager(self, gatherer: str):
        """A manager for one request, made from the gatherer's directory
        (`factory`, then `init`). None is kept."""
        created = not os.path.exists(paths.db_path(gatherer))
        manager = self.factory(gatherer)
        manager.init(gatherer)
        if created:
            self.log(gatherer, f"gatherer {gatherer} created ({manager.name})")
        return manager

    def with_pollers(self, manager, gatherer: str, cwd: Optional[str]):
        """The manager, with the gatherer's pollers for `cwd` (none, if they
        cannot be made: a bad poller config must not block the call)."""
        try:
            manager.set_pollers(list(self.pollers(gatherer, cwd)))
        except Exception as exc:  # noqa: BLE001
            self.log(gatherer, f"pollers failed: {exc}; none this call")
            manager.set_pollers([])
        return manager

    @staticmethod
    def events_of(manager, gatherer: str, events: list, properties: Dict[str, Any]) -> List[Event]:
        """The Events `events` are, their types named, each with
        `properties`: a name the gatherer does not have is added, declaring each of `properties` as optional."""
        ids: Dict[str, int] = {t.name: t.id for t in manager.event_types(gatherer)}
        out = []
        for e in events:
            if not isinstance(e, dict) or not isinstance(e.get("type"), str) or not e["type"] or "payload" not in e:
                raise BadEvent(f"not an event: {str(e)[:120]}")
            name = e["type"]
            if name not in ids:
                ids[name] = manager.add_event_type(gatherer, EventType(name, tuple(Property(p) for p in properties)))
            tokens, text = e.get("tokens"), e.get("text")
            out.append(Event(ids[name], e["payload"], id=e.get("id") or None,
                             tokens=tokens if isinstance(tokens, int) else None, properties=dict(properties),
                             text=text if isinstance(text, str) else None))
        return out

    # ---- the manager functions

    def insert(self, gatherer: str, properties: Dict[str, Any], events: list, manager=None) -> dict:
        manager = manager or self.manager(gatherer)
        stored = self.events_of(manager, gatherer, events, properties)
        rows = [manager.insert(gatherer, e) for e in stored]
        last = rows[-1] if rows else None
        if stored and last is None and stored[-1].id:          # the last one was already stored
            last = manager.locate(gatherer, stored[-1].id, properties=properties)
        return {"rows": rows, "last": last}

    def pending(self, gatherer: str, properties: Dict[str, Any], events: list, answer=None, stop=None,
                read_id=None) -> dict:
        """Keep what the model answered until the channel's next call stores its events; and when it
        came, on the read its call's context came from."""
        for e in events:
            if not isinstance(e, dict) or not isinstance(e.get("type"), str) or not e["type"] or "payload" not in e:
                raise BadEvent(f"not an event: {str(e)[:120]}")
        kept = self.manager(gatherer).record_pending(gatherer, properties, events,
                                                     answer if isinstance(answer, str) else None,
                                                     stop if isinstance(stop, str) else None,
                                                     read_id if isinstance(read_id, int) and not isinstance(read_id, bool)
                                                     else None)
        self.log(gatherer, tag(properties) + f"{kept} events pending")
        return {"kept": kept}

    def read(self, gatherer: str, properties: Dict[str, Any], cwd: Optional[str], row: int, manager=None,
             limit: Optional[int] = None, preamble: Optional[List[dict]] = None,
             process: Optional[dict] = None, run: Optional[str] = None) -> dict:
        manager = self.with_pollers(manager or self.manager(gatherer), gatherer, cwd)
        context, read_id, sizes = manager.read_logged(gatherer, row, properties=properties, limit=limit,
                                                      preamble=preamble, process=process, run=run)
        return {"context": context, "read_id": read_id, **sizes}

    def measured(self, gatherer: str, read_id: int, tokens: int) -> dict:
        """Record the provider's count of the context read `read_id` returned."""
        return {"recorded": self.manager(gatherer).record_real_tokens(gatherer, read_id, tokens)}

    def failed(self, gatherer: str, read_id: int, status: Optional[int], error: str) -> dict:
        """Record that the model call read `read_id` was for failed: its endpoint's status, and why."""
        recorded = self.manager(gatherer).record_failed(gatherer, read_id, status, error)
        if recorded:
            self.log(gatherer, f"read {read_id}: the call failed ({status or 'no answer'}): {error[:300]}")
        return {"recorded": recorded}

    def counted(self, gatherer: str, properties: Dict[str, Any], events: dict, made: dict, preamble: list,
                left_out: Optional[dict] = None) -> dict:
        """Record sizes the model's provider counted after the fact, in place of the tokenizer's."""
        return self.manager(gatherer).record_counts(gatherer, properties, events, made, preamble, left_out)

    def locate(self, gatherer: str, properties: Dict[str, Any], event_id: str) -> dict:
        return {"row": self.manager(gatherer).locate(gatherer, event_id, properties=properties)}

    def init(self, gatherer: str, event_types=()) -> dict:
        manager = self.manager(gatherer)
        for t in event_types or ():
            manager.add_event_type(gatherer, type_of(t))
        return {"event_types": [_type(t) for t in manager.event_types(gatherer)]}

    def event_types(self, gatherer: str) -> dict:
        return {"event_types": [_type(t) for t in self.manager(gatherer).event_types(gatherer)]}

    def add_event_type(self, gatherer: str, event_type: EventType) -> dict:
        return {"type_id": self.manager(gatherer).add_event_type(gatherer, event_type)}

    # ---- one model call

    def rewrite(self, gatherer: str, properties: Dict[str, Any], cwd: Optional[str], events: list,
                measured: Optional[dict] = None, limit: Optional[int] = None,
                preamble: Optional[List[dict]] = None, read_only: bool = False, compacted: bool = False,
                process: Optional[dict] = None, run: Optional[str] = None) -> dict:
        """Insert `events`, then read in response to the last. `measured`,
        {"read_id", "tokens"}, is the provider's count of an earlier read's
        context, recorded first, so this read sees it. With `read_only`, the
        context only (`Manager.context_only`): nothing else of the gatherer's
        state changes, and there is no read_id. With `compacted` (read only
        too), the harness compacted its history: the policy builds first, and
        waits for it (`Manager.compacted`). Never raises: a failure anywhere
        answers a null context."""
        prefix = tag(properties)
        if measured is not None:
            try:
                self.manager(gatherer).record_real_tokens(gatherer, measured["read_id"], measured["tokens"])
            except Exception as exc:  # noqa: BLE001 - a lost count never blocks the call
                self.log(gatherer, prefix + f"could not record the measured size: {exc!r}")
        try:
            manager = self.manager(gatherer)
            inserted = self.insert(gatherer, properties, events, manager)
            last = inserted["last"]
        except Exception as exc:  # noqa: BLE001 - never block the model call
            note = f"insert failed: {exc!r}; messages unchanged"
            self.log(gatherer, prefix + note)
            return {"context": None, "note": note}
        try:
            if any(r is not None for r in inserted["rows"]):    # it stored something: the answers kept with it
                manager.clear_pending(gatherer, properties)
            elif not read_only:                                 # the channel's next turn: an answer still
                manager.clear_pending(gatherer, properties, STREAMING)   # streaming broke off (a retry's)
        except Exception as exc:  # noqa: BLE001 - stale pending events never block the call
            self.log(gatherer, prefix + f"could not clear the pending events: {exc!r}")
        if last is None:
            note = f"{len(events)} events in, no event to respond to; messages unchanged"
            self.log(gatherer, prefix + note)
            return {"context": None, "note": note}
        built = ""
        if compacted:
            try:
                built = manager.compacted(gatherer, last, properties=properties, limit=limit, preamble=preamble)
            except Exception as exc:  # noqa: BLE001 - a failed build never blocks the call
                built = f"failed: {exc!r}"
        try:
            if read_only:
                context, sizes = manager.context_only(gatherer, last, properties=properties, limit=limit,
                                                      preamble=preamble)
                answer = {"context": context, "read_id": None, **sizes}
            else:
                answer = self.read(gatherer, properties, cwd, last, manager, limit, preamble, process, run)
        except Exception as exc:  # noqa: BLE001
            note = f"read failed: {exc!r}; messages unchanged"
            self.log(gatherer, prefix + note)
            return {"context": None, "note": note}
        context = answer["context"]
        ags = sum(1 for e in context if e.get("type") == "ag")
        note = f"{len(events)} events in (event {last}), {len(context)} out ({ags} ag)" + (" read only" if read_only else "") \
            + (f", compaction build: {built or 'none'}" if compacted else "")
        self.log(gatherer, prefix + note)
        return {"context": context, "note": note, "read_id": answer["read_id"],
                **{k: answer.get(k) for k in ("tokens", "budget", "sent_tokens", "basis")}}

    def open(self, gatherer: str, properties: Dict[str, Any]) -> dict:
        self.manager(gatherer)
        return dict({"gatherer": gatherer, "properties": properties}, **self.describe(gatherer))

    # ---- requests

    def handle(self, request: dict) -> dict:
        """The answer to one request (without its id)."""
        op = request.get("op")
        if op == "ping":
            return {"pong": True}
        gatherer = request.get("gatherer")
        if not isinstance(gatherer, str) or not gatherer:
            return {"error": "no gatherer"}
        properties, cwd, events = properties_of(request), request.get("cwd"), request.get("events")
        if op == "rewrite":
            if not isinstance(events, list):
                return {"context": None, "note": "no events; messages unchanged"}
            return self.rewrite(gatherer, properties, cwd, events, measured_of(request.get("measured")),
                                limit_of(request.get("limit")), preamble_of(request.get("preamble")),
                                process=process_of(request.get("process")), run=run_of(request.get("run")))
        if op in ("context", "compaction"):
            if not isinstance(events, list):
                return {"context": None, "note": "no events; messages unchanged"}
            return self.rewrite(gatherer, properties, cwd, events, None, limit_of(request.get("limit")),
                                preamble_of(request.get("preamble")), read_only=True, compacted=op == "compaction")
        if op == "measured":
            measured = measured_of(request)
            if measured is None:
                return {"error": "no read_id and tokens"}
            return self.measured(gatherer, measured["read_id"], measured["tokens"])
        if op == "failed":
            read_id, status, error = request.get("read_id"), request.get("status"), request.get("error")
            if not isinstance(read_id, int) or isinstance(read_id, bool) or not isinstance(error, str) or not error:
                return {"error": "no read_id and error"}
            return self.failed(gatherer, read_id, status if isinstance(status, int) and not isinstance(status, bool) else None,
                               error)
        if op == "counted":
            sizes = counted_of(request)
            if sizes is None:
                return {"error": "no counts"}
            return self.counted(gatherer, properties, *sizes)
        if op == "insert":
            if not isinstance(events, list):
                return {"error": "no events"}
            return self.insert(gatherer, properties, events)
        if op == "pending":
            if not isinstance(events, list):
                return {"error": "no events"}
            return self.pending(gatherer, properties, events, request.get("answer"), request.get("stop"),
                                request.get("read_id"))
        if op == "recap":
            session, text = request.get("session"), request.get("text")
            if not isinstance(session, str) or not session or not isinstance(text, str) or not text.strip():
                return {"error": "no session and text"}
            recap_id = self.manager(gatherer).record_recap(gatherer, session, text.strip())
            self.log(gatherer, f"[{session}] recap kept")
            return {"recap_id": recap_id}
        if op == "name":
            session, text, by = request.get("session"), request.get("text"), request.get("by")
            if not all(isinstance(x, str) and x.strip() for x in (session, text, by)):
                return {"error": "no session, text and by"}
            self.manager(gatherer).record_name(gatherer, session, " ".join(text.split()), by)
            self.log(gatherer, f"[{session}] named by {by}")
            return {}
        if op == "touches":
            session, touches = request.get("session"), request.get("touches")
            if not isinstance(session, str) or not session or not isinstance(touches, list):
                return {"error": "no session and touches"}
            kept = self.manager(gatherer).record_touches(gatherer, session, [t for t in touches if isinstance(t, dict)])
            self.log(gatherer, f"[{session}] {kept} file touches kept")
            return {"kept": kept}
        if op == "read":
            if not isinstance(request.get("row"), int):
                return {"error": "no row"}
            return self.read(gatherer, properties, cwd, request["row"], limit=limit_of(request.get("limit")),
                             process=process_of(request.get("process")), run=run_of(request.get("run")))
        if op == "claim":
            process, session = process_of(request.get("process")), request.get("session")
            if process is None or not isinstance(session, str) or not session:
                return {"error": "no session and process"}
            return self.manager(gatherer).claim(gatherer, session, process, str(request.get("by") or "call")[:40])
        if op == "locate":
            if not isinstance(request.get("event_id"), str):
                return {"error": "no event_id"}
            return self.locate(gatherer, properties, request["event_id"])
        if op == "init":
            return self.init(gatherer, request.get("event_types"))
        if op == "event_types":
            return self.event_types(gatherer)
        if op == "add_event_type":
            if not isinstance(request.get("name"), str) or not request["name"]:
                return {"error": "no name"}
            return self.add_event_type(gatherer, type_of(request))
        if op == "open":
            return self.open(gatherer, properties)
        return {"error": f"no op {op!r}"}

    def answer(self, request: dict) -> dict:
        """The answer to `request`, with its id; never raises."""
        try:
            result = self.handle(request)
        except Exception as exc:  # noqa: BLE001
            result = {"error": f"{type(exc).__name__}: {exc}"}
        return dict(result, id=request.get("id"))


def serve(server: Server, lines, out) -> None:
    """Answer each JSON line of `lines` on `out`, one line per answer, in
    order, until `lines` ends."""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except ValueError as exc:
            result = {"id": None, "error": f"not JSON: {exc}"}
        else:
            result = server.answer(request) if isinstance(request, dict) else {"id": None, "error": "not an object"}
        out.write(json.dumps(result, ensure_ascii=False) + "\n")
        out.flush()
