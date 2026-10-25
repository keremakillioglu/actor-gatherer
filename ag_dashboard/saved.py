"""Which actors the reader saved for later, to come back to and finish: kept in the dashboard's own
database (<home>/dashboard.db, next to sessions.py's and hiding.py's tables), so every dashboard on
this home shows the same ones. Table `saved`, one row per actor saved:

    gatherer, channel   the actor
    at                  when it was saved (ISO, UTC)

A saved actor is never folded away with the closed ones, and its gatherer is not hidden for having
had nothing for a week; it stays saved until the reader unsaves it."""

import os
import sqlite3
from datetime import datetime, timezone
from typing import Dict

from . import sessions

SCHEMA = """CREATE TABLE IF NOT EXISTS saved (
    gatherer TEXT NOT NULL,
    channel  TEXT NOT NULL,
    at       TEXT NOT NULL,
    PRIMARY KEY (gatherer, channel)
)"""


def stored() -> Dict[str, Dict[str, str]]:
    """{gatherer: {channel: when saved}}, read-only: {} when nothing is kept yet."""
    if not os.path.exists(sessions.db_path()):
        return {}
    conn = sqlite3.connect(f"file:{sessions.db_path()}?mode=ro", uri=True, timeout=8)
    try:
        found: Dict[str, Dict[str, str]] = {}
        for g, c, at in conn.execute("SELECT gatherer, channel, at FROM saved ORDER BY gatherer, at"):
            found.setdefault(g, {})[c] = at
        return found
    except sqlite3.Error:                # no table yet
        return {}
    finally:
        conn.close()


def choose(gatherer: str, channel: str, save: bool) -> Dict[str, Dict[str, str]]:
    """The actor saved for later (`save`) or no longer: every one saved, after."""
    if not gatherer or not channel:
        raise ValueError("which actor?")
    os.makedirs(os.path.dirname(sessions.db_path()), exist_ok=True)
    conn = sqlite3.connect(sessions.db_path(), timeout=8, isolation_level=None)
    try:
        conn.execute(SCHEMA)
        if save:                         # saved again: kept from when it was first
            conn.execute("INSERT OR IGNORE INTO saved (gatherer, channel, at) VALUES (?, ?, ?)",
                         (gatherer, channel, datetime.now(timezone.utc).isoformat()))
        else:
            conn.execute("DELETE FROM saved WHERE gatherer = ? AND channel = ?", (gatherer, channel))
    finally:
        conn.close()
    return stored()
