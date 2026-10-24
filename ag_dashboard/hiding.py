"""Which gatherers the reader hid, kept in the dashboard's own database (<home>/dashboard.db, next
to sessions.py's table), so every dashboard on this home -- another port, a restart, another
browser -- hides the same ones. Table `hiding`, one row per gatherer the reader chose for:

    gatherer  its name
    choice    "hidden": hidden by the reader; "shown": kept in view though it has had nothing
              for a week (which the page hides by itself otherwise)
    at        when it was chosen (ISO, UTC)

A gatherer with no row is left to the page: shown, unless it has had nothing for a week."""

import os
import sqlite3
from datetime import datetime, timezone
from typing import Dict

from . import sessions

CHOICES = ("hidden", "shown")
SCHEMA = """CREATE TABLE IF NOT EXISTS hiding (
    gatherer TEXT PRIMARY KEY,
    choice   TEXT NOT NULL,
    at       TEXT NOT NULL
)"""


def stored() -> Dict[str, str]:
    """{gatherer: "hidden" | "shown"}, read-only: {} when nothing is kept yet."""
    if not os.path.exists(sessions.db_path()):
        return {}
    conn = sqlite3.connect(f"file:{sessions.db_path()}?mode=ro", uri=True, timeout=8)
    try:
        return {g: c for g, c in conn.execute("SELECT gatherer, choice FROM hiding ORDER BY gatherer")}
    except sqlite3.Error:                # no table yet
        return {}
    finally:
        conn.close()


def choose(gatherer: str, choice: str) -> Dict[str, str]:
    """Keep `choice` ("hidden", "shown", or "" to leave it to the page) for `gatherer`: every choice, after."""
    if not gatherer:
        raise ValueError("which gatherer?")
    if choice and choice not in CHOICES:
        raise ValueError(f"a choice is one of {', '.join(CHOICES)}, or empty")
    os.makedirs(os.path.dirname(sessions.db_path()), exist_ok=True)
    conn = sqlite3.connect(sessions.db_path(), timeout=8, isolation_level=None)
    try:
        conn.execute(SCHEMA)
        if choice:
            conn.execute("INSERT INTO hiding (gatherer, choice, at) VALUES (?, ?, ?) "
                         "ON CONFLICT (gatherer) DO UPDATE SET choice = excluded.choice, at = excluded.at",
                         (gatherer, choice, datetime.now(timezone.utc).isoformat()))
        else:
            conn.execute("DELETE FROM hiding WHERE gatherer = ?", (gatherer,))
    finally:
        conn.close()
    return stored()
