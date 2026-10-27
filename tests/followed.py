"""The hook's following of a harness's own record of a session (ag's session_files.py), for a test: what the record
says since it was last read, inserted as events of the channel into a gatherer's database -- as the hook records them
(records.py's `session_file` and `fact`), each once."""
import json
import sqlite3
import time
from datetime import datetime, timezone

import harness_kit
from harness_kit.base import follow

from ag.integrations.tools.ag_orchestrator.records import fact, session_file


def _stamp():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def insert(conn: sqlite3.Connection, channel: str, events: list) -> None:
    """`events` ({type, id, payload}) stored as the channel's, in whatever schema the test's database has; one whose id
    is stored already is not stored again."""
    types = {r[1] for r in conn.execute("PRAGMA table_info(event_types)")}
    for e in events:
        if conn.execute("SELECT 1 FROM events WHERE event_id = ? AND ifnull(p_channel, '') = ?", (e["id"], channel)).fetchone():
            continue
        got = conn.execute("SELECT event_type_id FROM event_types WHERE name = ?", (e["type"],)).fetchone()
        if got:
            tid = got[0]
        elif "created_at" in types:
            tid = conn.execute("INSERT INTO event_types (name, created_at) VALUES (?, ?)", (e["type"], _stamp())).lastrowid
        else:
            tid = conn.execute("INSERT INTO event_types (name) VALUES (?)", (e["type"],)).lastrowid
        conn.execute("INSERT INTO events (inserted_at, event_id, event_type_id, payload_json, tokens, p_channel) "
                     "VALUES (?, ?, ?, ?, 0, ?)", (_stamp(), e["id"], tid, json.dumps(e["payload"]), channel))
    conn.commit()


class Followed:
    """One session's record, followed: `into` a database, each time what it says since."""

    def __init__(self, harness: str, path: str):
        self.harness, self.path = harness_kit.get(harness), path
        self.follower, self.offset = None, 0

    def into(self, conn: sqlite3.Connection, channel: str, now: float = None) -> None:
        events = []
        if self.follower is None:
            self.follower = self.harness.follower(self.path)
            events.append(session_file(self.harness.name, self.path))
        facts, self.offset = follow(self.path, self.follower, self.offset)
        facts += self.follower.due(time.time() if now is None else now)
        insert(conn, channel, events + [fact(f, self.path) for f in facts])


def schema(conn: sqlite3.Connection) -> sqlite3.Connection:
    """A bare gatherer database's tables, enough for the dashboard to read events by channel from."""
    conn.executescript("""CREATE TABLE IF NOT EXISTS event_types (event_type_id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,
                              created_at TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS events (row_id INTEGER PRIMARY KEY, inserted_at TEXT NOT NULL, event_id TEXT,
                              event_type_id INTEGER NOT NULL, payload_json TEXT NOT NULL, tokens INTEGER NOT NULL, text TEXT,
                              counted INTEGER, p_channel);""")
    return conn
