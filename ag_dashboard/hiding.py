"""Which gatherers the reader hid, kept in the dashboard's own database (<home>/dashboard.db, next
to sessions.py's table), so every dashboard on this home -- another port, a restart, another
browser -- hides the same ones. Table `hiding`, one row per gatherer the reader chose for:

    gatherer  its name
    choice    "hidden": hidden by the reader; "shown": kept in view though it has had nothing
              for a week (which the page hides by itself otherwise)
    at        when it was chosen (ISO, UTC)

A gatherer with no row is left to the page: shown, unless it has had nothing for a week."""

from datetime import datetime, timezone
from typing import Dict

from . import store

CHOICES = ("hidden", "shown")
SCHEMA = """CREATE TABLE IF NOT EXISTS hiding (
    gatherer TEXT PRIMARY KEY,
    choice   TEXT NOT NULL,
    at       TEXT NOT NULL
)"""
store.table("hiding", SCHEMA, merged=store.DROP)      # a group merged into another is gone, and so is its choice


def stored() -> Dict[str, str]:
    """{gatherer: "hidden" | "shown"}, read-only: {} when nothing is kept yet."""
    with store.reading() as conn:
        if conn is None or not store.has(conn, "hiding"):
            return {}
        return {g: c for g, c in conn.execute("SELECT gatherer, choice FROM hiding ORDER BY gatherer")}


def choose(gatherer: str, choice: str) -> Dict[str, str]:
    """Keep `choice` ("hidden", "shown", or "" to leave it to the page) for `gatherer`: every choice, after."""
    if not gatherer:
        raise ValueError("which gatherer?")
    if choice and choice not in CHOICES:
        raise ValueError(f"a choice is one of {', '.join(CHOICES)}, or empty")
    with store.transaction("hiding") as conn:
        if choice:
            conn.execute("INSERT INTO hiding (gatherer, choice, at) VALUES (?, ?, ?) "
                         "ON CONFLICT (gatherer) DO UPDATE SET choice = excluded.choice, at = excluded.at",
                         (gatherer, choice, datetime.now(timezone.utc).isoformat()))
        else:
            conn.execute("DELETE FROM hiding WHERE gatherer = ?", (gatherer,))
    return stored()
