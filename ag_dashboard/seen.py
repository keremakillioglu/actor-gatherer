"""When the reader last looked at each actor, kept in the dashboard's own database (<home>/dashboard.db,
next to sessions.py's, hiding.py's and saved.py's tables), so every dashboard on this home shows the same
actors FINISHED (page.html: done since the reader last looked) -- at either address the page is opened at
(localhost, 127.0.0.1: each a browser storage of its own), in any browser, after a restart. Table `seen`,
one row per actor looked at:

    gatherer, channel   the actor
    last                its latest activity (data.py's `last`, in seconds, the server's clock) when looked at
    at                  when it was looked at (ISO, UTC)

A row only moves forward: a look at an older `last` (a page behind the server) keeps the newer one. No
table yet: no dashboard on this home has kept a look, and the page takes every actor as seen."""

import os
import sqlite3
from datetime import datetime, timezone
from typing import Dict, List, Optional

from . import sessions

SCHEMA = """CREATE TABLE IF NOT EXISTS seen (
    gatherer TEXT NOT NULL,
    channel  TEXT NOT NULL,
    last     REAL NOT NULL,
    at       TEXT NOT NULL,
    PRIMARY KEY (gatherer, channel)
)"""


def stored() -> Optional[Dict[str, Dict[str, float]]]:
    """{gatherer: {channel: last}}, read-only: None when none was ever kept (no table yet)."""
    if not os.path.exists(sessions.db_path()):
        return None
    conn = sqlite3.connect(f"file:{sessions.db_path()}?mode=ro", uri=True, timeout=8)
    try:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'seen'").fetchone() is None:
            return None
        found: Dict[str, Dict[str, float]] = {}
        for g, c, last in conn.execute("SELECT gatherer, channel, last FROM seen ORDER BY gatherer, channel"):
            found.setdefault(g, {})[c] = last
        return found
    except sqlite3.Error:                # unreadable for now: nothing seen, not none ever kept
        return {}
    finally:
        conn.close()


def look(looked: List) -> Dict[str, Dict[str, float]]:
    """Each of `looked`, [gatherer, channel, last], looked at with its `last`: every one seen, after."""
    rows = []
    at = datetime.now(timezone.utc).isoformat()
    for item in looked if isinstance(looked, list) else []:
        g, c, last = item if isinstance(item, list) and len(item) == 3 else (None, None, None)
        if not (g and c and isinstance(g, str) and isinstance(c, str)) \
                or not isinstance(last, (int, float)) or isinstance(last, bool):
            raise ValueError("each actor looked at is [gatherer, channel, last]")
        rows.append((g, c, float(last), at))
    if not rows:
        raise ValueError("which actors?")
    os.makedirs(os.path.dirname(sessions.db_path()), exist_ok=True)
    conn = sqlite3.connect(sessions.db_path(), timeout=8, isolation_level=None)
    try:
        conn.execute(SCHEMA)
        conn.executemany("INSERT INTO seen (gatherer, channel, last, at) VALUES (?, ?, ?, ?) "
                         "ON CONFLICT (gatherer, channel) DO UPDATE SET last = excluded.last, at = excluded.at "
                         "WHERE excluded.last > seen.last", rows)
    finally:
        conn.close()
    return stored() or {}
