"""Groups merged into another (groups.py's `merge`): each is gone from the dashboard -- its actors, folders and apps are
the other group's now -- while ag's own directory for it is kept (its config, the database it had before `ag home
merge`), as an actor of it may still run under it until it restarts. Kept in the dashboard's own database
(<home>/dashboard.db), so every dashboard on this home leaves it out (data.py's `gatherer_names`). Table
`merged_groups`, one row per group merged:

    gatherer    its name
    into_group  the group it was merged into
    at          when (ISO, UTC)"""

import sqlite3
from datetime import datetime, timezone
from typing import Dict

from . import store

SCHEMA = """CREATE TABLE IF NOT EXISTS merged_groups (
    gatherer   TEXT PRIMARY KEY,
    into_group TEXT NOT NULL,
    at         TEXT NOT NULL
)"""
store.table("merged_groups", SCHEMA, merged=store.STAY)   # names a group merged away, kept so; a later merge leaves it


def stored() -> Dict[str, str]:
    """{group merged: the group it went into}, read-only: {} when none is."""
    with store.reading() as conn:
        if conn is None or not store.has(conn, "merged_groups"):
            return {}
        return {g: into for g, into in conn.execute("SELECT gatherer, into_group FROM merged_groups")}


def add(conn: sqlite3.Connection, gatherer: str, into: str) -> None:
    """`gatherer` kept as merged into `into`, on `conn` (the dashboard's database, in the caller's transaction, which
    made the table: store.transaction("merged_groups", ...))."""
    conn.execute("INSERT INTO merged_groups (gatherer, into_group, at) VALUES (?, ?, ?) "
                 "ON CONFLICT (gatherer) DO UPDATE SET into_group = excluded.into_group, at = excluded.at",
                 (gatherer, into, datetime.now(timezone.utc).isoformat()))
