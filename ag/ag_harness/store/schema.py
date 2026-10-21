"""The trace database: the tables every policy shares, and how a gatherer's
file is opened.

One SQLite file per gatherer (paths.py):

    event_types          every event type the gatherer has: defined at init or added
                         later; its name
    event_type_properties  the properties each type declares, required or not
    events               every event stored, in the order first seen, each of
                         one event type, with the tokenizer's count of each
    _made_items          items a policy MADE (e.g. condensation messages),
                         exactly as sent; never read back as history (internal)
    _reads, _read_items  the read log: what each read returned, in order, and in
                         response to which event (internal)
    _polls               when each poller (a source of events from outside the
                         conversation) was last asked (internal)

A leading underscore marks a table internal to the manager (`_made_items`,
`_reads`, `_read_items`, `_polls`), which the agent has no reason to know about; the
others (`event_types`, `events`) it may be pointed at. Operations on these
tables are in operations.py.

A policy that keeps state of its own creates its own tables in its `init`, which the manager
calls after `create`; none of them are here.

Event types are not enumerated here or anywhere else in the package: they are
the rows a caller puts in `event_types`, at init or later, and every event
points at one of them. Nor are their PROPERTIES: `events`, `_made_items` and
`_reads` get a column for each property a registered type declares
(`add_properties`, `p_<name>`, NULL = unset), and the unique index on events
covers them all, so an event id is one event per combination of properties.
"""

import os
import sqlite3
from typing import List

from ag.ag_interface import property_column

from .paths import db_path

PREFIX = property_column("")

SCHEMA = """
CREATE TABLE IF NOT EXISTS event_types (
    event_type_id INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL UNIQUE,  -- what identifies the type (e.g. user_message)
    created_at  TEXT    NOT NULL    -- UTC time the type was defined
);

CREATE TABLE IF NOT EXISTS events (
    row_id      INTEGER PRIMARY KEY,  -- insertion order; what `read` sorts by. Not
                                      -- AUTOINCREMENT: that spends an id (and a
                                      -- write) on every duplicate DO NOTHING
                                      -- skips. Rows are never deleted, so ids
                                      -- are never reused either way.
    inserted_at TEXT    NOT NULL,   -- UTC time the event was first stored
    event_id    TEXT,               -- the caller's id for the event: what makes a
                                    -- re-sent event a duplicate. NULL = the caller
                                    -- gave none; the row is then its own event,
                                    -- known by row_id, and never a duplicate.
    event_type_id INTEGER NOT NULL REFERENCES event_types (event_type_id),
    payload_json TEXT   NOT NULL,   -- the payload, as given
    tokens      INTEGER NOT NULL,   -- the caller's count if it gave one, else the
                                    -- tokenizer's count of `text` (of payload_json
                                    -- without one), taken at insert
    text        TEXT                -- the event's readable text, as the caller gave it:
                                    -- what a policy shows and counts of it. NULL: none
                                    -- given; its payload as JSON stands in
                                    -- (then a p_<name> column per property: add_properties)
);
CREATE INDEX IF NOT EXISTS events_type ON events (event_type_id);

-- The properties each type declares: what its events may carry.
CREATE TABLE IF NOT EXISTS event_type_properties (
    event_type_id INTEGER NOT NULL REFERENCES event_types (event_type_id),
    name        TEXT    NOT NULL,   -- the property; its column is p_<name>
    required    INTEGER NOT NULL,   -- 1: an event of the type must carry it
    PRIMARY KEY (event_type_id, name)
);

-- Items the manager MADE rather than received: a condensation of earlier
-- history, sent to the model as a message. Stored exactly as sent. Never part
-- of `events`, so never read back as history.
CREATE TABLE IF NOT EXISTS _made_items (
    made_id     INTEGER PRIMARY KEY,
    created_at  TEXT    NOT NULL,   -- (and the properties of the read it was made for)
    name        TEXT,               -- what it is, in the manager's terms
    source      TEXT,               -- what made it, in the manager's terms (e.g. a build)
    item_json   TEXT    NOT NULL,   -- the item, exactly as returned by read
    tokens      INTEGER             -- its size, by the manager's tokenizer
);

-- One row per read: what the manager returned as the context, when, and in
-- response to which event.
CREATE TABLE IF NOT EXISTS _reads (
    read_id     INTEGER PRIMARY KEY,
    read_at     TEXT    NOT NULL,   -- (and the read's properties)
    row_id      INTEGER,            -- the event (an events row) the read responded to
    manager     TEXT,               -- which implementation read
    basis       TEXT,               -- what the context was built from, in the
                                    -- manager's terms (e.g. a build id); NULL = none
    est_tokens  INTEGER,            -- the context's size by the manager's own count; NULL = not given
    real_tokens INTEGER,            -- its size as the model's provider counted it (the
                                    -- call's input tokens, reported after it); NULL = not yet
    limit_tokens INTEGER            -- the harness's own limit the call stated (where it compacts,
                                    -- or its window ends); NULL = none
);

-- What each read returned, in order: a stored event (row_id) or a made item
-- (made_id), exactly one of the two.
CREATE TABLE IF NOT EXISTS _read_items (
    read_id     INTEGER NOT NULL,
    position    INTEGER NOT NULL,
    row_id      INTEGER,
    made_id     INTEGER,
    PRIMARY KEY (read_id, position),
    CHECK ((row_id IS NULL) != (made_id IS NULL))
);
CREATE INDEX IF NOT EXISTS _read_items_row ON _read_items (row_id);

-- When each poller was last asked for this gatherer's events: the moment the
-- next poll starts from.
CREATE TABLE IF NOT EXISTS _polls (
    name        TEXT    PRIMARY KEY,    -- the poller's name
    polled_at   REAL    NOT NULL        -- seconds since the epoch
);
"""


class OutdatedDatabase(RuntimeError):
    """The file was written by an earlier schema: it has an `items` table
    and no `events`. It is not migrated; delete it, or load the gatherer
    again."""


#: The tables that carry the properties.
PROPERTY_TABLES = ("events", "_made_items", "_reads")


def create(conn: sqlite3.Connection) -> None:
    """Create every table that is absent. Idempotent.

    Raises:
        OutdatedDatabase: the file predates the current tables.
    """
    names = {n for (n,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    file = next((row[2] for row in conn.execute("PRAGMA database_list") if row[1] == "main"), "?")
    if "items" in names and "events" not in names:
        raise OutdatedDatabase(f"{file}: written before the events table (it has `items`); "
                               "delete it or load the gatherer again")
    conn.executescript(SCHEMA)
    if "text" not in {c[1] for c in conn.execute("PRAGMA table_info(events)")}:
        conn.execute("ALTER TABLE events ADD COLUMN text TEXT")      # a file from before events had text
    read_columns = {c[1] for c in conn.execute("PRAGMA table_info(_reads)")}
    for column in ("est_tokens", "real_tokens", "limit_tokens"):     # a file from before reads had sizes
        if column not in read_columns:
            conn.execute(f"ALTER TABLE _reads ADD COLUMN {column} INTEGER")
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = 'events_id'").fetchone() is None:
        index(conn, property_names(conn))            # a new file: over no property yet


def property_names(conn: sqlite3.Connection) -> List[str]:
    """The properties the gatherer has columns for, in the order they were added."""
    return [c[len(PREFIX):] for c in (r[1] for r in conn.execute("PRAGMA table_info(events)"))
            if c.startswith(PREFIX)]


def index(conn: sqlite3.Connection, names: List[str]) -> None:
    """(Re)make the unique index on events -- one row per event id per
    combination of properties -- and the read log's, over `names`.
    ifnull() because SQLite treats NULLs as distinct in a unique index, which
    would let events with a property unset duplicate. event_id is left bare
    for exactly that reason: rows without an id never collide, so each is
    stored."""
    keys = "".join(f"ifnull({property_column(n)}, ''), " for n in names)
    conn.execute("DROP INDEX IF EXISTS events_id")
    conn.execute(f"CREATE UNIQUE INDEX events_id ON events ({keys}event_id)")
    conn.execute("DROP INDEX IF EXISTS _reads_properties")
    conn.execute(f"CREATE INDEX _reads_properties ON _reads ({keys}read_id)")


def add_properties(conn: sqlite3.Connection, names) -> None:
    """A column in each of PROPERTY_TABLES for every one of `names` the gatherer
    has none for yet, and the indexes over them all. Its own transaction."""
    have = property_names(conn)
    new = [n for n in dict.fromkeys(names) if n not in have]
    if not new:
        return
    with conn:
        for name in new:
            for table in PROPERTY_TABLES:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {property_column(name)}")
        index(conn, have + new)


def connect(gatherer_id: str) -> sqlite3.Connection:
    """Open the gatherer's database, creating the file, its directory and its
    schema if absent."""
    path = db_path(gatherer_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, timeout=8)
    conn.execute("PRAGMA busy_timeout=8000")
    # WAL with synchronous=NORMAL: a commit does not wait for the disk (with
    # the rollback journal every insert, even a duplicate, paid for fsyncs).
    # A power loss can drop the last few commits, never corrupt the file. WAL
    # also lets readers run while a writer writes. The journal mode is stored
    # in the file, so it holds for every connection.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    # Per connection: every event's type must exist.
    conn.execute("PRAGMA foreign_keys=ON")
    create(conn)
    return conn


# One open connection per database for the life of the process. `insert` is
# called once per event, and the server inserts every event of a request on
# every model call, so opening a connection (and re-running the schema) each time
# would dominate its cost.
_CONNECTIONS = {}


def connection(gatherer_id: str) -> sqlite3.Connection:
    """The process's connection to the gatherer's database, opened on first use."""
    path = db_path(gatherer_id)
    conn = _CONNECTIONS.get(path)
    if conn is None:
        conn = _CONNECTIONS[path] = connect(gatherer_id)
    return conn
