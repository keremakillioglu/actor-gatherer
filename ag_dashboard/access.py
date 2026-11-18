"""ACCESS: which app instances an agent may use, checked at every call (tool_gateway.py's `resolve`, app_host.py's
`call`) -- not by what the agent was given when it started, which is only what it was told then.

Two ways in, as each app's manifest says (app_kit's `access`), and a third for a coordinator agent:

    task     the agent and the instance are in the same task (tasks.py): an item each, of one task
    group    the instance is of the agent's group (an app all of whose agents share, as Notes' one notebook)
    lead     the agent is its group's coordinator agent (tool_gateway.py's `lead`): every instance of its group

Nothing else gives access: an agent attached to an instance outside its task (what `task_links.link` once made when
an agent used an app another task held) is detached when its group is read (task_links.py's `on_load`).

    why(row, instance)          why the session `row` (sessions' table) may use `instance` -- "your task 'Trip plan'",
                                "your group", "you coordinate this group" -- else None
    usable(row, app=None)       the instances it may use now (of `app`), each with why: [(Instance, why)]
    holders(gatherer, app)      the tasks of the group holding an instance of a "task" app: for a refusal to name
    task_label(gatherer, tid)   what a task is called, for an agent to read: its name, else "task <id>"

What an agent was told of changes to these is SETTLED here too (`settle`): the instances each agent of a group may use
through its task, kept per group since last settled; each one gained or lost, or renamed, told to the agent in its
conversation -- a message from "Apps" it reads before its next call -- and kept as an `app_access` record in its
channel. A group's app is never told: every agent of the group may use it, always; nor is an agent that has had no
model call yet (`STARTED`), which is given what it may use as it starts. The first settle of a group after the
dashboard starts only takes note."""

import threading
from typing import Callable, Dict, List, Optional, Tuple

from . import tasks

GROUP, TASK = "group", "task"
LEAD_WHY = "you coordinate this group"
GROUP_WHY = "your group"
STREAM = "Apps"                     # the stream an access change is told in, as the agent reads it
AUTHOR = "ag"

HOST = None                         # the server's AppHost (server.py), as tool_gateway's
LEAD: Optional[Callable[[dict], bool]] = None   # whether a session is its group's coordinator agent (server.py)
#: whether an agent has had a model call (sessions.py's `_has_calls`): one that has not is given what it may use when it
#: starts, and told nothing before -- a message in its channel would make it a conversation before its first
STARTED: Optional[Callable[[str, str], bool]] = None
ROWS: Optional[Callable[[], List[dict]]] = None  # the sessions' table, as sessions.py lists it (server.py)


def channels_of(row: dict) -> Tuple[str, ...]:
    """The channels a session is known by: its own, and the one it was started under (a codex session's)."""
    return tuple(c for c in (row.get("session_id"), row.get("started_as")) if c)


def _lead(row: dict) -> bool:
    if LEAD is not None:
        return bool(LEAD(row))
    from . import tool_gateway                                      # (it imports this module)
    return tool_gateway.lead(row)


def _host():
    """The app host: the server's, else the tool gateway's (one set alone, as tests do)."""
    if HOST is not None:
        return HOST
    from . import tool_gateway
    return tool_gateway.HOST


def _manifest(app: str):
    host = _host()
    h = host.apps.get(app) if host is not None else None
    return h.manifest if h is not None else None


def task_label(gatherer: str, tid: int, known: Optional[dict] = None) -> str:
    """What task `tid` is called: its name, quoted, else "task:<id>", as dashboard_ls names it (`known`:
    tasks.of(gatherer), read already)."""
    got = known if known is not None else tasks.of(gatherer)
    name = next((t["name"] for t in got.get("tasks", []) if t["id"] == tid), "")
    return f"'{name}'" if name else f"task:{tid}"


def your_task(gatherer: str, tid: int, known: Optional[dict] = None) -> str:
    """"your task 'Trip plan'", or "your task (task:3)" for one with no name."""
    label = task_label(gatherer, tid, known)
    return f"your task {label}" if label.startswith("'") else f"your task ({label})"


def _task(tasked: Dict[str, int], channels: Tuple[str, ...]) -> Optional[int]:
    return next((tasked[c] for c in channels if c in tasked), None)


def why(row: dict, instance, known: Optional[dict] = None) -> Optional[str]:
    """Why the session `row` may use `instance` (module doc), else None. `known`: tasks.of(its group), read already."""
    g = row.get("gatherer")
    if not g or instance.gatherer != g:
        return None
    m = _manifest(instance.app)
    if m is None:
        return None
    if _lead(row):
        return LEAD_WHY
    got = known if known is not None else tasks.of(g)
    mine = _task(got["tasked"], channels_of(row))
    if mine is not None and got["tasked"].get(tasks.app_item(instance.id)) == mine:
        return your_task(g, mine, got)
    if m.access == GROUP:
        return GROUP_WHY
    return None


def row_of(gatherer: str, channel: str) -> dict:
    """The session a channel is (its own id, or the one it was started under), else one known only by its channel."""
    rows = ROWS() if ROWS is not None else []
    return next((r for r in rows if channel and channel in (r.get("session_id"), r.get("started_as"))),
                {"gatherer": gatherer, "session_id": channel})


def may_use(instance, caller) -> bool:
    """Whether the agent calling (app_kit's Caller) may use `instance` (app_host.py's `may_use`, at every call)."""
    return bool(caller.channel) and why(row_of(caller.gatherer, caller.channel), instance) is not None


def usable(row: dict, app: Optional[str] = None) -> List[tuple]:
    """The instances the session `row` may use now (of `app`), as they were opened, each with why."""
    host = _host()
    if host is None or not row.get("gatherer"):
        return []
    known = tasks.of(row["gatherer"])
    out = []
    for i in host.instances_of(row["gatherer"], app):
        w = why(row, i, known)
        if w:
            out.append((i, w))
    return out


def holders(gatherer: str, app: str) -> List[str]:
    """The tasks of `gatherer` that hold an instance of `app`, as task_label words them; "on its own" for one in none."""
    host = _host()
    if host is None:
        return []
    known = tasks.of(gatherer)
    out = []
    for i in host.instances_of(gatherer, app):
        tid = known["tasked"].get(tasks.app_item(i.id))
        out.append(f"{shown(i)} in {task_label(gatherer, tid, known)}" if tid is not None else f"{shown(i)} on its own")
    return out


def shown(instance) -> str:
    """An instance as an agent reads it: its app's label, its name (the user's, else its title), and its id."""
    m = _manifest(instance.app)
    label = m.label if m is not None else instance.app
    name = instance.name or instance.title
    return f"{label} '{name}' (id {instance.id})" if name else f"{label} (id {instance.id})"


# ---- what agents were told: settled

_told: Dict[str, Dict[str, Dict[str, tuple]]] = {}   # group -> channel -> instance id -> (app, its name, as shown)
_lock = threading.Lock()


def through_tasks(gatherer: str) -> Dict[str, Dict[str, tuple]]:
    """{channel: {instance id: (app, its name, as shown)}}: what each agent in a task of `gatherer` may use through its
    task -- the instances of "task" apps in it. Its group's apps, which every agent may use anyway, are left out."""
    host = _host()
    if host is None:
        return {}
    known = tasks.of(gatherer)
    by_task: Dict[int, List[str]] = {}
    for item, tid in known["tasked"].items():
        if tasks.app_of(item) is None:
            by_task.setdefault(tid, []).append(item)
    out: Dict[str, Dict[str, tuple]] = {c: {} for cs in by_task.values() for c in cs}
    for i in host.instances_of(gatherer):
        m = _manifest(i.app)
        tid = known["tasked"].get(tasks.app_item(i.id))
        if m is None or m.access == GROUP or tid is None:
            continue
        for c in by_task.get(tid, []):
            out[c][i.id] = (i.app, i.name, shown(i))
    return out


def settle(gatherer: str, tell: Optional[Callable[[str, str, dict], None]] = None) -> List[Tuple[str, str]]:
    """What the agents of `gatherer` may use through their tasks compared with what they were last told (module doc):
    each change told (`tell(channel, text, record)`; none: HOST's `tell_agent`) -> [(channel, text)] told. The first
    settle of a group only takes note."""
    if _host() is None or not gatherer:
        return []
    now = through_tasks(gatherer)            # read first, outside the lock: a group's first read settles it too
    with _lock:
        was = _told.get(gatherer)
        _told[gatherer] = now
    if was is None:
        return []
    known = tasks.of(gatherer)
    told = []
    for c in sorted(set(now) | set(was)):
        before, after = was.get(c, {}), now.get(c, {})
        if before != after and not _started(gatherer, c):
            continue
        tid = known["tasked"].get(c)
        where = your_task(gatherer, tid, known) if tid is not None else "your task"
        for iid in sorted(set(before) | set(after)):
            if iid in after and iid not in before:
                app, _, said = after[iid]
                text = (f"You can now use {said}: it is in {where}. Its tools and instructions: apps_help {app}; call "
                        f"its tools with apps_call (instance {iid}) until your next start lists them by name.")
                record = {"can": True, "why": where}
            elif iid in before and iid not in after:
                app, _, said = before[iid]
                text = f"You can no longer use {said}: it is not in your task now."
                record = {"can": False}
            elif before[iid][1] != after[iid][1]:
                app, _, said = after[iid]
                text = f"{before[iid][2]} is now called: {said}."
                record = {"can": True, "renamed": True}
            else:
                continue
            (tell or _tell)(c, text, {**record, "group": gatherer, "app": app, "instance": iid})
            told.append((c, text))
    return told


def _started(gatherer: str, channel: str) -> bool:
    if STARTED is None:
        from . import sessions
        return sessions._has_calls(gatherer, channel)
    return bool(STARTED(gatherer, channel))


def _tell(channel: str, text: str, record: dict) -> None:
    host = _host()
    if host is not None:
        host.tell_agent(record["group"], channel, text, record)


def forget() -> None:
    """What was told, forgotten (tests)."""
    with _lock:
        _told.clear()
