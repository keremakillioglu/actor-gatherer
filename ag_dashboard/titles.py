"""The reader's names for gatherers, kept in the dashboard's own database (<home>/dashboard.db, next to
sessions.py's table), so every dashboard on this home shows the same. Table `titles`, one row per gatherer named:

    gatherer  its name: ag's, its directory's, the one every actor and command goes by
    title     the reader's name for it, which the page shows in its place
    at        when it was given (ISO, UTC)

Only what the page shows: the gatherer itself, its directory and its actors keep its name."""

from datetime import datetime, timezone
from typing import Dict

from . import store

TITLE_CHARS = 80
SCHEMA = """CREATE TABLE IF NOT EXISTS titles (
    gatherer TEXT PRIMARY KEY,
    title    TEXT NOT NULL,
    at       TEXT NOT NULL
)"""
store.table("titles", SCHEMA, merged=store.DROP)      # a group merged into another is gone: the other keeps its own name


def stored() -> Dict[str, str]:
    """{gatherer: title}, read-only: {} when nothing is kept yet."""
    with store.reading() as conn:
        if conn is None or not store.has(conn, "titles"):
            return {}
        return {g: t for g, t in conn.execute("SELECT gatherer, title FROM titles ORDER BY gatherer")}


def give(gatherer: str, title: str) -> Dict[str, str]:
    """`title` (one line, its spaces single; "" takes it back) for `gatherer`: every title, after."""
    if not gatherer:
        raise ValueError("which gatherer?")
    title = " ".join((title or "").split())[:TITLE_CHARS].strip()
    with store.transaction("titles") as conn:
        if title and title != gatherer:
            conn.execute("INSERT INTO titles (gatherer, title, at) VALUES (?, ?, ?) "
                         "ON CONFLICT (gatherer) DO UPDATE SET title = excluded.title, at = excluded.at",
                         (gatherer, title, datetime.now(timezone.utc).isoformat()))
        else:
            conn.execute("DELETE FROM titles WHERE gatherer = ?", (gatherer,))
    return stored()
