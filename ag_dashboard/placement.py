"""Where each thing of the home is now, in its one database (ag's `paths.merged`): read from ag's records once per change
of them, and kept, so every part of the dashboard that asks reads the same answer.

    groups    {channel: its group}, as its latest `group` record names it
    folders   {id: {id, group, parent, name, at, closed}}, the folders there are (`folder` records; a gone one, none)
    placed    {item: (group, folder id or None)}: each actor's, by its `group` records; each app's and each group placed
              in another, by their `filed` records (items "app:<id>", "group:<name>": folders.py's)
    top       the highest folder id ever kept, gone or not (folders.py makes the next above it)
    apps      {instance: its group}: opened in it (`app_opened`), or moved to it since (`app_regrouped`), as the app
              host reads them
    changed   {group: when what it holds last changed}: the latest `group`, `folder` or `filed` record naming it, as
              where something went or where it left (`was`)

Before the home's one database (a database per gatherer), nothing: each gatherer's is its own, and holds all of it.

`now()` reads the home's; `of(conn)` reads the database `conn` is on. Each is read again only once a record of these
types has been added since (the last of their row ids, how many, and their sum). A database or table not there yet is nothing
read; any other error (a database locked past its connection's timeout) is raised."""
import json
import os
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple

from . import home

GROUP, FOLDER, FILED = "group", "folder", "filed"
OPENED, REGROUPED = "app_opened", "app_regrouped"
TYPES = (GROUP, FOLDER, FILED, OPENED, REGROUPED)
ALONE = "self:"                 # an actor on its own: its group of one, `self:<its channel>` (groups.py)
APP, PLACED = "app:", "group:"  # folders.py's items: an app's instance, a group placed in another


@dataclass
class Placement:
    groups: Dict[str, Optional[str]] = field(default_factory=dict)
    folders: Dict[int, dict] = field(default_factory=dict)
    placed: Dict[str, Tuple[str, Optional[int]]] = field(default_factory=dict)
    top: int = 0
    apps: Dict[str, str] = field(default_factory=dict)
    changed: Dict[str, float] = field(default_factory=dict)

    def members(self, group: str) -> Set[str]:
        """The channels whose latest `group` record names `group`."""
        return {ch for ch, g in self.groups.items() if g == group}

    def alone(self) -> List[str]:
        """The groups of one of the actors on their own (`self:<channel>`), by name."""
        return sorted({g for g in self.groups.values() if isinstance(g, str) and g.startswith(ALONE)})

    def instances(self, group: str) -> Set[str]:
        """The app instances in `group` now."""
        return {inst for inst, g in self.apps.items() if g == group}


NONE = Placement()
_kept: Dict[tuple, Tuple[tuple, Placement]] = {}    # (database file) -> (what its records were then, what they said)
_lock = threading.Lock()


def _payload(raw) -> Optional[dict]:
    try:
        got = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return None
    return got if isinstance(got, dict) else None


def _seconds(value) -> Optional[float]:
    if value is None:
        return None
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)).timestamp()


def _missing(exc: sqlite3.OperationalError) -> bool:
    """An error that says what is read is not there yet (no table, no column): nothing kept, not a failure."""
    return str(exc).startswith(("no such table", "no such column"))


def now() -> Placement:
    """The home's one database's (module doc); NONE before there is one."""
    if not home.merged() or not os.path.exists(home.home_db()):
        return NONE
    conn = sqlite3.connect(f"file:{home.home_db()}?mode=ro", uri=True, timeout=8)
    try:
        return of(conn)
    finally:
        conn.close()


def of(conn: sqlite3.Connection) -> Placement:
    """The placement `conn`'s database's records say (module doc), read again only if they changed since."""
    path = conn.execute("PRAGMA database_list").fetchone()[2]
    marks = ", ".join("?" * len(TYPES))
    try:
        mark = tuple(conn.execute(f"SELECT max(e.row_id), count(*), total(e.row_id) FROM events e JOIN event_types t "
                                  f"ON t.event_type_id = e.event_type_id WHERE t.name IN ({marks})", TYPES).fetchone())
    except sqlite3.OperationalError as exc:
        if _missing(exc):
            return NONE
        raise
    try:
        st = os.stat(path)
        key = (path, st.st_dev, st.st_ino)
    except OSError:                                # an in-memory or a temporary database: not kept
        key = None
    with _lock:
        got = _kept.get(key) if key else None
    if got and got[0] == mark:
        return got[1]
    placement = _read(conn)
    if key:
        with _lock:
            _kept[key] = (mark, placement)
    return placement


def _read(conn: sqlite3.Connection) -> Placement:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(events)")}
    inst = "e.p_instance" if "p_instance" in cols else "NULL"
    if "p_channel" not in cols:                    # no channel's column yet: nothing placed
        return NONE
    p = Placement()
    marks = ", ".join("?" * len(TYPES))
    for kind, ch, instance, raw, at in conn.execute(
            f"SELECT t.name, e.p_channel, {inst}, e.payload_json, e.inserted_at FROM events e JOIN event_types t "
            f"ON t.event_type_id = e.event_type_id WHERE t.name IN ({marks}) ORDER BY e.row_id", TYPES):
        payload = _payload(raw)
        if payload is None:
            continue
        if kind in (GROUP, FOLDER, FILED):
            when = _seconds(at)
            for name in (payload.get("group"), payload.get("was")):
                if isinstance(name, str) and name and when:
                    p.changed[name] = max(p.changed.get(name, 0.0), when)
        folder = payload.get("folder")
        folder = folder if isinstance(folder, int) else None
        if kind == GROUP and ch is not None:
            p.groups[ch] = payload.get("group")
            p.placed[ch] = (str(payload.get("group") or ""), folder)
        elif kind == FOLDER and ch is None and isinstance(payload.get("id"), int):
            fid = payload["id"]
            p.top = max(p.top, fid)
            if payload.get("gone"):
                p.folders.pop(fid, None)
            else:
                p.folders[fid] = {k: payload.get(k) for k in ("id", "group", "parent", "name", "at", "closed")}
        elif kind == FILED and ch is None and str(payload.get("item") or "").startswith((APP, PLACED)):
            p.placed[payload["item"]] = (str(payload.get("group") or ""), folder)
        elif kind == OPENED and instance:
            made = payload.get("instance")
            if isinstance(made, dict) and made.get("gatherer"):
                p.apps[instance] = str(made["gatherer"])
        elif kind == REGROUPED and instance and instance in p.apps and payload.get("group"):
            p.apps[instance] = str(payload["group"])
    return p
