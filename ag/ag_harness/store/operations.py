"""Operations on the database schema.py defines.

    event types register_type (define one; get its id if defined), event_types, has_type
    properties  Spec, spec (what each type declares), property_values
    events      row_of, insert, insert_many, locate; Row, rows, read; high_water
    made items  make_item, made_items
    read log    Ref, record_read, last_read
    polls       polled_at, mark_polled

What a property means is not known here: an event carries the values its
type declares, each in its column, NULL when unset. Two filters read them
back (`rows`): `match`, what a read with those properties sees -- the value,
or unset -- and `differ`, set to anything else.
"""

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ag.ag_interface import Event, EventType, Property, Tokenizer, property_column
from ag.ag_interface.event import PROPERTY_NAME
from ag.ag_interface.store import Ref, Row, event_text  # noqa: F401 - the interface's, used here too

from .schema import add_properties, property_names


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------- event types

def register_type(conn: sqlite3.Connection, event_type: EventType) -> int:
    """Define `event_type` for the gatherer and return its id. A name already
    defined keeps its id, and gains any property it did not declare yet. Each property declared gets its columns
    (`schema.add_properties`). Its own transactions.

    Raises:
        TypeError: `event_type` is not an EventType with a non-empty name,
            or a property of it is not a `Property` with a valid name.
    """
    if not isinstance(event_type, EventType) or not isinstance(event_type.name, str) or not event_type.name:
        raise TypeError(f"an event type must be an EventType with a name, not {event_type!r}")
    for p in event_type.properties:
        if not isinstance(p, Property) or not isinstance(p.name, str) or not PROPERTY_NAME.match(p.name):
            raise TypeError(f"event type {event_type.name!r}: a property must be a Property named with letters, "
                            f"digits and '_', not {p!r}")
    add_properties(conn, [p.name for p in event_type.properties])
    with conn:
        conn.execute("INSERT INTO event_types (name, created_at) VALUES (?, ?) ON CONFLICT (name) DO NOTHING",
                     (event_type.name, _now()))
        type_id = conn.execute("SELECT event_type_id FROM event_types WHERE name = ?",
                               (event_type.name,)).fetchone()[0]
        conn.executemany("INSERT INTO event_type_properties (event_type_id, name, required) VALUES (?, ?, ?) "
                         "ON CONFLICT DO NOTHING", [(type_id, p.name, int(bool(p.required)))
                                                    for p in event_type.properties])
    return type_id


def _declared(conn: sqlite3.Connection) -> Dict[int, Tuple[Property, ...]]:
    out: Dict[int, list] = {}
    for i, n, r in conn.execute("SELECT event_type_id, name, required FROM event_type_properties ORDER BY rowid"):
        out.setdefault(i, []).append(Property(n, bool(r)))
    return {i: tuple(ps) for i, ps in out.items()}


def event_types(conn: sqlite3.Connection) -> List[EventType]:
    """Every type the gatherer has, in the order defined, each with its id and
    its properties."""
    declared = _declared(conn)
    return [EventType(n, declared.get(i, ()), id=i) for i, n in conn.execute(
        "SELECT event_type_id, name FROM event_types ORDER BY event_type_id")]


def has_type(conn: sqlite3.Connection, type_id: int) -> bool:
    return conn.execute("SELECT 1 FROM event_types WHERE event_type_id = ?", (type_id,)).fetchone() is not None


text = event_text


# ---------------------------------------------------------------- properties

@dataclass
class Spec:
    """The gatherer's properties, as an insert checks them: the columns there
    are, in order, and what each type declares. Loaded once (`spec`) and
    kept while no type is added."""
    names: List[str] = field(default_factory=list)
    types: Dict[int, Tuple[str, Dict[str, bool]]] = field(default_factory=dict)   # id -> (name, {property: required})


def spec(conn: sqlite3.Connection) -> Spec:
    declared = _declared(conn)
    return Spec(property_names(conn), {i: (n, {p.name: p.required for p in declared.get(i, ())})
                                       for i, n in conn.execute("SELECT event_type_id, name FROM event_types")})


def _value(name: str, value: Any) -> Any:
    if value is not None and (isinstance(value, bool) or not isinstance(value, (str, int, float))):
        raise TypeError(f"property {name!r} must be a string or a number, not {value!r}")
    return value


def property_values(event: Event, spec: Spec) -> tuple:
    """The event's properties in `spec.names`' order (None: unset), checked
    against what its type declares.

    Raises:
        LookupError: its type is not in `spec`.
        ValueError: it lacks a property its type requires, or carries one
            its type does not declare.
        TypeError: its properties are not a dict of strings and numbers.
    """
    given = event.properties or {}
    if not isinstance(given, dict):
        raise TypeError(f"an event's properties must be a dict, not {given!r}")
    if event.type_id not in spec.types:
        raise LookupError(f"no event type with id {event.type_id!r} in this gatherer; "
                          f"define it with init or add_event_type first")
    type_name, declared = spec.types[event.type_id]
    for name, value in given.items():
        if _value(name, value) is not None and name not in declared:
            raise ValueError(f"event type {type_name!r} declares no property {name!r}"
                             f" (it declares {', '.join(declared) or 'none'})")
    for name, required in declared.items():
        if required and given.get(name) is None:
            raise ValueError(f"event type {type_name!r} requires the property {name!r}")
    return tuple(given.get(n) for n in spec.names)


def _given(conn: sqlite3.Connection, properties: Optional[Dict[str, Any]], what: str) -> tuple:
    """(the gatherer's property names, `properties`' values in their order), for
    a made item or a read. A property the gatherer has no column for may only be
    None."""
    names, given = property_names(conn), properties or {}
    for name, value in given.items():
        if _value(name, value) is not None and name not in names:
            raise ValueError(f"{what}: this gatherer has no property {name!r} (it has {', '.join(names) or 'none'})")
    return names, tuple(given.get(n) for n in names)


def _columns(names: List[str], alias: str = "") -> str:
    return "".join(f", {alias}{property_column(n)}" for n in names)


def _same(names: List[str], alias: str = "") -> str:
    """The SQL for "these properties are exactly these values (unset: '')",
    in the unique index's own terms, so it uses it; one ? per name."""
    return "".join(f"ifnull({alias}{property_column(n)}, '') = ? AND " for n in names)


def _unset_is_empty(values) -> list:
    return ["" if v is None else v for v in values]


def _filter(names: List[str], alias: str, match: Optional[Dict[str, Any]], differ: Optional[Dict[str, Any]],
            unset_matches: bool) -> tuple:
    """(SQL conditions, each ending in AND, params) for `match` and `differ`
    (the interface's GathererStore.rows). A property the gatherer has no column for
    is unset on every event."""
    parts, params = [], []
    for name, value in (match or {}).items():
        col = alias + property_column(name)
        if name not in names:
            parts.append("1" if value is None or unset_matches else "0")
        elif value is None:
            parts.append(f"{col} IS NULL")
        elif unset_matches:
            parts.append(f"({col} = ? OR {col} IS NULL)")
            params.append(value)
        else:
            parts.append(f"{col} = ?")
            params.append(value)
    for name, value in (differ or {}).items():
        col = alias + property_column(name)
        if name not in names:
            parts.append("0")
        else:
            parts.append(f"({col} IS NOT NULL AND {col} IS NOT ?)")
            params.append(value)
    return "".join(f"{p} AND " for p in parts), params


# ---------------------------------------------------------------- events

def check(event: Event) -> None:
    """Raises TypeError unless `event` is an Event with an int `type_id`."""
    if not isinstance(event, Event):
        raise TypeError(f"insert takes an Event, not {type(event).__name__}")
    if not isinstance(event.type_id, int) or isinstance(event.type_id, bool):
        raise TypeError(f"an event's type_id must be an int (an EventType's id), not {event.type_id!r}")


def row_of(event: Event, values: tuple, tokenizer: Tokenizer) -> tuple:
    """The values for one INSERT, in `insert_sql`'s column order; `values`
    are its properties' (`property_values`).

    The payload is serialized with sorted keys. An empty event id is stored
    as NULL. The event's tokens are its own `tokens` if given, else the
    tokenizer's count of its text -- of the JSON, if it has none -- taken
    here, once.

    Raises:
        TypeError: `event` is not an Event, its `type_id` is not an int, or
            its payload is not JSON-serializable.
    """
    check(event)
    raw = json.dumps(event.payload, sort_keys=True, ensure_ascii=False)
    text = event.text if isinstance(event.text, str) else None
    tokens = event.tokens if event.tokens is not None else tokenizer.count(raw if text is None else text)
    return (_now(), event.id or None, event.type_id, raw, tokens, text, *values)


def unknown_type(conn: sqlite3.Connection, exc: sqlite3.IntegrityError, event: Event) -> Exception:
    """The error to raise for a failed INSERT: a LookupError if the event's
    type is not one of the gatherer's, else `exc` itself."""
    if "FOREIGN KEY" in str(exc) and not has_type(conn, event.type_id):
        return LookupError(f"no event type with id {event.type_id!r} in this gatherer; "
                           f"define it with init or add_event_type first")
    return exc


def insert_sql(names: List[str]) -> str:
    return (f"INSERT INTO events (inserted_at, event_id, event_type_id, payload_json, tokens, text{_columns(names)}) "
            f"VALUES (?, ?, ?, ?, ?, ?{', ?' * len(names)}) ON CONFLICT DO NOTHING RETURNING row_id")


def stored(conn: sqlite3.Connection, names: List[str], values: tuple, event_id: str) -> bool:
    """Whether an event with this id and exactly these properties is stored."""
    return conn.execute(f"SELECT 1 FROM events WHERE {_same(names)}event_id = ?",
                        (*_unset_is_empty(values), event_id)).fetchone() is not None


def locate(conn: sqlite3.Connection, properties: Optional[Dict[str, Any]], event_id: str) -> Optional[int]:
    """The row id of the event with this id as a read with `properties` sees
    it -- with each property its value or unset (one not given: unset) --
    whichever was stored first (the one `rows` returns), or None."""
    if not event_id:
        return None
    names = property_names(conn)
    given = properties or {}
    where, params = _filter(names, "", {n: given.get(n) for n in names}, None, True)
    row = conn.execute(f"SELECT min(row_id) FROM events WHERE {where}event_id = ?", (*params, event_id)).fetchone()
    return row[0] if row and row[0] is not None else None


def insert(conn: sqlite3.Connection, event: Event, tokenizer: Tokenizer, spec_: Optional[Spec] = None) -> Optional[int]:
    """Store one event in its own transaction. Returns its row id, or None if
    it was already stored (same id, same properties). An event without an
    id is always stored. `spec_`: the gatherer's (`spec`), if the caller keeps it.

    A re-sent event is recognised by its id BEFORE it is serialized and
    counted: a caller inserts the whole conversation on every model call, and
    tokenizing thousands of events already stored took seconds per call. The
    unique index still catches a race between two processes.

    Raises:
        TypeError: `event` is not an Event with an int `type_id`, or its
            payload is not JSON-serializable. Nothing is stored.
        LookupError: the gatherer has no event type with that id. Nothing is
            stored.
        ValueError: its properties are not what its type declares. Nothing
            is stored.
    """
    check(event)
    sp = spec_ or spec(conn)
    values = property_values(event, sp)
    if event.id and stored(conn, sp.names, values, event.id):
        return None
    row_values = row_of(event, values, tokenizer)
    try:
        with conn:   # committed on return
            row = conn.execute(insert_sql(sp.names), row_values).fetchone()
    except sqlite3.IntegrityError as exc:
        raise unknown_type(conn, exc, event) from exc
    return row[0] if row else None


def insert_many(conn: sqlite3.Connection, events, tokenizer: Tokenizer) -> None:
    """Store a whole history in ONE transaction (a bulk load). Events already
    stored (same id, same properties) are skipped, as `insert` skips them.

    Raises:
        TypeError, LookupError, ValueError: as `insert`. Nothing is stored.
    """
    sp = spec(conn)
    sql = insert_sql(sp.names)
    event = None
    try:
        with conn:
            for event in events:
                check(event)
                conn.execute(sql, row_of(event, property_values(event, sp), tokenizer))
    except sqlite3.IntegrityError as exc:
        raise unknown_type(conn, exc, event) from exc


_FROM = "events e JOIN event_types t ON t.event_type_id = e.event_type_id"


def _select(names: List[str]) -> str:
    return f"e.row_id, e.event_id, t.event_type_id, t.name, e.payload_json, e.tokens, e.text{_columns(names, 'e.')}"


def _row(r, names: List[str]) -> Row:
    return Row(r[0], r[1], EventType(r[3], id=r[2]), json.loads(r[4]), r[5],
               {n: v for n, v in zip(names, r[7:]) if v is not None}, r[6])


def rows_by_id(conn: sqlite3.Connection, row_ids: Iterable[int]) -> dict:
    """{row_id: Row} for the given row ids."""
    ids = sorted(set(row_ids))
    if not ids:
        return {}
    names = property_names(conn)
    marks = ",".join("?" * len(ids))
    return {r[0]: _row(r, names) for r in conn.execute(
        f"SELECT {_select(names)} FROM {_FROM} WHERE e.row_id IN ({marks})", ids)}


def _types_clause(type_ids: Optional[Iterable[int]]) -> tuple:
    """(SQL fragment, params) restricting rows to `type_ids`; ("", ()) for
    None = every type. An empty set matches nothing."""
    if type_ids is None:
        return "", ()
    ids = sorted(set(type_ids))
    if not ids:
        return " AND 0", ()
    return f" AND e.event_type_id IN ({','.join('?' * len(ids))})", tuple(ids)


def rows(conn: sqlite3.Connection, after_row: int = 0, type_ids: Optional[Iterable[int]] = None, *,
         match: Optional[Dict[str, Any]] = None, differ: Optional[Dict[str, Any]] = None,
         unset_matches: bool = True) -> list:
    """Every event whose properties pass `match` and `differ`
    (ag.ag_interface.store), as Rows, in order; only rows after `after_row`,
    and -- with `type_ids` -- only events of those types.

    Without `differ`, an event id is returned once, at the position it was
    first stored among the events that pass: the same event can have a row
    with a property unset and one with it set (bulk-loaded without it, then
    re-sent with it). With `after_row`, an id first stored at or before it is
    not repeated: it is a re-send of something already seen.
    """
    names = property_names(conn)
    clause, params = _types_clause(type_ids)
    where, where_params = _filter(names, "e.", match, differ, unset_matches)
    once, once_params = "", []
    if not differ:
        inner, once_params = _filter(names, "x.", match, None, unset_matches)
        once = (f" AND (e.event_id IS NULL OR e.row_id IN (SELECT min(x.row_id) FROM events x "
                f"WHERE {inner}x.event_id IS NOT NULL GROUP BY x.event_id))")
    sql = f"SELECT {_select(names)} FROM {_FROM} WHERE {where}e.row_id > ?{clause}{once} ORDER BY e.row_id"
    return [_row(r, names) for r in conn.execute(sql, (*where_params, after_row, *params, *once_params))]


def read(conn: sqlite3.Connection, match: Optional[Dict[str, Any]] = None) -> list:
    """The payloads a read with `match`'s properties sees, in order (see `rows`)."""
    return [r.payload for r in rows(conn, match=match)]


# ---------------------------------------------------------------- made items

def make_item(conn: sqlite3.Connection, item: Any, tokenizer: Tokenizer, *,
              properties: Optional[Dict[str, Any]] = None, name: Optional[str] = None,
              source: Optional[str] = None) -> int:
    """Store an item the manager made, with its size and the properties of
    the read it is for; returns its made_id.

    Raises:
        ValueError: a property the gatherer has no column for.
    """
    names, values = _given(conn, properties, "a made item")
    raw = json.dumps(item, ensure_ascii=False)
    with conn:
        cur = conn.execute(
            f"INSERT INTO _made_items (created_at, name, source, item_json, tokens{_columns(names)}) "
            f"VALUES (?, ?, ?, ?, ?{', ?' * len(names)})", (_now(), name, source, raw, tokenizer.count(raw), *values))
    return cur.lastrowid


def made_items(conn: sqlite3.Connection, made_ids) -> dict:
    """{made_id: (name, item, tokens)} for the given ids."""
    ids = list(made_ids)
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    return {m: (n, json.loads(j), t or 0) for m, n, j, t in conn.execute(
        f"SELECT made_id, name, item_json, tokens FROM _made_items WHERE made_id IN ({marks})", ids)}


# ---------------------------------------------------------------- the read log

def record_read(conn: sqlite3.Connection, properties: Optional[Dict[str, Any]], refs, *,
                manager: str, basis: Optional[str] = None, row_id: Optional[int] = None,
                est_tokens: Optional[int] = None, limit_tokens: Optional[int] = None) -> int:
    """Log one read: a `_reads` row (with its properties, `row_id`, the
    event it responded to, `est_tokens`, the context's size by the
    manager's count, and `limit_tokens`, the harness's own limit the call
    stated), and a `_read_items` row per item it returned, in order.
    Returns the read_id."""
    names, values = _given(conn, properties, "a read")
    with conn:
        cur = conn.execute(f"INSERT INTO _reads (read_at, row_id, manager, basis, est_tokens, limit_tokens"
                           f"{_columns(names)}) VALUES (?, ?, ?, ?, ?, ?{', ?' * len(names)})",
                           (_now(), row_id, manager, basis, est_tokens, limit_tokens, *values))
        read_id = cur.lastrowid
        conn.executemany("INSERT INTO _read_items (read_id, position, row_id, made_id) VALUES (?, ?, ?, ?)",
                         [(read_id, i, r.row_id, r.made_id) for i, r in enumerate(refs)])
    return read_id


def last_read(conn: sqlite3.Connection, properties: Optional[Dict[str, Any]] = None) -> Optional[dict]:
    """The most recent read with these properties -- each given one its
    value (None: unset), those not given any value -- {read_id, read_at,
    row_id (the event it responded to), manager, basis, est_tokens,
    real_tokens (None: not reported), limit_tokens (None: none stated),
    refs: [Ref, ...]}, or None."""
    names, _ = _given(conn, properties, "a read")
    given = {n: v for n, v in (properties or {}).items() if n in names}
    row = conn.execute(f"SELECT read_id, read_at, row_id, manager, basis, est_tokens, real_tokens, limit_tokens "
                       f"FROM _reads "
                       f"WHERE {_same(list(given))}1 ORDER BY read_id DESC LIMIT 1",
                       _unset_is_empty(given.values())).fetchone()
    if not row:
        return None
    refs = [Ref(r, m) for r, m in conn.execute(
        "SELECT row_id, made_id FROM _read_items WHERE read_id = ? ORDER BY position", (row[0],))]
    return {"read_id": row[0], "read_at": row[1], "row_id": row[2], "manager": row[3], "basis": row[4],
            "est_tokens": row[5], "real_tokens": row[6], "limit_tokens": row[7], "refs": refs}


def record_real_tokens(conn: sqlite3.Connection, read_id: int, tokens: int) -> bool:
    """Set read `read_id`'s `real_tokens`: the size of the context it
    returned as the model's provider counted it (the call's input tokens,
    cached ones included). Whether that read exists."""
    with conn:
        cur = conn.execute("UPDATE _reads SET real_tokens = ? WHERE read_id = ?", (tokens, read_id))
    return cur.rowcount > 0


def high_water(conn: sqlite3.Connection) -> int:
    """The highest row id stored in the gatherer (whatever its properties); 0 when empty."""
    row = conn.execute("SELECT max(row_id) FROM events").fetchone()
    return row[0] or 0


# ---------------------------------------------------------------- polls

def polled_at(conn: sqlite3.Connection, name: str) -> Optional[float]:
    """When the poller `name` was last asked for this gatherer (seconds since
    the epoch), or None if never."""
    row = conn.execute("SELECT polled_at FROM _polls WHERE name = ?", (name,)).fetchone()
    return row[0] if row else None


def mark_polled(conn: sqlite3.Connection, name: str, at: float) -> None:
    """Record that the poller `name` was asked at `at`."""
    with conn:
        conn.execute("INSERT INTO _polls (name, polled_at) VALUES (?, ?) "
                     "ON CONFLICT (name) DO UPDATE SET polled_at = excluded.polled_at", (name, at))


def last_inserted_at(conn: sqlite3.Connection) -> Optional[str]:
    """When the gatherer's most recent event was first stored (UTC, ISO
    format, whatever its properties), or None when it has none."""
    row = conn.execute("SELECT max(inserted_at) FROM events").fetchone()
    return row[0] if row else None
