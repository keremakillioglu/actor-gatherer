"""Each actor's avatar: a small picture of its own beside it in the page's list, so color alone tells
the actors apart. The pictures are the SVGs in ag_dashboard/avatars/<kind>/<name>.svg (drawn by
assets/src/avatars/draw.py, or put there by hand: the README there), each in one hue, which its root
names (`data-hue`), as it does how the character moves while its actor works (`data-motion`: the
Chat view's, page.html's `.buddy`). What each can say before its actor's first message is in a file beside
them, hello.toml (`LINES`), read again whenever it changes. Which actor has which is kept in the dashboard's own database (<home>/dashboard.db,
next to sessions.py's and hiding.py's tables), so every dashboard on this home shows the same. Table
`avatars`, one row per actor given one:

    gatherer, channel   the actor
    avatar              its picture, "<kind>/<name>"
    at                  when it was given (ISO, UTC)
    said                which of its picture's lines it says (`next_said`; NULL, given before there were lines:
                        one fixed by its channel)

An actor is given one the first time the home is read with it (`assign`), the newest actor first (the
ones in view): one in a hue no other open actor of its gatherer has, then one no actor in the home has,
then the least recently given -- never given first, in a fixed shuffled order (`order`), so kinds and
hues mix. An actor whose picture is no longer in the folder is given another in the same way; with no
pictures at all, none is given, and the page draws the actor's harness's mark. Each actor carries its
picture's hue and motion too (`avatar_hue`, `avatar_motion`), for the page to draw it at work, and the line it
says before its first message (`avatar_hello`)."""

import hashlib
import os
import random
import re
import sqlite3
import sys
import threading
import tomllib
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

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
    said     INTEGER,
    PRIMARY KEY (gatherer, channel)
)"""
STYLES = 4                               # the lines a drawn picture says, one of each style (LINES)
LINES = "hello.toml"                     # in DIR: what each says before its actor's first message, by its name

_lock = threading.Lock()
_read: Dict[str, Tuple[float, str, str]] = {}     # path -> (its mtime, its hue, its motion): a picture is read once
_said: Dict[str, Tuple[float, Dict[str, List[str]]]] = {}   # LINES' path -> (its mtime, its lines by name)


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


def lines() -> Dict[str, List[str]]:
    """LINES, {name: its lines}, read again whenever it changed. One that does not read (a slip while it is being
    edited) is as it last read, and says why on stderr; with none, {}."""
    p = os.path.join(DIR, LINES)
    try:
        mtime = os.stat(p).st_mtime
    except OSError:
        return {}
    was = _said.get(p)
    if was and was[0] == mtime:
        return was[1]
    try:
        with open(p, "rb") as fh:
            got = tomllib.load(fh)
        table = {k: [t.strip() for t in v if isinstance(t, str) and t.strip()] for k, v in got.items() if isinstance(v, list)}
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        print(f"ag dashboard: {p} does not read ({e}); its lines as they last read", file=sys.stderr)
        table = was[1] if was else {}
    _said[p] = (mtime, table)
    return table


def hello(name: str) -> List[str]:
    """What the picture `name` ("<kind>/<name>") can say before its actor's first message: LINES' lines under its name,
    or one in every hue ("daruma-red") under its name without its hue ("daruma"); [] for none."""
    table, base = lines(), name.rsplit("/", 1)[-1]
    hue = _read.get(os.path.join(DIR, name + ".svg"), (None, "", ""))[1]
    return table.get(base) or (table.get(base[:-len(hue) - 1], []) if hue and base.endswith("-" + hue) else [])


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


def kept() -> Tuple[Dict[Tuple[str, str], str], Dict[Tuple[str, str], int]]:
    """({(gatherer, channel): its picture}, {(gatherer, channel): which of its lines it says}), read-only: empty when none
    is kept yet."""
    if not os.path.exists(sessions.db_path()):
        return {}, {}
    conn = sqlite3.connect(f"file:{sessions.db_path()}?mode=ro", uri=True, timeout=8)
    try:
        rows = _rows(conn)
        return {(g, c): a for g, c, a, _ in rows}, {(g, c): s for g, c, _, s in rows if s is not None}
    except sqlite3.Error:                # no table yet
        return {}, {}
    finally:
        conn.close()


def stored() -> Dict[Tuple[str, str], str]:
    """{(gatherer, channel): its picture}, read-only: {} when none is kept yet."""
    return kept()[0]


def _rows(conn: sqlite3.Connection) -> List[Tuple[str, str, str, Optional[int]]]:
    """Every row kept, (gatherer, channel, avatar, said), oldest given first: said None in a table from before it."""
    try:
        return list(conn.execute("SELECT gatherer, channel, avatar, said FROM avatars ORDER BY at"))
    except sqlite3.OperationalError:     # a table from before `said`
        return [(g, c, a, None) for g, c, a in conn.execute("SELECT gatherer, channel, avatar FROM avatars ORDER BY at")]


def next_said(said: List[int]) -> int:
    """Which line an actor newly given a picture says, `said` what the actors given one before say (oldest first): at
    random, of the STYLES its round has not said yet -- rounds of STYLES actors, one after another -- so the next actor
    says another and every style comes round in turn; a round's first not the line just said."""
    done = said[len(said) - len(said) % STYLES:]
    return random.choice([s for s in range(STYLES) if s not in done and (done or not said or s != said[-1])])


def says(channel: str, lines: List[str], said: Optional[int]) -> Optional[str]:
    """The line of `lines` an actor says: its `said`'th, or with none (given its picture before there were lines), one
    fixed by its `channel`; None when its picture has none."""
    if not lines:
        return None
    return lines[(int(hashlib.sha1(channel.encode()).hexdigest(), 16) if said is None else said) % len(lines)]


def attach(home: dict, kept: Dict[Tuple[str, str], str], pool: Dict[str, str],
           said: Optional[Dict[Tuple[str, str], int]] = None) -> dict:
    """Set each actor's `avatar` in `home` (data.home()) from `kept`, and its hue, motion and line (from `said`, which
    of its picture's lines each says): None where it has none in `pool` (pictures())."""
    for g in home["gatherers"]:
        for a in g["agents"]:
            got = kept.get((g["name"], a["channel"]))
            a["avatar"] = got if got in pool else None
            a["avatar_hue"] = pool[got] if a["avatar"] else None
            a["avatar_motion"] = motion(got) if a["avatar"] else None
            a["avatar_hello"] = says(a["channel"], hello(got), (said or {}).get((g["name"], a["channel"]))) if a["avatar"] else None
    return home


def assign(home: dict) -> dict:
    """Give each actor of `home` (data.home()) with no picture one, kept, and the line it says (next_said); set every
    actor's `avatar`."""
    pool = pictures()
    has, said = kept()
    if not pool or all(has.get((g["name"], a["channel"])) in pool for g in home["gatherers"] for a in g["agents"]):
        return attach(home, has, pool, said)         # each has its own: nothing to write
    actors = sorted(((g, a) for g in home["gatherers"] for a in g["agents"]),
                    key=lambda ga: ga[1].get("created") or ga[1].get("last") or 0, reverse=True)
    with _lock:
        os.makedirs(os.path.dirname(sessions.db_path()), exist_ok=True)
        conn = sqlite3.connect(sessions.db_path(), timeout=8, isolation_level=None)
        try:
            conn.execute(SCHEMA)
            if "said" not in {r[1] for r in conn.execute("PRAGMA table_info(avatars)")}:   # a table from before it
                try:
                    conn.execute("ALTER TABLE avatars ADD COLUMN said INTEGER")
                except sqlite3.OperationalError:     # another dashboard added it meanwhile
                    pass
            conn.execute("BEGIN IMMEDIATE")          # another dashboard on this home gives none meanwhile
            rows = _rows(conn)
            has = {(g, c): a for g, c, a, _ in rows}
            said = {(g, c): s for g, c, _, s in rows if s is not None}
            told = [s for *_, s in rows if s is not None]
            last = dict(conn.execute("SELECT avatar, max(at) FROM avatars GROUP BY avatar"))
            own = lambda g, a: has.get((g["name"], a["channel"])) if has.get((g["name"], a["channel"])) in pool else None
            held = {own(g, a) for g, a in actors} - {None}
            now, given = datetime.now(timezone.utc), []
            for g, a in actors:
                if own(g, a):
                    continue
                at = (now + timedelta(microseconds=len(given))).isoformat()    # each its own time: the next is newer
                taken = {pool[own(g, b)] for b in g["agents"] if b is not a and b.get("status") != CLOSED and own(g, b)}
                pick = min(pool, key=lambda n: (pool[n] in taken, n in held, last.get(n, ""), order(n)))
                line = next_said(told)
                has[(g["name"], a["channel"])], last[pick], said[(g["name"], a["channel"])] = pick, at, line
                held.add(pick)
                told.append(line)
                given.append((g["name"], a["channel"], pick, at, line))
            conn.executemany("INSERT INTO avatars (gatherer, channel, avatar, at, said) VALUES (?, ?, ?, ?, ?) "
                             "ON CONFLICT (gatherer, channel) DO UPDATE SET avatar = excluded.avatar, at = excluded.at, "
                             "said = excluded.said", given)
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()
    return attach(home, has, pool, said)
