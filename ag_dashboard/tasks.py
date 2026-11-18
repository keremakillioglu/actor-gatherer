"""TASKS: what the reader works with at once -- actors and apps alike, its ITEMS -- one row in the list, opened as one
layout (the page's TASKS, 05-agent-list.js and 07-panes.js). An item is an actor, by its channel, or an app's instance,
by "app:<its id>" (`app_item`); each is in one task at most, and one in none is a task of its own, needing no row here.
A task is a LEAF: it holds items, not folders; where it is in the list's tree is where its actors are filed
(folders.py), each actor put in one joining it filed where the task is. Within a task every agent is attached to every
app (task_links.py: joining one attaches, leaving it detaches). Kept in the dashboard's own database
(<home>/dashboard.db, beside folders.py's tables), so every dashboard on this home shows the same ones.

Table `tasks`, one row per task:

    id          its number (never used again)
    gatherer    the gatherer its actors are of
    name        what the list calls it -- "": named by what is in it (the page's: its lead actor's name, else its app's)
    at          when it was made (ISO, UTC)

Table `tasked`, one row per item in a task:

    gatherer, channel   the item: an actor by the channel it was put in as -- its own, or the id the dashboard started
                        it under (a Codex session's from before `ag --channel`, renamed to its thread's); the page finds
                        it by either, as it finds folders.py's `filed` -- or an app's instance, "app:<its id>"
    task                the task's id
    at                  when it was put in it

Table `tasks_grouped`, one row per gatherer whose items sharing an app were made one task, once (`group`): what was
kept before apps were items.

`add` puts items in the task another item is in -- one in none, a task made of them all; `take_out` takes them out. A
task left with one item, or none, is gone: its last item a task of its own again."""

import os
import sqlite3
from typing import Dict, Iterable, List, Optional

from . import folders, sessions

TASK_CHARS = 80                 # the longest name a task takes
APP = "app:"                    # an app's instance, as an item: APP + its id


def app_item(instance_id: str) -> str:
    return APP + str(instance_id)


def app_of(item: str) -> Optional[str]:
    """The instance's id an item is, "app:<id>"; None: an actor's channel."""
    return item[len(APP):] if str(item).startswith(APP) else None

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS tasks (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    gatherer TEXT NOT NULL,
    name     TEXT NOT NULL,
    at       TEXT NOT NULL
)""",
    """CREATE TABLE IF NOT EXISTS tasked (
    gatherer TEXT NOT NULL,
    channel  TEXT NOT NULL,
    task     INTEGER NOT NULL,
    at       TEXT NOT NULL,
    PRIMARY KEY (gatherer, channel)
)""",
    """CREATE TABLE IF NOT EXISTS tasks_grouped (
    gatherer TEXT PRIMARY KEY,
    at       TEXT NOT NULL
)""",
)


class TaskError(ValueError):
    """A task that cannot be made, changed or found as asked: its text says why."""


def task_name(text, none: bool = False) -> str:
    """`text` as a task's name: its spaces made one, trimmed, at most TASK_CHARS long. TaskError for none -- but with
    `none`, "": named by what is in it."""
    name = " ".join(str(text or "").split())[:TASK_CHARS].strip()
    if not name and not none:
        raise TaskError("what is the task called?")
    return name


def _write() -> sqlite3.Connection:
    """The dashboard's database, for a change, this module's tables made the first time."""
    os.makedirs(os.path.dirname(sessions.db_path()), exist_ok=True)
    conn = sqlite3.connect(sessions.db_path(), timeout=8, isolation_level=None)
    try:
        for statement in SCHEMA:
            conn.execute(statement)
    except BaseException:
        conn.close()
        raise
    return conn


def stored() -> Dict[str, dict]:
    """{gatherer: {tasks: [{id, name}] (oldest first), tasked: {channel: task id}}}, of every gatherer with a task: {}
    when there is none yet."""
    if not os.path.exists(sessions.db_path()):
        return {}
    conn = sqlite3.connect(f"file:{sessions.db_path()}?mode=ro", uri=True, timeout=8)
    try:
        if not folders._has(conn, "tasks"):
            return {}
        found: Dict[str, dict] = {}
        for tid, g, name in conn.execute("SELECT id, gatherer, name FROM tasks ORDER BY id"):
            found.setdefault(g, {"tasks": [], "tasked": {}})["tasks"].append({"id": tid, "name": name})
        for g, c, tid in conn.execute("SELECT gatherer, channel, task FROM tasked ORDER BY at"):
            found.setdefault(g, {"tasks": [], "tasked": {}})["tasked"][c] = tid
        return found
    except sqlite3.Error:
        return {}
    finally:
        conn.close()


def of(gatherer: str) -> dict:
    """`stored()` of one gatherer: {tasks, tasked}, both empty for a gatherer with none."""
    return stored().get(gatherer) or {"tasks": [], "tasked": {}}


def _change(gatherer: str, do):
    """`do(conn)` in a transaction of its own (BEGIN IMMEDIATE), rolled back if it raises; then the tasks left with
    fewer than two items gone."""
    if not gatherer:
        raise TaskError("which gatherer?")
    conn = _write()
    try:
        conn.execute("BEGIN IMMEDIATE")
        got = do(conn)
        conn.execute("DELETE FROM tasked WHERE gatherer = ? AND task IN (SELECT task FROM tasked WHERE gatherer = ? "
                     "GROUP BY task HAVING count(*) < 2)", (gatherer, gatherer))
        conn.execute("DELETE FROM tasks WHERE gatherer = ? AND id NOT IN (SELECT task FROM tasked WHERE gatherer = ?)",
                     (gatherer, gatherer))
        conn.execute("COMMIT")
        return got
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def _channels(channels: Iterable[str]) -> List[str]:
    return [c for c in dict.fromkeys(str(c or "").strip() for c in channels) if c]


def add(gatherer: str, to: str, channels: Iterable[str], name: Optional[str] = None) -> int:
    """The items `channels` put in the task the item `to` is in (each out of any other it was in) -> its id. `to` in
    none: a task made of it and them, called `name` (none: named by what is in it). TaskError for no item to add."""
    to, channels = str(to or "").strip(), [c for c in _channels(channels) if c != str(to or "").strip()]
    if not to or not channels:
        raise TaskError("which actors or apps? `to`, one, and `items`, those to put in its task")

    def do(conn):
        row = conn.execute("SELECT task FROM tasked WHERE gatherer = ? AND channel = ?", (gatherer, to)).fetchone()
        at = folders._now()
        if row:
            tid = row[0]
        else:
            tid = conn.execute("INSERT INTO tasks (gatherer, name, at) VALUES (?, ?, ?)",
                               (gatherer, task_name(name, none=True), at)).lastrowid
            channels.insert(0, to)
        conn.executemany("INSERT INTO tasked (gatherer, channel, task, at) VALUES (?, ?, ?, ?) "
                         "ON CONFLICT (gatherer, channel) DO UPDATE SET task = excluded.task, at = excluded.at",
                         [(gatherer, c, tid, at) for c in channels])
        return tid
    return _change(gatherer, do)


def take_out(gatherer: str, channels: Iterable[str]) -> None:
    """The items `channels` out of the task each is in: each a task of its own again (and the task's last one too)."""
    channels = _channels(channels)
    if not channels:
        raise TaskError("which actors or apps?")
    _change(gatherer, lambda conn: conn.executemany("DELETE FROM tasked WHERE gatherer = ? AND channel = ?",
                                                    [(gatherer, c) for c in channels]))


def rename(gatherer: str, tid: int, to: str) -> None:
    """Task `tid` called `to` -- "" (spaces only too): named by what is in it again, as one is that was never named.
    TaskError for no such task."""
    name = task_name(to, none=True)

    def do(conn):
        if not conn.execute("UPDATE tasks SET name = ? WHERE gatherer = ? AND id = ?", (name, gatherer, tid)).rowcount:
            raise TaskError(f"no task {tid} in {gatherer}")
    _change(gatherer, do)


def members(gatherer: str, tid: int) -> List[str]:
    """Task `tid`'s items, as they were put in it, the first put in first."""
    return [c for c, t in of(gatherer)["tasked"].items() if t == tid]


def task_of(gatherer: str, item: str) -> Optional[int]:
    return of(gatherer)["tasked"].get(item)


def grouped(gatherer: str) -> bool:
    """Whether the gatherer's items sharing an app were made one task already (`group`)."""
    if not os.path.exists(sessions.db_path()):
        return False
    conn = sqlite3.connect(f"file:{sessions.db_path()}?mode=ro", uri=True, timeout=8)
    try:
        return folders._has(conn, "tasks_grouped") and conn.execute(
            "SELECT 1 FROM tasks_grouped WHERE gatherer = ?", (gatherer,)).fetchone() is not None
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def group(gatherer: str, links: Iterable[Iterable[str]]) -> List[int]:
    """Once for a gatherer (`tasks_grouped`): the items each of `links` holds -- an app's instance and the agents attached
    to it -- made one task, with those in a task with any of them: the oldest such task, else a new one named by what is
    in it -> the tasks made or grown. What was kept before apps were items: an app is in the task of the actors working
    with it, and actors sharing an app in one. Done already: nothing ([])."""
    def do(conn):
        if conn.execute("SELECT 1 FROM tasks_grouped WHERE gatherer = ?", (gatherer,)).fetchone():
            return []
        conn.execute("INSERT INTO tasks_grouped (gatherer, at) VALUES (?, ?)", (gatherer, folders._now()))
        up: Dict[str, str] = {}

        def top(x):
            while up.get(x, x) != x:
                x = up[x]
            return x

        def join(x, y):
            x, y = top(x), top(y)
            if x != y:
                up[y] = x
        was = dict(conn.execute("SELECT channel, task FROM tasked WHERE gatherer = ?", (gatherer,)))
        by_task: Dict[int, List[str]] = {}
        for c, tid in was.items():
            by_task.setdefault(tid, []).append(c)
        seen = set(was)
        for items in [*by_task.values(), *(_channels(link) for link in links)]:
            seen.update(items)
            for x in items[1:]:
                join(items[0], x)
        groups: Dict[str, List[str]] = {}
        for x in seen:
            groups.setdefault(top(x), []).append(x)
        at, grown = folders._now(), []
        for items in groups.values():
            tids = sorted({was[x] for x in items if x in was})
            if len(items) < 2 or (len(tids) == 1 and all(x in was for x in items)):
                continue                                    # alone, or one task already
            tid = tids[0] if tids else conn.execute("INSERT INTO tasks (gatherer, name, at) VALUES (?, '', ?)",
                                                    (gatherer, at)).lastrowid
            conn.executemany("INSERT INTO tasked (gatherer, channel, task, at) VALUES (?, ?, ?, ?) "
                             "ON CONFLICT (gatherer, channel) DO UPDATE SET task = excluded.task",
                             [(gatherer, x, tid, at) for x in sorted(items)])
            grown.append(tid)
        return grown
    return _change(gatherer, do)
