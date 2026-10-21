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

    {"op": "rewrite", "gatherer", "properties", "cwd", "events", "measured"?, "limit"?}
        -> {"context": [...] or null, "note", "read_id"}   one model call: insert, then read
                                                in response to the last event; null: send
                                                your own. `read_id` names the read, for
                                                `measured`; a `measured` given here is
                                                recorded before the read. `limit` is the
                                                harness's own limit for the call (where it
                                                compacts, or its window ends), in its
                                                provider's tokens; the policy keeps under it
    {"op": "measured", "gatherer", "read_id", "tokens"} -> {"recorded": bool}
                                                the provider's count of read `read_id`'s
                                                context: the call's input tokens, cached
                                                ones included, reported after the call
    {"op": "insert", "gatherer", "properties", "events"} -> {"rows": [row id or null, ...], "last"}
    {"op": "read", "gatherer", "properties", "cwd", "row", "limit"?} -> {"context": [...], "read_id"}
    {"op": "locate", "gatherer", "properties", "event_id"} -> {"row"}      (`id` is the request's own)
    {"op": "init", "gatherer", "event_types"?: [TYPE]} -> {"event_types": [TYPE with its id]}
    {"op": "event_types", "gatherer"} -> {"event_types": [...]}
    {"op": "add_event_type", "gatherer", TYPE's fields} -> {"type_id"}
    {"op": "open", "gatherer", "properties"} -> {"gatherer", "properties", "policy", "pollers", "config", "database"}

where TYPE is {"name", "properties"?: [{"name", "required"?}]}.
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
import sys
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from ag.ag_interface import Event, EventType, Property
from ..store import paths


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
            "properties": [{"name": p.name, "required": p.required} for p in t.properties]}


def type_of(t) -> EventType:
    """The EventType a request's TYPE is.

    Raises:
        BadEvent: it is not {"name": <non-empty>, "properties"?: [{"name", "required"?}]}.
    """
    if not isinstance(t, dict) or not isinstance(t.get("name"), str) or not t["name"]:
        raise BadEvent(f"not an event type: {str(t)[:120]}")
    props = t.get("properties") or []
    if not isinstance(props, list) or not all(isinstance(p, dict) and isinstance(p.get("name"), str) for p in props):
        raise BadEvent(f"event type {t['name']!r}: properties must be [{{name, required?}}], not {str(props)[:120]}")
    return EventType(t["name"], tuple(Property(p["name"], bool(p.get("required"))) for p in props))


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

    def read(self, gatherer: str, properties: Dict[str, Any], cwd: Optional[str], row: int, manager=None,
             limit: Optional[int] = None) -> dict:
        manager = self.with_pollers(manager or self.manager(gatherer), gatherer, cwd)
        context, read_id = manager.read_logged(gatherer, row, properties=properties, limit=limit)
        return {"context": context, "read_id": read_id}

    def measured(self, gatherer: str, read_id: int, tokens: int) -> dict:
        """Record the provider's count of the context read `read_id` returned."""
        return {"recorded": self.manager(gatherer).record_real_tokens(gatherer, read_id, tokens)}

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
                measured: Optional[dict] = None, limit: Optional[int] = None) -> dict:
        """Insert `events`, then read in response to the last. `measured`,
        {"read_id", "tokens"}, is the provider's count of an earlier read's
        context, recorded first, so this read sees it. Never raises: a
        failure anywhere answers a null context."""
        prefix = tag(properties)
        if measured is not None:
            try:
                self.manager(gatherer).record_real_tokens(gatherer, measured["read_id"], measured["tokens"])
            except Exception as exc:  # noqa: BLE001 - a lost count never blocks the call
                self.log(gatherer, prefix + f"could not record the measured size: {exc!r}")
        try:
            manager = self.manager(gatherer)
            last = self.insert(gatherer, properties, events, manager)["last"]
        except Exception as exc:  # noqa: BLE001 - never block the model call
            note = f"insert failed: {exc!r}; messages unchanged"
            self.log(gatherer, prefix + note)
            return {"context": None, "note": note}
        if last is None:
            note = f"{len(events)} events in, no event to respond to; messages unchanged"
            self.log(gatherer, prefix + note)
            return {"context": None, "note": note}
        try:
            answer = self.read(gatherer, properties, cwd, last, manager, limit)
        except Exception as exc:  # noqa: BLE001
            note = f"read failed: {exc!r}; messages unchanged"
            self.log(gatherer, prefix + note)
            return {"context": None, "note": note}
        context = answer["context"]
        ags = sum(1 for e in context if e.get("type") == "ag")
        note = f"{len(events)} events in (event {last}), {len(context)} out ({ags} ag)"
        self.log(gatherer, prefix + note)
        return {"context": context, "note": note, "read_id": answer["read_id"]}

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
                                limit_of(request.get("limit")))
        if op == "measured":
            measured = measured_of(request)
            if measured is None:
                return {"error": "no read_id and tokens"}
            return self.measured(gatherer, measured["read_id"], measured["tokens"])
        if op == "insert":
            if not isinstance(events, list):
                return {"error": "no events"}
            return self.insert(gatherer, properties, events)
        if op == "read":
            if not isinstance(request.get("row"), int):
                return {"error": "no row"}
            return self.read(gatherer, properties, cwd, request["row"], limit=limit_of(request.get("limit")))
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
