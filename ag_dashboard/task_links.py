"""TASK LINKS: attachment follows a task's membership (tasks.py). Within a task every agent is attached to every app --
given its tools, told what the reader does in it (app_host.py's `attach`) -- so an item joining a task attaches it to
the task's others, and one leaving it detaches it from them. Each change of the tasks goes through here (`change`),
which attaches and detaches what the change asks, and has the page told (RING).

What else puts an app and an agent together, here too:

    link(g, instance, channel, move)   an agent to be attached to an app's instance: the app, in no task, put in the
                                       agent's -- a task of the two, the agent in none -- else the agent, in none, put
                                       in the app's; both in tasks already, the agent moved to the app's only when
                                       `move` (the reader's own attaching, from the app's panel), else nothing: an
                                       agent is attached only to the apps of its task (access.py) -> whether the two
                                       are in one task now, attached. Its task changed first, so whoever hears of the
                                       attaching finds it there
    unlink(g, instance, channel)       an agent detached from an app by the reader: in its task, taken out of it (and so
                                       detached from every app of it), else only detached
    closed(g, instance)                an app's instance closed: out of its task
    on_load(g)                         the host's records of a gatherer read (app_host.py's `loaded_then`): a gatherer
                                       agent's attachments dropped (kept before it was attached to none); once, the
                                       items sharing an app made one task (tasks.py's `group`), what was kept before
                                       apps were items; and every attachment of an agent to an app outside its task
                                       dropped -- what `link` once made of an agent using an app another task held --
                                       the agent told, when it could use it only so (access.py)

Each change of the tasks has what the agents may use through them settled after (access.py's `settle`): an agent
gaining or losing an app's instance is told.

An instance of an app every agent of its group may use (its manifest's `access = "group"`: access.py) is in no task
either (`taskable`): a task would mean nothing for it. One found in a task -- put there before this rule -- is taken out
of it as its group is read (`on_load`).

A gatherer's own agent (sessions.py's COORDINATOR) is in no task, and attached to no app (`attachable`, the host's
check): it reaches every app without (tool_gateway.py)."""

from typing import Callable, Dict, List, Optional, Tuple

from . import access, sessions, tasks, tool_gateway
from app_kit import AppError

RING: Optional[Callable] = None         # the server's hub.ring: the page told the tasks changed (server.py)
SESSIONS = None                         # the server's sessions.Sessions: who is a gatherer agent (server.py)


def _host():
    return tool_gateway.HOST


def _ring(gatherer: str) -> None:
    if RING is not None:
        RING(None, what="list")


def coordinator(channel: str) -> bool:
    """Whether `channel` is a gatherer's own agent's (none known here: no)."""
    if SESSIONS is None:
        return False
    return any(r.get("role") == sessions.COORDINATOR for r in SESSIONS.list()
               if channel in (r.get("session_id"), r.get("started_as")))


def attachable(gatherer: str, channel: str) -> bool:
    """Whether the agent `channel` may be attached to an app (app_host.py's `attachable`): any but a gatherer's own."""
    return not coordinator(channel)


def sync(gatherer: str, before: Dict[str, int], after: Dict[str, int]) -> Dict[str, List[str]]:
    """The attachments made to follow the change from `before` to `after` ({item: task id}): each agent and app now in
    one task attached, each that were in one and are no longer detached -> {channel: [instance ids attached]}. Those
    whose task did not change are left as they are. No apps hosted: nothing."""
    host = _host()
    if host is None:
        return {}
    changed = {x for x in set(before) | set(after) if before.get(x) != after.get(x)}
    near = set(changed)
    for x in changed:
        for m in (before, after):
            if m.get(x) is not None:
                near.update(y for y, t in m.items() if t == m[x])
    attached: Dict[str, List[str]] = {}
    for c in sorted(y for y in near if tasks.app_of(y) is None):
        for a in sorted(y for y in near if tasks.app_of(y) is not None):
            if c not in changed and a not in changed:
                continue
            now = after.get(c) is not None and after.get(c) == after.get(a)
            was = before.get(c) is not None and before.get(c) == before.get(a)
            iid = tasks.app_of(a)
            try:
                if now and not was:
                    host.attach(gatherer, iid, c, by="task")
                    attached.setdefault(c, []).append(iid)
                elif was and not now:
                    host.detach(gatherer, iid, c, by="task")
            except AppError:                                    # its instance closed meanwhile: nothing to attach
                continue
    return attached


def change(gatherer: str, do: Callable[[], object]) -> Tuple[object, Dict[str, List[str]]]:
    """`do()`, a change of the gatherer's tasks (tasks.py), the attachments made to follow it (`sync`), the page told ->
    (what `do` returned, the attachments made)."""
    host = _host()
    if host is not None:
        host.instances_of(gatherer)                     # its records read first: what its agents may use, noted
    before = dict(tasks.of(gatherer)["tasked"])
    got = do()
    attached = sync(gatherer, before, dict(tasks.of(gatherer)["tasked"]))
    _ring(gatherer)
    access.settle(gatherer)
    return got, attached


def taskable(gatherer: str, item: str) -> bool:
    """Whether `item` may be put in a task: an actor that is not a gatherer's own agent, or an instance of an app whose
    manifest says `access = "task"` -- not one every agent of its group may use (module doc). An instance this host
    doesn't know, or of an app it can't find: as a task app's."""
    iid = tasks.app_of(item)
    if iid is None:
        return not coordinator(item)
    host = _host()
    if host is None:
        return True
    with host.lock:
        inst = host.instances.get(iid)
        hosted = host.apps.get(inst.app) if inst is not None else None
    return hosted is None or hosted.manifest.access != access.GROUP


def untaskable(gatherer: str, items) -> List[str]:
    """Of `items`, those that may not be put in a task (`taskable`)."""
    return [str(x) for x in items if not taskable(gatherer, str(x))]


def link(gatherer: str, instance: str, channel: str, move: bool = False) -> bool:
    """An agent to be attached to an app's instance (module doc) -> whether they are in one task now, attached. An app
    every agent of the group may use: never (it is in no task), whoever asks."""
    if not channel or coordinator(channel) or not taskable(gatherer, tasks.app_item(instance)):
        return False
    item = tasks.app_item(instance)
    has = tasks.of(gatherer)["tasked"]
    mine, its = _task_of(has, channel), has.get(item)
    if its is not None and mine == its:
        host = _host()
        if host is not None:
            host.attach(gatherer, instance, channel, by="task")
        return True
    if its is None:
        change(gatherer, lambda: tasks.add(gatherer, channel, [item]))
    elif mine is None or move:
        change(gatherer, lambda: tasks.add(gatherer, item, [channel]))
    else:
        return False
    return True


def _aliases(channel: str) -> Tuple[str, ...]:
    """A channel and the other its session is known by (its own id, the one it was started under)."""
    rows = SESSIONS.list() if SESSIONS is not None else []
    row = next((r for r in rows if channel in (r.get("session_id"), r.get("started_as"))), None)
    return access.channels_of(row) if row is not None else (channel,)


def _task_of(has: Dict[str, int], channel: str) -> Optional[int]:
    return next((has[c] for c in _aliases(channel) if c in has), None)


def unlink(gatherer: str, instance: str, channel: str) -> None:
    """An agent detached from an app by the reader (module doc)."""
    has = tasks.of(gatherer)["tasked"]
    tid = has.get(channel)
    if tid is not None and has.get(tasks.app_item(instance)) == tid:
        change(gatherer, lambda: tasks.take_out(gatherer, [channel]))
        return
    host = _host()
    if host is not None:
        host.detach(gatherer, instance, channel)


def closed(gatherer: str, instance: str) -> None:
    """An app's instance closed: out of its task (its agents detached already, by the host)."""
    item = tasks.app_item(instance)
    if tasks.task_of(gatherer, item) is not None:
        tasks.take_out(gatherer, [item])
        _ring(gatherer)


def on_load(gatherer: str) -> None:
    """A gatherer's records read: its own agent's attachments dropped; once, the items sharing an app made one task;
    every attachment outside a task dropped (module doc)."""
    host = _host()
    if host is None:
        return
    with host.lock:
        lead = [(i, c) for i, inst in host.instances.items() if inst.gatherer == gatherer
                for c in sorted(host.attached.get(i, ())) if coordinator(c)]
    for i, c in lead:
        try:
            host.detach(gatherer, i, c, by="dashboard")
        except AppError:
            continue
    if not tasks.grouped(gatherer):
        with host.lock:
            held = [(i, sorted(host.attached.get(i, ()))) for i, inst in host.instances.items()
                    if inst.gatherer == gatherer]
        links = [[tasks.app_item(i), *(c for c in cs if not coordinator(c))] for i, cs in held
                 if taskable(gatherer, tasks.app_item(i))]     # a group's app ties no one together
        change(gatherer, lambda: tasks.group(gatherer, links))
    loose = untaskable(gatherer, [x for x in tasks.of(gatherer)["tasked"] if tasks.app_of(x) is not None])
    if loose:                                           # a group's app, in a task from before the rule: out of it
        change(gatherer, lambda: tasks.take_out(gatherer, loose))
    strays(gatherer)
    access.settle(gatherer)                             # what its agents may use, noted: changes after are told


def strays(gatherer: str) -> List[Tuple[str, str]]:
    """Each attachment of an agent to an app's instance outside its task dropped (module doc); the agent told, where it
    could use the instance only so -> [(instance id, channel)] dropped."""
    host = _host()
    if host is None:
        return []
    has = tasks.of(gatherer)["tasked"]
    with host.lock:
        held = [(i, inst, sorted(host.attached.get(i, ()))) for i, inst in host.instances.items()
                if inst.gatherer == gatherer]
    dropped = []
    for iid, inst, cs in held:
        its = has.get(tasks.app_item(iid))
        for c in cs:
            if its is not None and _task_of(has, c) == its:
                continue
            try:
                host.detach(gatherer, iid, c, by="access")
            except AppError:
                continue
            dropped.append((iid, c))
            if access.why(access.row_of(gatherer, c), inst) is None and access._started(gatherer, c):
                host.tell_agent(gatherer, c, f"You can no longer use {access.shown(inst)}: it is not in your task.",
                                {"can": False, "group": gatherer, "app": inst.app, "instance": iid})
    return dropped
