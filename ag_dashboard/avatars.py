"""Each actor's avatar: a small picture of its own beside it in the page's list, so color alone tells
the actors apart. The pictures are the SVGs in ag_dashboard/avatars/<kind>/<name>.svg (drawn by
assets/src/avatars/draw.py, or put there by hand: the README there), each in one hue, which its root
names (`data-hue`), as it does how the character moves while its actor works (`data-motion`: the
Chat view's, page.html's `.buddy`). Which actor has which is kept in the dashboard's own database (<home>/dashboard.db,
next to sessions.py's and hiding.py's tables), so every dashboard on this home shows the same. Table
`avatars`, one row per actor given one:

    gatherer, channel   the actor
    avatar              its picture, "<kind>/<name>"
    at                  when it was given (ISO, UTC)

An actor is given one the first time the home is read with it (`assign`), the newest actor first (the
ones in view): one in a hue no other open actor of its gatherer has, then one no actor in the home has,
then the least recently given -- never given first, in a fixed shuffled order (`order`), so kinds and
hues mix. An actor whose picture is no longer in the folder is given another in the same way; with no
pictures at all, none is given, and the page draws the actor's harness's mark. Each actor carries its
picture's hue and motion too (`avatar_hue`, `avatar_motion`), for the page to draw it at work."""

import hashlib
import os
import re
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple

from . import sessions

DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "avatars")
CLOSED = "closed"                        # data.CLOSED: an actor whose hue another may take
NAME = re.compile(r"^[a-z0-9_-]+/[a-z0-9_-]+$")
HUE = re.compile(rb'data-hue="([^"]+)"')
MOTION = re.compile(rb'data-motion="([^"]*)"')
CIRCLE = re.compile(rb'<circle cx="32" cy="32" r="32"[^>]*/>')   # the circle of its hue a picture is drawn on (the README)
SCHEMA = """CREATE TABLE IF NOT EXISTS avatars (
    gatherer TEXT NOT NULL,
    channel  TEXT NOT NULL,
    avatar   TEXT NOT NULL,
    at       TEXT NOT NULL,
    PRIMARY KEY (gatherer, channel)
)"""

_lock = threading.Lock()
_read: Dict[str, Tuple[float, str, str]] = {}     # path -> (its mtime, its hue, its motion): a picture is read once


def pictures() -> Dict[str, str]:
    """{"<kind>/<name>": its hue}, every picture in DIR. One whose root names no hue is a hue of its own."""
    found = {}
    for kind in sorted(os.listdir(DIR)) if os.path.isdir(DIR) else []:
        folder = os.path.join(DIR, kind)
        if not os.path.isdir(folder):
            continue
        for entry in sorted(os.scandir(folder), key=lambda e: e.name):
            name = f"{kind}/{entry.name[:-4]}"
            if not entry.name.endswith(".svg") or not NAME.match(name):
                continue
            mtime = entry.stat().st_mtime
            if _read.get(entry.path, (None,))[0] != mtime:
                with open(entry.path, "rb") as fh:
                    head = fh.read(4096)
                hue, motion = HUE.search(head), MOTION.search(head)
                _read[entry.path] = (mtime, hue.group(1).decode() if hue else name, motion.group(1).decode() if motion else "")
            found[name] = _read[entry.path][1]
    return found


def motion(name: str) -> str:
    """How the picture `name` moves while its actor works, as its root names it ("swim bubbles"): "" for
    none, or a picture pictures() has not read."""
    return _read.get(os.path.join(DIR, name + ".svg"), (None, "", ""))[2]


def bare(svg: bytes) -> bytes:
    """The picture `svg` without the circle it is drawn on: its character alone, to move on the page."""
    return CIRCLE.sub(b"", svg, count=1)


def path(name: str) -> Optional[str]:
    """The file of the picture `name` ("<kind>/<name>"), or None: no such picture."""
    if not NAME.match(name or ""):
        return None
    p = os.path.join(DIR, name + ".svg")
    return p if os.path.isfile(p) else None


def order(name: str) -> str:
    """Where a picture never given comes: a fixed shuffle, the same on every dashboard."""
    return hashlib.sha1(name.encode()).hexdigest()


def stored() -> Dict[Tuple[str, str], str]:
    """{(gatherer, channel): its picture}, read-only: {} when none is kept yet."""
    if not os.path.exists(sessions.db_path()):
        return {}
    conn = sqlite3.connect(f"file:{sessions.db_path()}?mode=ro", uri=True, timeout=8)
    try:
        return {(g, c): a for g, c, a in conn.execute("SELECT gatherer, channel, avatar FROM avatars")}
    except sqlite3.Error:                # no table yet
        return {}
    finally:
        conn.close()


def attach(home: dict, kept: Dict[Tuple[str, str], str], pool: Dict[str, str]) -> dict:
    """Set each actor's `avatar` in `home` (data.home()) from `kept`, and its hue and motion: None where it
    has none in `pool` (pictures())."""
    for g in home["gatherers"]:
        for a in g["agents"]:
            got = kept.get((g["name"], a["channel"]))
            a["avatar"] = got if got in pool else None
            a["avatar_hue"] = pool[got] if a["avatar"] else None
            a["avatar_motion"] = motion(got) if a["avatar"] else None
    return home


def assign(home: dict) -> dict:
    """Give each actor of `home` (data.home()) with no picture one, kept; set every actor's `avatar`."""
    pool = pictures()
    kept = stored()
    if not pool or all(kept.get((g["name"], a["channel"])) in pool for g in home["gatherers"] for a in g["agents"]):
        return attach(home, kept, pool)              # each has its own: nothing to write
    actors = sorted(((g, a) for g in home["gatherers"] for a in g["agents"]),
                    key=lambda ga: ga[1].get("created") or ga[1].get("last") or 0, reverse=True)
    with _lock:
        os.makedirs(os.path.dirname(sessions.db_path()), exist_ok=True)
        conn = sqlite3.connect(sessions.db_path(), timeout=8, isolation_level=None)
        try:
            conn.execute(SCHEMA)
            conn.execute("BEGIN IMMEDIATE")          # another dashboard on this home gives none meanwhile
            kept = {(g, c): a for g, c, a in conn.execute("SELECT gatherer, channel, avatar FROM avatars")}
            last = dict(conn.execute("SELECT avatar, max(at) FROM avatars GROUP BY avatar"))
            own = lambda g, a: kept.get((g["name"], a["channel"])) if kept.get((g["name"], a["channel"])) in pool else None
            held = {own(g, a) for g, a in actors} - {None}
            now, given = datetime.now(timezone.utc), []
            for g, a in actors:
                if own(g, a):
                    continue
                at = (now + timedelta(microseconds=len(given))).isoformat()    # each its own time: the next is newer
                taken = {pool[own(g, b)] for b in g["agents"] if b is not a and b.get("status") != CLOSED and own(g, b)}
                pick = min(pool, key=lambda n: (pool[n] in taken, n in held, last.get(n, ""), order(n)))
                kept[(g["name"], a["channel"])], last[pick] = pick, at
                held.add(pick)
                given.append((g["name"], a["channel"], pick, at))
            conn.executemany("INSERT INTO avatars (gatherer, channel, avatar, at) VALUES (?, ?, ?, ?) "
                             "ON CONFLICT (gatherer, channel) DO UPDATE SET avatar = excluded.avatar, at = excluded.at",
                             given)
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()
    return attach(home, kept, pool)
