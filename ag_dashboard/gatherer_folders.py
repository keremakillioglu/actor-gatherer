"""The folders the reader keeps GATHERERS in, above them in the list: only to organise it. Kept in the dashboard's own
database (<home>/dashboard.db, beside folders.py's), so every dashboard on this home shows the same ones. A gatherer in
one is the same gatherer: its actors, what they share, its name, its hiding (hiding.py) are as they were. With none, the
list is as it was without them: every gatherer at its top.

Apart from folders.py's, which keep a gatherer's ACTORS (the gatherer their top): those are a gatherer's own, these the
home's, holding gatherers -- and nothing else: no actor is filed in one, none is started in one, none is counted on one.

Table `gatherer_folders`, one row per folder, kept until it is deleted, empty or not:

    id          its number (never used again)
    parent      the folder it is in; NULL: the list's top
    name        unique among the folders beside it, whatever its case; never holding "/" (folders.py's rule)
    at          when it was made (ISO, UTC)

Table `gatherers_filed`, one row per gatherer in a folder (none: at the list's top):

    gatherer    its name (the reader's title for it, titles.py, is apart: renamed so, it stays where it is)
    folder      the folder's id
    at          when it was put there

A folder deleted, what was in it -- gatherers and folders -- moves up into the one it was in."""

import sqlite3
from datetime import datetime, timezone
from typing import Iterable, Optional

from . import store
from .folders import FolderError, folder_name

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS gatherer_folders (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    parent INTEGER,
    name   TEXT NOT NULL,
    at     TEXT NOT NULL
)""",
    "CREATE UNIQUE INDEX IF NOT EXISTS gatherer_folders_named ON gatherer_folders (ifnull(parent, 0), name COLLATE NOCASE)",
    """CREATE TABLE IF NOT EXISTS gatherers_filed (
    gatherer TEXT PRIMARY KEY,
    folder   INTEGER NOT NULL,
    at       TEXT NOT NULL
)""",
)
store.table("gatherer_folders", *SCHEMA[:2])
store.table("gatherers_filed", SCHEMA[2], merged=store.DROP)    # a group merged into another is gone from the folders


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def none() -> dict:
    return {"folders": [], "filed": {}}


def stored() -> dict:
    """{folders: [{id, parent, name}] (by name, whatever its case), filed: {gatherer: folder id}}, read-only: both empty
    while none is kept."""
    got = none()
    with store.reading() as conn:
        if conn is None or not store.has(conn, "gatherer_folders"):
            return got
        for fid, parent, name in conn.execute("SELECT id, parent, name FROM gatherer_folders ORDER BY lower(name), name"):
            got["folders"].append({"id": fid, "parent": parent, "name": name})
        if store.has(conn, "gatherers_filed"):
            for g, fid in conn.execute("SELECT gatherer, folder FROM gatherers_filed ORDER BY at"):
                got["filed"][g] = fid
    return got


# ---- changes: each in one transaction of its own (BEGIN IMMEDIATE), rolled back if it raises

def _change(do):
    with store.transaction("gatherer_folders", "gatherers_filed") as conn:
        return do(conn)


def _folder(conn: sqlite3.Connection, fid) -> tuple:
    """(id, parent, name) of the folder `fid`; FolderError for none."""
    try:
        fid = int(fid)
    except (TypeError, ValueError):
        raise FolderError(f"no folder {fid!r}") from None
    row = conn.execute("SELECT id, parent, name FROM gatherer_folders WHERE id = ?", (fid,)).fetchone()
    if row is None:
        raise FolderError(f"no folder {fid}")
    return row


def _beside(conn: sqlite3.Connection, parent: Optional[int], name: str, but: Optional[int] = None) -> Optional[str]:
    """The name of a folder in `parent` (None: the top) already named `name`, whatever its case, but `but`."""
    row = conn.execute("SELECT name FROM gatherer_folders WHERE ifnull(parent, 0) = ? AND name = ? COLLATE NOCASE AND id != ?",
                       (parent or 0, name, but or 0)).fetchone()
    return row[0] if row else None


def _free(conn: sqlite3.Connection, parent: Optional[int], name: str, but: Optional[int] = None) -> None:
    other = _beside(conn, parent, name, but)
    if other is not None:
        raise FolderError(f'a folder named "{other}" is already there')


def make(name: str, parent: Optional[int] = None) -> int:
    """A new folder, empty, in `parent` (None: the list's top) -> its id. FolderError for no such parent, or one beside
    it already named so."""
    name = folder_name(name)

    def do(conn):
        if parent is not None:
            _folder(conn, parent)
        _free(conn, parent, name)
        return conn.execute("INSERT INTO gatherer_folders (parent, name, at) VALUES (?, ?, ?)", (parent, name, _now())).lastrowid
    return _change(do)


def rename(fid: int, to: str) -> None:
    """The folder named `to`, what is in it still in it. FolderError for no such folder, or one beside it named so."""
    to = folder_name(to)

    def do(conn):
        _, parent, _ = _folder(conn, fid)
        _free(conn, parent, to, but=int(fid))
        conn.execute("UPDATE gatherer_folders SET name = ? WHERE id = ?", (to, int(fid)))
    _change(do)


def move(fid: int, parent: Optional[int]) -> None:
    """The folder, and all in it, put in `parent` (None: the list's top). FolderError for no such folder, a folder put in
    itself or in one of its own, or one there named as it is."""
    def do(conn):
        _, _, name = _folder(conn, fid)
        if parent is not None:
            up = _folder(conn, parent)[0]
            while up is not None:                       # its own folders, up to the top
                if up == int(fid):
                    raise FolderError(f'"{name}" can\'t go in itself or in one of its own folders')
                up = conn.execute("SELECT parent FROM gatherer_folders WHERE id = ?", (up,)).fetchone()[0]
        _free(conn, parent, name, but=int(fid))
        conn.execute("UPDATE gatherer_folders SET parent = ? WHERE id = ?", (parent, int(fid)))
    _change(do)


def delete(fid: int) -> None:
    """The folder gone, what was in it -- its gatherers, its folders -- moved up into the one it was in. A folder moved up
    next to one of its name keeps its own, with " 2" (" 3", ...) after it, as folders.py's do."""
    def do(conn):
        _, parent, _ = _folder(conn, fid)
        for cid, cname in conn.execute("SELECT id, name FROM gatherer_folders WHERE parent = ?", (int(fid),)).fetchall():
            name, n = cname, 1
            while _beside(conn, parent, name, but=cid) is not None:
                n += 1
                name = f"{cname} {n}"
            conn.execute("UPDATE gatherer_folders SET parent = ?, name = ? WHERE id = ?", (parent, name, cid))
        if parent is None:
            conn.execute("DELETE FROM gatherers_filed WHERE folder = ?", (int(fid),))
        else:
            conn.execute("UPDATE gatherers_filed SET folder = ? WHERE folder = ?", (parent, int(fid)))
        conn.execute("DELETE FROM gatherer_folders WHERE id = ?", (int(fid),))
    _change(do)


def file(gatherers: Iterable[str], folder: Optional[int]) -> None:
    """The gatherers (by name) put in `folder` (None: the list's top). FolderError for none named, or no such folder."""
    names = [g for g in dict.fromkeys(str(g or "").strip() for g in gatherers) if g]
    if not names:
        raise FolderError("which gatherers?")

    def do(conn):
        if folder is None:
            conn.executemany("DELETE FROM gatherers_filed WHERE gatherer = ?", [(g,) for g in names])
            return
        fid, at = _folder(conn, folder)[0], _now()
        conn.executemany("INSERT INTO gatherers_filed (gatherer, folder, at) VALUES (?, ?, ?) "
                         "ON CONFLICT (gatherer) DO UPDATE SET folder = excluded.folder, at = excluded.at",
                         [(g, fid, at) for g in names])
    _change(do)
