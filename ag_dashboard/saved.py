"""Which actors the reader saved for later, to come back to and finish: kept in the dashboard's own
database (<home>/dashboard.db, next to sessions.py's and hiding.py's tables), so every dashboard on
this home shows the same ones. Table `saved`, one row per actor saved:

    gatherer, channel   the actor
    at                  when it was saved (ISO, UTC)

A saved actor is never folded away with the closed ones, and its gatherer is not hidden for having
had nothing for a week; it stays saved until the reader unsaves it.

A saved actor's process is PUT AWAY (`Rest`) once it has been left unused for REST_SECONDS: the
dashboard's own process for it -- its terminal, or its message box's agent -- ended as a restart ends
it, kept (sessions.py's `put_away`), so it shows Idle and its next message or terminal resumes it.
Unused (`resting`): its turn over, with nothing of it running in the background or waiting on the user;
no activity of it (a call, an event: data.py's `last`), nothing typed into its terminal, no process
started for it, for REST_SECONDS; and no page has it open in a pane (live.py's `shown`). Its status is
read for it alone (data.py's `actors`), not the whole home. A process the dashboard does not run (a
terminal outside it) is never touched."""

import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Set

from . import sessions

REST_SECONDS = 120.0            # how long a saved actor's process is left unused before it is put away
REST_CHECK = 10.0               # how often that is looked at

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


def resting(home: dict, shown: Set[str], now: float) -> List[str]:
    """The sessions whose process to put away (module doc), of data.home()'s `home`: `shown`, the channels
    a page has open."""
    from .data import IDLE              # data imports this module: asked here, once it is loaded
    saved = home.get("saved") or {}
    out = []
    for g in home.get("gatherers") or []:
        mine = saved.get(g["name"]) or {}
        for a in g["agents"]:
            s = a.get("session") or {}
            if not s.get("pid") or not (a["channel"] in mine or s.get("started_as") in mine):
                continue
            if a.get("status") != IDLE or s.get("status") in ("starting", "running") or s.get("queued") \
                    or a["channel"] in shown:
                continue
            used = max(a.get("last") or 0, s.get("typed") or 0, s.get("since") or 0)
            if now - used >= REST_SECONDS:
                out.append(s["session_id"])
    return out


class Rest:
    """Every REST_CHECK seconds, the saved actors' processes left unused put away (module doc): `started`,
    the dashboard's sessions; `shown`, the actors the pages have open ({(gatherer, channel)}: live.py's
    Hub.shown). Of the gatherers, only the actors that may be due are read: saved, with a process of the
    dashboard's, not shown, not started or typed into for REST_SECONDS."""

    def __init__(self, started: "sessions.Sessions", shown: Callable[[], set]):
        self.started, self.shown = started, shown
        self.stop = threading.Event()
        threading.Thread(target=self._run, name="ag-rest", daemon=True).start()

    def check(self, now: Optional[float] = None) -> List[str]:
        """The sessions put away now."""
        from .data import actors            # data imports this module: asked here, once it is loaded
        now = time.time() if now is None else now
        kept = stored()
        names = {c for g in kept.values() for c in g}
        if not names:
            return []
        shown = {c for _, c in self.shown()}
        started = self.started.list()
        maybe: Dict[str, Set[str]] = {}         # gatherer -> its sessions that may be due
        for s in started:
            if s.get("pid") and (s["session_id"] in names or s.get("started_as") in names) and s["session_id"] not in shown \
                    and now - max(s.get("since") or 0, s.get("typed") or 0) >= REST_SECONDS:
                maybe.setdefault(s["gatherer"], set()).add(s["session_id"])
        gatherers = []
        for g, sids in maybe.items():
            try:
                gatherers.append({"name": g, "agents": actors(g, sids, started)})
            except sqlite3.Error:            # not read: left as it is, till the next look
                continue
        return [sid for sid in resting({"saved": kept, "gatherers": gatherers}, shown, now)
                if self.started.put_away(sid, now - REST_SECONDS)]

    def _run(self) -> None:
        while not self.stop.wait(REST_CHECK):
            try:
                self.check()
            except Exception:  # noqa: BLE001 - never stop looking
                pass

    def close(self) -> None:
        self.stop.set()
