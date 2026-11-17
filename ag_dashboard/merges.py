"""Groups merged into another (groups.py's `merge`): each is gone from the dashboard -- its actors, folders and apps are
the other group's now -- while ag's own directory for it is kept (its config, the database it had before `ag home
merge`), as an actor of it may still run under it until it restarts. Kept in the dashboard's own database
(<home>/dashboard.db), so every dashboard on this home leaves it out (data.py's `gatherer_names`). Table
`merged_groups`, one row per group merged:

    gatherer    its name
    into_group  the group it was merged into
    at          when (ISO, UTC)"""

import os
import sqlite3
from datetime import datetime, timezone
from typing import Dict

from . import sessions

SCHEMA = """CREATE TABLE IF NOT EXISTS merged_groups (
    gatherer   TEXT PRIMARY KEY,
    into_group TEXT NOT NULL,
    at         TEXT NOT NULL
)"""


def stored() -> Dict[str, str]:
    """{group merged: the group it went into}, read-only: {} when none is."""
    if not os.path.exists(sessions.db_path()):
        return {}
    conn = sqlite3.connect(f"file:{sessions.db_path()}?mode=ro", uri=True, timeout=8)
    try:
        return {g: into for g, into in conn.execute("SELECT gatherer, into_group FROM merged_groups")}
    except sqlite3.Error:                # no table yet
        return {}
    finally:
        conn.close()


def add(conn: sqlite3.Connection, gatherer: str, into: str) -> None:
    """`gatherer` kept as merged into `into`, on `conn` (the dashboard's database, in the caller's transaction)."""
    conn.execute(SCHEMA)
    conn.execute("INSERT INTO merged_groups (gatherer, into_group, at) VALUES (?, ?, ?) "
                 "ON CONFLICT (gatherer) DO UPDATE SET into_group = excluded.into_group, at = excluded.at",
                 (gatherer, into, datetime.now(timezone.utc).isoformat()))
