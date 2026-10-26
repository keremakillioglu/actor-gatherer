"""The trace database: the tables every policy shares, and how a gatherer's
file is opened.

One SQLite file per gatherer (paths.py):

    event_types          every event type the gatherer has: defined at init or added
                         later; its name
    event_type_properties  the properties each type declares, required or not,
                         identifying or not
    events               every event stored, in the order first seen, each of
                         one event type, with the tokenizer's count of each
    _made_items          items a policy MADE (e.g. condensation messages),
                         exactly as sent; never read back as history (internal)
    _reads, _read_items  the read log: what each read returned, in order, and in
                         response to which event (internal)
    _preambles           what harnesses sent besides their messages (system prompts, tool
                         definitions), each text once; a read names its own (internal)
    _polls               when each poller (a source of events from outside the
                         conversation) was last asked (internal)
    _pending             what the model answered that no model call has carried back
                         yet, as events, per channel: kept until that channel's next
                         call stores its events (internal)
    _recaps              the harness's recaps of a session (Claude Code's "while you were
                         away" summary), each with when it was made: never history (internal)
    _names               a session's name, as whoever named it gave it (codex's title for its
                         thread): never history (internal)
    _touches             what each tool call did to files, as the hook server found them on
                         disk once its result was in: never history (internal)

A leading underscore marks a table internal to the manager (`_made_items`,
`_reads`, `_read_items`, `_polls`, `_pending`, `_recaps`, `_names`, `_touches`), which the agent has no reason to know about; the
others (`event_types`, `events`) it may be pointed at. Operations on these
tables are in operations.py.

A policy that keeps state of its own creates its own tables in its `init`, which the manager
calls after `create`; none of them are here.

Event types are not enumerated here or anywhere else in the package: they are
the rows a caller puts in `event_types`, at init or later, and every event
points at one of them. Nor are their PROPERTIES: `events`, `_made_items`, `_reads`
and `_pending` get a column for each property a registered type declares
(`add_properties`, `p_<name>`, NULL = unset), and the unique index on events
covers the identifying ones (`identifying_names`: those a type declares
`identifies`), so an event id is one event per combination of them; the other
properties only describe it, and keep the values it was first stored with.
"""

import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import List, Optional

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
    text        TEXT,               -- the event's readable text, as the caller gave it:
                                    -- what a policy shows and counts of it. NULL: none
    counted     INTEGER             -- 1: `tokens` is the model's provider's count, set after
                                    -- insert (`record_counts`); NULL: the caller's or the tokenizer's
                                    -- given; its payload as JSON stands in
                                    -- (then a p_<name> column per property: add_properties)
);
CREATE INDEX IF NOT EXISTS events_type ON events (event_type_id);

-- The properties each type declares: what its events may carry.
CREATE TABLE IF NOT EXISTS event_type_properties (
    event_type_id INTEGER NOT NULL REFERENCES event_types (event_type_id),
    name        TEXT    NOT NULL,   -- the property; its column is p_<name>
    required    INTEGER NOT NULL,   -- 1: an event of the type must carry it
    identifies  INTEGER NOT NULL DEFAULT 0,   -- 1: part of an event's identity, with its id
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
    tokens      INTEGER,            -- its size, by the manager's tokenizer (or, `counted`, the provider's)
    counted     INTEGER             -- 1: `tokens` is the provider's count (`record_counts`)
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
    limit_tokens INTEGER,           -- the harness's own limit the call stated (where it compacts,
                                    -- or its window ends); NULL = none
    preamble_json TEXT,             -- the harness's preamble the call stated: the _preambles it
                                    -- sent besides its messages, as a JSON list of ids; NULL = none
    sent_tokens INTEGER,            -- all the call sent -- every item and the preamble -- as the
                                    -- manager counted it at the read (less what the harness then
                                    -- left out, as it reports); NULL = not known
    pid         INTEGER,            -- the harness's process that made the call, and when it started
    pid_started TEXT,               -- ("<boot id>:<start ticks>", so a reused pid is not it); NULL = not known
    run         TEXT,               -- the harness's run that made the call, as its launcher named it (the hook
                                    -- server's /r/<run>/: codex's, the id of the process ag started); NULL = none
    error_status INTEGER,           -- the call failed: the HTTP status its endpoint answered; NULL = it did not
                                    -- fail, or no answer came at all (`error` says why)
    error       TEXT,               -- why the call failed, as the hook server saw it: the endpoint's message, or
                                    -- why it could not be reached; NULL = it did not fail, or not known
    answered_at TEXT                -- UTC time the call's answer came back whole (as `_pending` keeps it, but
                                    -- not cleared when a call stores it); NULL = not yet, failed, or not known
);

-- What a harness sends besides its messages -- its system prompt, its tool definitions --
-- each distinct text once (a call names the ones it sent, `_reads.preamble_json`).
CREATE TABLE IF NOT EXISTS _preambles (
    preamble_id INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL,   -- what it is, as the harness names it: "instructions", "tools", ...
    sha         TEXT    NOT NULL UNIQUE,   -- of the name and the text
    text        TEXT    NOT NULL,
    tokens      INTEGER,            -- its size, by the manager's tokenizer (or, `counted`, the provider's)
    counted     INTEGER             -- 1: `tokens` is the provider's count (`record_counts`)
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

-- What the model answered that no model call has carried back yet: the answer's events as
-- the harness made them, kept from when the answer came back until the next call with the
-- same properties (the same channel) stores its events -- the answer among them -- and
-- deletes them. Not history: never read back as events, never in a context.
CREATE TABLE IF NOT EXISTS _pending (
    pending_id  INTEGER PRIMARY KEY,
    received_at TEXT    NOT NULL,   -- (and the properties of the call it answered)
    answer      TEXT,               -- the answer it is part of, as the provider names it; NULL = not named
    stop        TEXT,               -- why that answer stopped, as the provider says it (Anthropic's stop
                                    -- reason: end_turn, tool_use, ...; a Responses status); NULL = not said
    type        TEXT    NOT NULL,   -- the event type's name, as the harness gave it
    payload_json TEXT   NOT NULL,   -- the event's payload, as given
    text        TEXT                -- its readable text, as given; NULL = none
);

-- The events the harness took back: stored for a model call it hung up on before the answer came (the
-- user stopped it), and not in what it sent after -- Claude Code puts the user's message back in its input
-- box. Kept, but in no read (`rows`) and not where a request picks up its history (`latest`). An event
-- sent again is stored again as itself: its row is no longer withdrawn (`insert`).
CREATE TABLE IF NOT EXISTS _withdrawn (
    row_id       INTEGER PRIMARY KEY,  -- the event (an events row)
    withdrawn_at TEXT    NOT NULL,     -- when (UTC, ISO)
    read_id      INTEGER               -- the read of the call it came with; NULL = not known
);

-- A harness's recap of a session: Claude Code's "while you were away" summary, which it asks its model
-- for after a turn when the user has left. Not a turn and not history: never read back as events, never
-- in a context; kept for a reader of the gatherer (the dashboard's actor list), newest last.
CREATE TABLE IF NOT EXISTS _recaps (
    recap_id    INTEGER PRIMARY KEY,
    session     TEXT    NOT NULL,   -- the session: its calls' `channel`
    made_at     TEXT    NOT NULL,   -- when its answer came back (UTC, ISO)
    text        TEXT    NOT NULL    -- the recap, as the model wrote it
);
CREATE INDEX IF NOT EXISTS _recaps_session ON _recaps (session, recap_id);

-- A session's name: one per session and namer, the newest kept -- the harness's (codex's title for its
-- thread, which it asks its model for after the first message) or another's ("user": one typed, which a
-- reader puts before the others). Not history: never read
-- back as events, never in a context; kept for a reader of the gatherer (the dashboard's actor list).
CREATE TABLE IF NOT EXISTS _names (
    session     TEXT    NOT NULL,   -- the session: its calls' `channel`
    by          TEXT    NOT NULL,   -- who named it: "codex", ...
    named_at    TEXT    NOT NULL,   -- when (UTC, ISO)
    text        TEXT    NOT NULL,   -- the name
    PRIMARY KEY (session, by)
);

-- What each tool call of a session did to files, as the hook server found them on disk right after the
-- call ran (ag/integrations/tools/ag_orchestrator/file_touches/): a row per call, file and how; a row with no path says
-- the call was checked and touched no file. Not history: never read back as events, never in a context;
-- kept for a reader of the gatherer (the dashboard's Files view). The first row for a call, file and how
-- is the one kept: the same results sent again (a retried call) are not checked again.
CREATE TABLE IF NOT EXISTS _touches (
    touch_id    INTEGER PRIMARY KEY,
    session     TEXT    NOT NULL,   -- the session: its calls' `channel`
    call_id     TEXT    NOT NULL,   -- the tool call, by the harness's id for it
    at          TEXT    NOT NULL,   -- when it was checked (UTC, ISO)
    path        TEXT,               -- the file, absolute; NULL: the call touched none
    how         TEXT,               -- read, hit, created, modified, deleted
    checked     INTEGER,            -- 1: what the call showed of the file is on disk; 0: it is not; NULL:
                                    -- nothing to match (a change; a read whose lines can't be told apart)
    named       INTEGER,            -- 1: the call names the file; 0: the file changed while the call ran
    detail_json TEXT                -- at which lines, and what (file_touches/check.py); NULL: none
);
CREATE UNIQUE INDEX IF NOT EXISTS _touches_one ON _touches (session, call_id, ifnull(path, ''), ifnull(how, ''));

-- Which process has each session open: one per session, so two processes (a terminal, the
-- dashboard's chat) never run it at once. Claimed by ag's launcher as it starts the harness on a
-- known session, and by each model call of a process the hook server could tell (`claim`); a row
-- whose process has ended holds nothing. A process holds one session: claiming another drops it.
-- A holder that `yields` (the dashboard's chat agent, between its turns: `hold`) gives way: another
-- process's claim stops it and takes the session.
CREATE TABLE IF NOT EXISTS _open (
    session     TEXT    PRIMARY KEY,   -- the session: its calls' `channel`
    pid         INTEGER NOT NULL,      -- the harness's process, and when it started
    pid_started TEXT    NOT NULL,      -- ("<boot id>:<start ticks>", as _reads has it)
    opened_at   TEXT    NOT NULL,
    opened_by   TEXT,                  -- what claimed it: "launcher", "call"
    yields      INTEGER NOT NULL DEFAULT 0   -- 1: idle, and gives way to another process's claim
);
"""


class OutdatedDatabase(RuntimeError):
    """The file was written by an earlier schema: it has an `items` table
    and no `events`, or it holds one event twice by the identity its types
    now declare. It is not migrated; delete it, or load the gatherer
    again."""


#: The tables that carry the properties.
PROPERTY_TABLES = ("events", "_made_items", "_reads", "_pending")


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
        add_column(conn, "events", "text TEXT")                       # a file from before events had text
    for table in ("events", "_made_items", "_preambles"):            # a file from before counts were set
        if "counted" not in {c[1] for c in conn.execute(f"PRAGMA table_info({table})")}:
            add_column(conn, table, "counted INTEGER")
    read_columns = {c[1] for c in conn.execute("PRAGMA table_info(_reads)")}
    for column, kind in (("est_tokens", "INTEGER"), ("real_tokens", "INTEGER"), ("limit_tokens", "INTEGER"),
                         ("preamble_json", "TEXT"), ("sent_tokens", "INTEGER"), ("pid", "INTEGER"),
                         ("pid_started", "TEXT"), ("error_status", "INTEGER"),
                         ("error", "TEXT"), ("answered_at", "TEXT"), ("run", "TEXT")):                           # a file from before reads had them
        if column not in read_columns:
            add_column(conn, "_reads", f"{column} {kind}")
    if "yields" not in {c[1] for c in conn.execute("PRAGMA table_info(_open)")}:     # a file from before holders yielded
        add_column(conn, "_open", "yields INTEGER NOT NULL DEFAULT 0")
    pending_columns = {c[1] for c in conn.execute("PRAGMA table_info(_pending)")}
    if "stop" not in pending_columns:                                # a file from before pending kept it
        add_column(conn, "_pending", "stop TEXT")
    for name in property_names(conn):                                # a file from before _pending: its properties
        if property_column(name) not in pending_columns:
            add_column(conn, "_pending", property_column(name))
    if "identifies" not in {c[1] for c in conn.execute("PRAGMA table_info(event_type_properties)")}:
        add_column(conn, "event_type_properties", "identifies INTEGER NOT NULL DEFAULT 0")
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = 'events_id'").fetchone() is None:
        with writing(conn):                          # a new file: over no property yet
            index(conn, property_names(conn))


def add_column(conn: sqlite3.Connection, table: str, column: str) -> None:
    """`ALTER TABLE table ADD COLUMN column`, unless another connection has just added it."""
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column}")
    except sqlite3.OperationalError as exc:
        if "duplicate column name" not in str(exc):
            raise


@contextmanager
def writing(conn: sqlite3.Connection):
    """A transaction that holds the database's write lock from its start (BEGIN IMMEDIATE), committed
    at the end: what it reads of the schema no other connection changes before it writes. Within a
    transaction already begun, that one."""
    with conn:
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
        yield conn


def property_names(conn: sqlite3.Connection) -> List[str]:
    """The properties the gatherer has columns for, in the order they were added."""
    return [c[len(PREFIX):] for c in (r[1] for r in conn.execute("PRAGMA table_info(events)"))
            if c.startswith(PREFIX)]


def identifying_names(conn: sqlite3.Connection) -> List[str]:
    """The properties that are part of an event's identity -- those a type declares `identifies` --
    in the order they were added."""
    marked = {n for (n,) in conn.execute("SELECT DISTINCT name FROM event_type_properties WHERE identifies = 1")}
    return [n for n in property_names(conn) if n in marked]


def index(conn: sqlite3.Connection, names: List[str]) -> None:
    """(Re)make the unique index on events -- one row per event id per
    combination of identifying properties (`identifying_names`) -- and the
    read log's, over all of `names`. ifnull() because SQLite treats NULLs as
    distinct in a unique index, which would let events with a property unset
    duplicate. event_id is left bare for exactly that reason: rows without an
    id never collide, so each is stored.

    Raises:
        OutdatedDatabase: the events already stored hold one event twice by
            the new identity (a file from before properties were identifying).
    """
    keys = "".join(f"ifnull({property_column(n)}, ''), " for n in identifying_names(conn))
    sql = f"CREATE UNIQUE INDEX events_id ON events ({keys}event_id)"
    found = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'index' AND name = 'events_id'").fetchone()
    if found is None or found[0] != sql:
        conn.execute("DROP INDEX IF EXISTS events_id")
        try:
            conn.execute(sql)
        except sqlite3.IntegrityError as exc:
            file = next((row[2] for row in conn.execute("PRAGMA database_list") if row[1] == "main"), "?")
            raise OutdatedDatabase(f"{file}: holds the same event more than once by its identifying properties "
                                   f"(written before they were declared); delete the gatherer") from exc
    every = "".join(f"ifnull({property_column(n)}, ''), " for n in names)
    sql = f"CREATE INDEX _reads_properties ON _reads ({every}read_id)"
    found = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'index' AND name = '_reads_properties'").fetchone()
    if found is None or found[0] != sql:
        conn.execute("DROP INDEX IF EXISTS _reads_properties")
        conn.execute(sql)


def add_properties(conn: sqlite3.Connection, names) -> None:
    """A column in each of PROPERTY_TABLES for every one of `names` the gatherer
    has none for yet, and the indexes over them all. Its own transaction, which
    looks at the columns again once it holds the write lock (`writing`): another
    connection may have just added them."""
    names, have = list(dict.fromkeys(names)), property_names(conn)
    if all(n in have for n in names):
        return
    with writing(conn):
        have = property_names(conn)
        new = [n for n in names if n not in have]
        for name in new:
            for table in PROPERTY_TABLES:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {property_column(name)}")
        if new:
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


# One open connection per database for each thread, kept until the thread ends
# (`release`). `insert` is called once per event, and the server inserts every
# event of a request on every model call, so opening a connection (and re-running
# the schema) each time would dominate its cost. Per thread, as a connection is
# used by one thread at a time: the server answers each channel's requests on a
# thread of its own, side by side (ag/ag_harness/server/).
_LOCAL = threading.local()


def connection(gatherer_id: str) -> sqlite3.Connection:
    """This thread's connection to the gatherer's database, opened on first use."""
    path = db_path(gatherer_id)
    connections = getattr(_LOCAL, "connections", None)
    if connections is None:
        connections = _LOCAL.connections = {}
    conn = connections.get(path)
    if conn is None:
        conn = connections[path] = connect(gatherer_id)
    return conn


def opened(gatherer_id: str) -> Optional[sqlite3.Connection]:
    """This thread's connection to the gatherer's database, if `connection` has opened one."""
    return (getattr(_LOCAL, "connections", None) or {}).get(db_path(gatherer_id))


def release() -> None:
    """Close this thread's connections (`connection`): what a thread that ends does."""
    connections, _LOCAL.connections = getattr(_LOCAL, "connections", None) or {}, {}
    for conn in connections.values():
        conn.close()
