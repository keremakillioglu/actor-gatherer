"""Moving actors and folders from one group to another. A group is what a gatherer is (the Notes design "Groups:
design"): in the home's one database (home.py's `merged`) a gatherer's actors are the channels whose latest `group`
record names it (data.py's `members`), so an actor changes group by a new record -- with a database per gatherer, an
actor's group is its file, and none moves (GroupError).

    plan(gatherer, to, channels, folder)    what a move would do, for the page to ask first: the actors that change
                                            group -- those named, every one in the folder and the folders in it, and
                                            the others of each one's task, which moves whole -- and how many actors each
                                            of the two groups has before and after
    move(gatherer, to, channels, folder, into)   it done, in one call to ag: a `group` record in each actor's channel
                                            ({group, was, name, was_name, folder}: its id names the channel and the
                                            move, as a read returns an id once, whatever its channel) -- its folder
                                            `into` (one of the group's; none, its top), or the one it was in, inside
                                            the folder moved -- and a `folder` record of the folder and each folder in
                                            it, now the group's (folders.py); then the dashboard's own rows of the
                                            actors moved to the group's name, in one transaction -- the session's, its
                                            saved mark, what was seen of it, its avatar, its task

An app in a task or a folder that moves goes with it, as its actors keep using it (`apps`): one with many instances
(Browser, DocWriter, Editor) -- its `filed` record names the new group, and the host moves it (app_host.py's
`regroup`). An app's own agent (one it started: app_agents.py's `role_of`, its role naming the instance) and that
instance go together, as a task does (`_own`): Paper news's agent and its Paper news. A group's only one of its app
(Notes, Slack, Paper news: one per group) is its group's, and stays -- a move that would take one is refused
(GroupError) -- unless its own agent goes with it: then it goes too, into a group that has none of that app; into one
that has, it is closed, and its agents work with that group's instead (`_folds`: its role names that one from then on,
as the host would open the old one again for it at its next start). An attachment a move would leave across groups --
a moved actor to an app that stays, an actor that stays to an app that moves -- is dropped (`_unhook`), as attaching
across groups is refused.

    split(gatherer, folder)                 a folder dragged outside every group: made a group of its own, named after
                                            it (`ag new`, as "+ New group" makes one), what was in it at its top
    alone(gatherer, channel)                an actor dragged outside every group: on its own, a group of one
                                            (`self:<channel>`) -- it shares with no one, no one with it, and it has no
                                            coordinator agent -- with the apps of its task (none of its actors but it),
                                            and its app's own window if it is an app's agent; `move` brings it back
    start_alone(started, gatherer, cwd, harness)   a new actor on its own from its start (the list's "+" beside
                                            "+ New group"): its session made (sessions.py's `create`, `alone`) and its
                                            `group` record in before its first call, so it never shares
    place(gatherer, to, into)               a group -- an actor on its own's too -- put in group `to`'s folder `into`,
                                            keeping its own group: a group inside that folder, sharing with no one
                                            around it (`to` "": back at the list's top). Its `filed` record (folders.py's
                                            PLACED); what anyone shares is as it was. `places()`: where each one is
    own(gatherer, folder)                   the folder given a group of its own where it is: `split`, then the new group
                                            placed where the folder was, with its parent group's settings
    above(gatherer)                         a group placed in another's folder back in that group: `merge`d there, a
                                            folder of it where it was
    runs_under(group)                       the group ag runs a write of `group`'s under: an actor on its own's, the
                                            group it left (`launch_group`) -- ag keeps a config for the home's groups,
                                            and would make one for a name it does not know

A group placed in a folder that moves goes with it, as an actor in it does: its place names the group the folder is in
now (`_carried`) -- a folder made a group (`split`), the new group's top; a group merged (`merge`), the folder it became.

A watch of the coordinator agent's on a moved actor goes as coordination.py's `check` says. A coordinator agent over a
folder (sessions.py's `over`) goes where its folder goes (`_crews`): moved with it into another group, its session's
group that one from then on -- in no folder there, as it is in none; made the new group's own when its folder is made a
group (`split`). One over a group stays with its group."""

import os
import re
import secrets
import sqlite3
from typing import Dict, Iterable, List, Optional

from app_kit import AppError

from . import actions, data, folders, gatherer_folders, home, merges, sessions, tasks, titles

GROUP = "group"
ALONE = "self:"                 # an actor on its own: the group of one `self:<its channel>` (the policy's ALONE too)
#: The dashboard's tables that name an actor's gatherer beside its channel (sessions apart: by its session_id).
ACTOR_TABLES = ("saved", "seen", "avatars", "tasked")


class GroupError(ValueError):
    """A move the groups cannot take: the page shows its text."""


def _names(gatherer: str) -> str:
    return (titles.stored() or {}).get(gatherer) or gatherer


def _tree(gatherer: str) -> dict:
    return folders.of(gatherer)


def _under(tree: dict, fid: int) -> List[int]:
    """The folder and every folder in it, by id."""
    out, todo = [], [int(fid)]
    while todo:
        f = todo.pop()
        out.append(f)
        todo += [x["id"] for x in tree["folders"] if x.get("parent") == f]
    return out


def _crews(gatherer: str, fids: Iterable[int]) -> List[str]:
    """The coordinator agents of `gatherer` over the folders `fids` (sessions.py's `over`), by their sessions' ids."""
    want = {f"folder:{int(f)}" for f in fids}
    return sorted(r["session_id"] for r in sessions.stored()
                  if r.get("role") == sessions.COORDINATOR and r.get("gatherer") == gatherer and r.get("over") in want)


def actors(gatherer: str, channels: Iterable[str] = (), folder: Optional[int] = None) -> List[str]:
    """The items a move takes: the actors named, those filed in `folder` or a folder in it, the coordinator agents over
    those folders (`_crews`), and every other item of a task one of them is in (a task moves whole) -- apps among them,
    as APP + its id, each one that can move (`apps`)."""
    out = {str(c) for c in channels}
    if folder is not None:
        tree = _tree(gatherer)
        if not any(f["id"] == int(folder) for f in tree["folders"]):
            raise GroupError(f"{gatherer} has no folder {folder}")
        inside = set(_under(tree, int(folder)))
        out |= {c for c, f in tree["filed"].items() if f in inside} | set(_crews(gatherer, inside))
    mine = (tasks.stored() or {}).get(gatherer) or {"tasks": [], "tasked": {}}
    agents = _app_agents(gatherer)
    while True:                                       # each one's task, and an app's own agent with its instance
        joined = {mine["tasked"][c] for c in out if c in mine["tasked"]}
        grown = out | {c for c, t in mine["tasked"].items() if t in joined} | _own(gatherer, out, agents)
        if grown == out:
            break
        out = grown
    apps(gatherer, out)
    return sorted(out)


def _app_agents(gatherer: str) -> Dict[str, List[str]]:
    """The agents of `gatherer` an app started, by the instance their role names: {instance id: [channel]}."""
    from . import app_agents                          # (it imports what imports this module)
    out: Dict[str, List[str]] = {}
    for s in sessions.stored():
        got = app_agents.role_of(s)
        if got is not None and s.get("gatherer") == gatherer:
            out.setdefault(got[1], []).append(s["session_id"])
    return out


def _own(gatherer: str, items: set, agents: Dict[str, List[str]]) -> set:
    """What an app's own agent and its instance bring along (module doc): of each agent among `items`, its instance,
    open in `gatherer` (with no host to say, it all the same: `apps` refuses it then) -- of each instance among them,
    its agents."""
    host = _host()
    here = None if host is None else {i.id for i in host.instances_of(gatherer)}
    out = set()
    for inst, channels in agents.items():
        if folders.APP + inst in items:
            out |= set(channels)
        elif any(c in items for c in channels) and (here is None or inst in here):
            out.add(folders.APP + inst)
    return out


def _host():
    from . import tool_gateway                        # the server's AppHost, its apps' (None: none run here)
    return tool_gateway.HOST


def apps(gatherer: str, items: Iterable[str]) -> list:
    """The app instances among `items` (APP + its id) -> [Instance]. GroupError: one not found, or one that can't move --
    a group's only one of its app (one per group, folder, checkout or repository), which is its group's, unless its own
    agent is among `items` too."""
    items = [str(c) for c in items]
    ids = [c[len(folders.APP):] for c in items if c.startswith(folders.APP)]
    if not ids:
        return []
    host = _host()
    if host is None:
        raise GroupError("apps can only be moved by the dashboard that runs them")
    out, agents = [], _app_agents(gatherer)
    for i in ids:
        try:
            inst = host.instance(gatherer, i)
        except AppError:
            raise GroupError(f"{gatherer} has no app {i}") from None
        if host.hosted(inst.app).manifest.instances != "many" and not set(agents.get(i, ())) & set(items):
            raise GroupError(f"{inst.name or inst.title or inst.app} is the group's only one and stays with the group. "
                             "Take it out of the task or folder first.")
        out.append(inst)
    return out


def _folds(to: str, moved: list) -> dict:
    """Of the instances `moved` (`apps`), those a group has one of at most (its app not "many") that `to` has one of
    already: {moved id: `to`'s one} -- it closed, and its agents that move work with `to`'s one (module doc)."""
    host = _host()
    out = {}
    for inst in moved:
        if host.hosted(inst.app).manifest.instances == "many":
            continue
        there = host.instances_of(to, inst.app)
        if there:
            out[inst.id] = there[0]
    return out


def _close(gatherer: str, inst, moving: List[str]) -> tuple:
    """The instance `inst` of `gatherer` closed, as the group it goes to has its app's one (`_folds`), and out of its
    task -- before the moving actors' rows move -> (the moving actors that used it, its own agents among them)."""
    from . import task_links                          # (it imports what imports this module)
    host = _host()
    gone = set(moving)
    own = [c for c in _app_agents(gatherer).get(inst.id, ()) if c in gone]
    users = sorted({c for c in host.agents_of(inst) if c in gone} | set(own))
    host.close_instance(gatherer, inst.id, by="group")
    task_links.closed(gatherer, inst.id)
    return users, own


def _join(to: str, there, users: List[str], own: List[str]) -> None:
    """The actors `users` of an instance closed for `to`'s own one, `there` (`_close`), attached to it, in its task as
    an agent attached to an app is (task_links.py's `link`) -- once their rows are `to`'s -- and each of its own agents
    `own` given a role naming `there` from now on, as the host would make the one it named again for it at its next
    start (app_host.py's `adopt`)."""
    from . import app_agents, task_links
    if own:
        conn = folders._write()
        try:
            with conn:
                conn.executemany("UPDATE sessions SET role = ? WHERE session_id = ?",
                                 [(app_agents.role(there.app, there.id), c) for c in own])
        finally:
            conn.close()
    for c in users:
        task_links.link(to, there.id, c)
        _host().attach(to, there.id, c, by="group")


def _unhook(gatherer: str, moving: List[str], moved_apps: List[str]) -> None:
    """The attachments a move from `gatherer` leaves across groups dropped (module doc), before the apps move: the
    actors `moving` from the apps that stay, the actors that stay from the apps `moved_apps`."""
    host = _host()
    if host is None:
        return
    gone, going = set(moving), set(moved_apps)
    for inst in host.instances_of(gatherer):
        stays = inst.id not in going
        for c in host.agents_of(inst):
            if (c in gone) == stays:
                host.detach(gatherer, inst.id, c, by="group")


def _members(group: str) -> set:
    conn = data._connect(group)
    if conn is None:
        return set()
    try:
        return data.members(conn, group) or set()
    finally:
        conn.close()


def _sizes(*groups: str) -> Dict[str, int]:
    conn = data._connect(groups[0])
    if conn is None:
        return {g: 0 for g in groups}
    try:
        return {g: len(data.members(conn, g) or ()) for g in groups}
    finally:
        conn.close()


def _check(gatherer: str, to: str) -> None:
    if not home.merged():
        raise GroupError("run `ag home merge` first to move between groups")
    if to == gatherer:
        raise GroupError(f"already in {to}")
    if to not in data.gatherer_names():
        raise GroupError(f"no group {to!r}")


def plan(gatherer: str, to: str, channels: Iterable[str] = (), folder: Optional[int] = None) -> dict:
    """{actors, from, to, folder, before: {group: actors}, after: {group: actors}} -- what `move` would do, nothing done."""
    _check(gatherer, to)
    items = actors(gatherer, channels, folder)
    moving = [c for c in items if not c.startswith(folders.APP)]
    before = _sizes(gatherer, to)
    moved = apps(gatherer, items)
    folds = _folds(to, moved)
    return {"actors": moving, "from": gatherer, "to": to, "folder": folder, "before": before,
            "after": {gatherer: before[gatherer] - len(moving), to: before[to] + len(moving)},
            "apps": [{"id": i.id, "app": i.app, "title": i.name or i.title,
                      **({"joins": {"id": folds[i.id].id, "title": folds[i.id].name or folds[i.id].title}}
                         if i.id in folds else {})} for i in moved]}


def move(gatherer: str, to: str, channels: Iterable[str] = (), folder: Optional[int] = None,
         into: Optional[int] = None, dissolve: bool = False) -> dict:
    """The move done (module doc): {actors, apps, joined, from, to} -- `apps` the instances moved, `joined` those closed
    for `to`'s own one of their app, {id: its id} (`_folds`). GroupError: no such group or folder, a folder of that
    name in the place it would go, or a record ag did not take -- nothing of the dashboard's then changed. `dissolve`:
    the folder itself gone, what was in it at `into` instead (`split`'s)."""
    _check(gatherer, to)
    items = actors(gatherer, channels, folder)
    moving = [c for c in items if not c.startswith(folders.APP)]
    moved = apps(gatherer, items)
    folds = _folds(to, moved)
    moved_apps = [i.id for i in moved if i.id not in folds]
    items = [c for c in items if not (c.startswith(folders.APP) and c[len(folders.APP):] in folds)]   # closed ones: none
    target = _tree(to)
    if into is not None and not any(f["id"] == int(into) for f in target["folders"]):
        raise GroupError(f"{to} has no folder {into}")
    if folder is not None and not dissolve:
        name = next(f["name"] for f in _tree(gatherer)["folders"] if f["id"] == int(folder))
        if any(f.get("parent") == into and f["name"].lower() == name.lower() for f in target["folders"]):
            raise GroupError(f'{to} already has a folder named "{name}" there')
    said = {"group": to, "was": gatherer, "name": _names(to), "was_name": _names(gatherer)}
    tree = _tree(gatherer)
    under = _under(tree, int(folder)) if folder is not None else []
    gone = int(folder) if dissolve and folder is not None else None
    crews = set(_crews(gatherer, under)) if under else set()
    there = {c: None if c in crews else tree["filed"][c] if tree["filed"].get(c) in under and tree["filed"][c] != gone
             else into for c in items}                # in a folder moved: still in it; a coordinator agent in none
    events = [{"type": GROUP, "id": f"{GROUP}:{c}:{secrets.token_hex(6)}", "properties": {"channel": c},
               "payload": {**said, "folder": there[c]}} for c in moving]
    events += [folders._filed_event(to, c, there[c]) for c in items if c.startswith(folders.APP)]   # an app's place
    events += _carried(gatherer, to, {f: (into if f == gone else f) for f in under})
    if is_alone(gatherer):                            # back in a group: its group of one placed nowhere
        events.append(_placed(gatherer, "", None))
    kept = folders._records()[0]
    for fid in under:                                 # the folder at `into`, those in it where they were
        f = kept[fid]
        if fid == gone:
            events.append(folders._folder_event(fid, None))
            continue
        parent = into if fid == int(folder) or f["parent"] == gone else f["parent"]
        events.append(folders._folder_event(fid, (to, parent, f["name"], f["at"], f["closed"])))
    try:
        actions.insert(to, events)                    # ag first: what the policy reads, and where the folders are
    except (RuntimeError, OSError, ValueError) as exc:
        raise GroupError(f"ag couldn't make the move ({exc}). Nothing changed.") from None
    got = _members(to)
    missed = [c for c in moving if c not in got]
    if missed:
        raise GroupError(f"ag didn't move {', '.join(missed)}. Nothing else changed.")
    _unhook(gatherer, moving, [i.id for i in moved])  # one closed for `to`'s: its own let go of at its close
    for i in moved_apps:
        _host().regroup(gatherer, i, to)
    closed = {inst.id: _close(gatherer, inst, moving) for inst in moved if inst.id in folds}
    _rows(gatherer, to, items)
    if gone is not None:                              # its folder made a group: the coordinator agent over it, the group's
        _over([c for c in _crews(to, [gone])], None)
    for i, (users, own) in closed.items():
        _join(to, folds[i], users, own)
    return {"actors": moving, "apps": moved_apps, "joined": {i: there.id for i, there in folds.items()},
            "from": gatherer, "to": to}


def _rows(gatherer: str, to: str, moving: List[str]) -> None:
    """The dashboard's own rows of the moved actors moved to `to`'s name, in one transaction: their folders are the
    records' (folders.py)."""
    if not moving:
        return
    marks = ", ".join("?" * len(moving))
    conn = folders._write()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if folders._has(conn, "sessions"):
            conn.execute(f"UPDATE sessions SET gatherer = ? WHERE gatherer = ? AND session_id IN ({marks})",
                         (to, gatherer, *moving))
        for table in ACTOR_TABLES:
            if folders._has(conn, table):
                conn.execute(f"UPDATE {table} SET gatherer = ? WHERE gatherer = ? AND channel IN ({marks})",
                             (to, gatherer, *moving))
        if folders._has(conn, "tasks"):
            conn.execute(f"UPDATE tasks SET gatherer = ? WHERE id IN (SELECT task FROM tasked WHERE gatherer = ? "
                         f"AND channel IN ({marks}))", (to, to, *moving))
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def _over(channels: List[str], over: Optional[str]) -> None:
    """The coordinator agents `channels` over `over` (sessions.py's; None: their group's) from now on."""
    if not channels:
        return
    conn = folders._write()
    try:
        conn.execute(f"UPDATE sessions SET over = ? WHERE session_id IN ({', '.join('?' * len(channels))})",
                     (over, *channels))
    finally:
        conn.close()


def _group_name(title: str) -> str:
    """A new group's name, from `title`: what ag takes of it (letters, digits, '.', '_', '-'), one no group has."""
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", title).strip("._-")[:60] or "group"
    taken = {n.lower() for n in data.gatherer_names(every=True)}    # a merged one's too: its directory is kept
    name, n = base, 1
    while name.lower() in taken:
        n += 1
        name = f"{base}_{n}"
    return name


def split(gatherer: str, folder: int) -> dict:
    """The folder `folder` of `gatherer` made a group of its own (module doc): a new group named after it -- its exact
    name its title, where ag takes another -- and what was in it, actors and folders, at the new group's top; the folder
    itself gone. -> {group, actors, apps, from}. GroupError: no such folder, a group's only one of an app in it, or the
    move not taken."""
    if not home.merged():
        raise GroupError("run `ag home merge` first to make a group from a folder")
    f = next((x for x in _tree(gatherer)["folders"] if x["id"] == int(folder)), None)
    if f is None:
        raise GroupError(f"{gatherer} has no folder {folder}")
    actors(gatherer, (), folder)                      # an app that stays in it: refused before anything is made
    name = _group_name(f["name"])
    try:
        sessions.new_gatherer(name)
    except sessions.SessionError as exc:
        raise GroupError(str(exc)) from None
    if name != f["name"]:
        titles.give(name, f["name"])
    moved = move(gatherer, name, folder=folder, into=None, dissolve=True)
    return {"group": name, "actors": moved["actors"], "apps": moved["apps"], "from": gatherer}


def make(title: str, under: Optional[int] = None) -> dict:
    """A folder made outside every group -- at the list's top, or in a folder of groups `under` (gatherer_folders.py) --
    made a group of its own (the list's folder button): named after `title`, as `split` names one (`ag new`, its exact
    name its title where ag takes another), and put in `under`. -> {group, title}. GroupError: no name, one with "/", no
    such folder of groups, or ag did not make it."""
    try:
        title = folders.folder_name(title)
    except folders.FolderError as exc:
        raise GroupError(str(exc)) from None
    if under is not None and not any(f["id"] == int(under) for f in gatherer_folders.stored()["folders"]):
        raise GroupError(f"no folder of groups {under}")
    name = _group_name(title)
    try:
        sessions.new_gatherer(name)
    except sessions.SessionError as exc:
        raise GroupError(str(exc)) from None
    if name != title:
        titles.give(name, title)
    if under is not None:
        gatherer_folders.file([name], int(under))
    return {"group": name, "title": title}


def _merging(gatherer: str, to: str, into: Optional[int]) -> tuple:
    """What `merge` of `gatherer` into `to`, at `to`'s folder `into`, takes -> (the folder's name -- the group's title,
    one no folder beside it has -- its actors, by channel, its app instances). GroupError: not a merge (`merge`)."""
    _check(gatherer, to)
    if is_alone(gatherer) or is_alone(to):
        raise GroupError("an actor on its own can only join a group by moving into it")
    target = _tree(to)
    if into is not None and not any(f["id"] == int(into) for f in target["folders"]):
        raise GroupError(f"{to} has no folder {into}")
    base = folders.folder_name(_names(gatherer).replace("/", "-"))
    beside = {f["name"].lower() for f in target["folders"] if f.get("parent") == into}
    name, n = base, 1
    while name.lower() in beside:
        n += 1
        name = f"{base} {n}"
    channels = _members(gatherer) | {r["session_id"] for r in sessions.stored() if r.get("gatherer") == gatherer}
    host = _host()
    return name, sorted(channels), ([] if host is None else host.instances_of(gatherer))


def merge_plan(gatherer: str, to: str, into: Optional[int] = None) -> dict:
    """What `merge` would do, nothing done, for the page to ask first: {from, to, into, folder: the name it would have,
    actors: how many move, before: {group: actors}, apps: [{id, app, title, joins?: `to`'s one it is closed for}]}."""
    name, channels, insts = _merging(gatherer, to, into)
    folds = _folds(to, insts)
    return {"from": gatherer, "to": to, "into": into, "folder": name, "actors": len(channels),
            "before": _sizes(gatherer, to),
            "apps": [{"id": i.id, "app": i.app, "title": i.name or i.title,
                      **({"joins": {"id": folds[i.id].id, "title": folds[i.id].name or folds[i.id].title}}
                         if i.id in folds else {})} for i in insts]}


def merge(gatherer: str, to: str, into: Optional[int] = None) -> dict:
    """The group `gatherer` dropped into the group `to`: made a folder of it, named after it, in `to`'s folder `into`
    (None: its top) -- as a folder dropped outside every group is made a group (`split`). Everything of it goes:

      - its actors, closed ones too, each a `group` record naming `to`, in the new folder -- or in the folder of it
        it was in, its folders going too, under the new one -- all in one call to ag, with the new folder's record;
      - its apps: one with many instances moved (the host's `regroup`); a group's only one of its app moved too, or,
        `to` having one already, closed, its agents working with `to`'s from then on (`_folds`) -- and what the app
        keeps for the group carried into `to`'s (the host's `folded`: its Notes' pages, under a page named after it);
      - the dashboard's own rows of it, `to`'s (`_rows_all`): its sessions -- the coordinator agent over it then over
        the new folder -- what was saved, seen, tasked, its Editor's projects and branches; its hiding and its place
        among the folders of groups dropped;
      - it kept as merged (merges.py): gone from the list, ag's directory for it kept.

    -> {group: `to`, folder: the new folder's id, name, actors, apps, joined, from}. GroupError: not on the home's one
    database, no such group or folder, the same group, an actor on its own on either side, or a record ag did not take
    -- nothing of the dashboard's then changed."""
    name, channels, insts = _merging(gatherer, to, into)
    folds = _folds(to, insts)
    tree = _tree(gatherer)
    kept, _, top = folders._records()
    fid = max([top, *kept]) + 1
    mine = {f["id"] for f in tree["folders"]}
    crews = {r["session_id"] for r in sessions.stored()
             if r.get("role") == sessions.COORDINATOR and r.get("gatherer") == gatherer}

    def place(item: str) -> Optional[int]:            # in a folder of the group: still in it; else in the new one
        if item in crews:
            return None                               # (a coordinator agent is in none: it is over one, or the group)
        f = tree["filed"].get(item)
        return f if f in mine else fid

    said = {"group": to, "was": gatherer, "name": _names(to), "was_name": _names(gatherer)}
    events = [folders._folder_event(fid, (to, into, name, folders._now(), None))]
    events += [{"type": GROUP, "id": f"{GROUP}:{c}:{secrets.token_hex(6)}", "properties": {"channel": c},
                "payload": {**said, "folder": place(c)}} for c in channels]
    for f in tree["folders"]:                         # its folders: under the new one, those in them where they were
        k = kept[f["id"]]
        events.append(folders._folder_event(f["id"], (to, fid if k["parent"] is None else k["parent"], k["name"],
                                                       k["at"], k["closed"])))
    events += [folders._filed_event(to, folders.APP + i.id, place(folders.APP + i.id)) for i in insts if i.id not in folds]
    events += _carried(gatherer, to, {None: fid, **{f: f for f in mine}})   # groups placed in it: where they were
    if gatherer in folders.places():                  # it, placed in a group's folder: a folder there now, nowhere else
        events.append(_placed(gatherer, "", None))
    try:
        actions.insert(to, events)                    # ag first: what the policy reads, and where the folders are
    except (RuntimeError, OSError, ValueError) as exc:
        raise GroupError(f"ag couldn't make the merge ({exc}). Nothing changed.") from None
    missed = [c for c in channels if c not in _members(to)]
    if missed:
        raise GroupError(f"ag didn't move {', '.join(missed)}. Nothing else changed.")
    host = _host()
    moved = [i.id for i in insts if i.id not in folds]
    for i in moved:
        host.regroup(gatherer, i, to)
    closed = {inst.id: _close(gatherer, inst, channels) for inst in insts if inst.id in folds}
    _rows_all(gatherer, to, f"folder:{fid}")
    for i, (users, own) in closed.items():
        _join(to, folds[i], users, own)
    title = _names(gatherer)
    for inst in insts:                                # what each app keeps for the group: carried into `to`'s
        host.folded(gatherer, folds.get(inst.id) or host.instance(to, inst.id), title)
    return {"group": to, "folder": fid, "name": name, "actors": channels, "apps": moved,
            "joined": {i: there.id for i, there in folds.items()}, "from": gatherer}


def _rows_all(gatherer: str, to: str, over: str) -> None:
    """Every row the dashboard keeps of the group `gatherer` made `to`'s, in one transaction (`merge`): the coordinator
    agent over it over `over` (its folder now), what tables name the group by beside an actor or a task, its Editor's
    projects (those `to` has already kept as they are), and it kept as merged -- its hiding and its place among the
    folders of groups dropped."""
    conn = folders._write()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if folders._has(conn, "sessions"):
            conn.execute("UPDATE sessions SET over = ? WHERE gatherer = ? AND role = ? AND ifnull(over, '') = ''",
                         (over, gatherer, sessions.COORDINATOR))
        for table in ("sessions", *ACTOR_TABLES, "tasks", "branches"):
            if folders._has(conn, table):
                conn.execute(f"UPDATE {table} SET gatherer = ? WHERE gatherer = ?", (to, gatherer))
        if folders._has(conn, "projects"):
            conn.execute("INSERT OR IGNORE INTO projects (gatherer, path, remote, added) "
                         "SELECT ?, path, remote, added FROM projects WHERE gatherer = ?", (to, gatherer))
            conn.execute("DELETE FROM projects WHERE gatherer = ?", (gatherer,))
        for table in ("hiding", "gatherers_filed"):
            if folders._has(conn, table):
                conn.execute(f"DELETE FROM {table} WHERE gatherer = ?", (gatherer,))
        merges.add(conn, gatherer, to)
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def _placed(group: str, to: str, folder: Optional[int]) -> dict:
    """The `filed` record of the group `group` placed in group `to`'s folder `folder` ("": at the list's top)."""
    return folders._filed_event(to or "", folders.PLACED + group, folder if to else None)


def _carried(gatherer: str, to: str, where: Dict[Optional[int], Optional[int]]) -> List[dict]:
    """The records of the groups placed in `gatherer`'s folders `where` names (None: its top), placed in `to`'s folder
    `where` maps each to, as the folders they are in move there."""
    return [_placed(g, to, where[p["folder"]]) for g, p in folders.places().items()
            if p["in"] == gatherer and p["folder"] in where and g != to]


def _inside(group: str, outer: str) -> bool:
    """Whether `group` is `outer`, or placed in it, or in a group placed in it, ..."""
    places, seen = folders.places(), set()
    while group and group not in seen:
        if group == outer:
            return True
        seen.add(group)
        group = (places.get(group) or {}).get("in") or ""
    return False


def places() -> Dict[str, dict]:
    """{group: {in, folder}}: each group placed in another group's folder (folders.py's `places`), of those listed."""
    there = set(data.gatherer_names()) | set(data.alone_names())
    return {g: p for g, p in folders.places().items() if g in there and p["in"] in there}


def place(gatherer: str, to: Optional[str], into: Optional[int] = None) -> dict:
    """The group `gatherer` -- an actor on its own's too -- put in group `to`'s folder `into` (None: its top), keeping
    its own group: a group inside that folder, as the list shows it, its actors sharing with each other, no one around
    them. `to` "" or None: back at the list's top. Nothing anyone shares changes: only its `filed` record (module doc).
    A group placed so leaves the folder of groups it was in (gatherer_folders.py). -> {group, in, folder}. GroupError:
    not on the home's one database, no such group or folder, `to` an actor on its own, or `to` inside it."""
    if not home.merged():
        raise GroupError("run `ag home merge` first to put a group inside another group's folder")
    if gatherer not in set(data.gatherer_names()) | set(data.alone_names()):
        raise GroupError(f"no group {gatherer!r}")
    to = str(to or "")
    if to:
        if is_alone(to) or to not in data.gatherer_names():
            raise GroupError(f"no group {to!r} to put it in")
        if _inside(to, gatherer):
            raise GroupError("a group can't go inside itself or a group inside it")
        if into is not None and not any(f["id"] == int(into) for f in _tree(to)["folders"]):
            raise GroupError(f"{to} has no folder {into}")
    try:
        actions.insert(runs_under(gatherer), [_placed(gatherer, to, into)])
    except (RuntimeError, OSError, ValueError) as exc:
        raise GroupError(f"ag couldn't make the change ({exc})") from None
    if to and not is_alone(gatherer) and gatherer in gatherer_folders.stored()["filed"]:
        gatherer_folders.file([gatherer], None)
    return {"group": gatherer, "in": to or None, "folder": into if to else None}


def _settings_from(group: str, made: str) -> None:
    """The new group `made` given `group`'s settings (its gatherer.toml: policy, pollers, options), as `own` makes one
    in it. Left with ag's defaults when that file can't be read or written."""
    try:
        with open(os.path.join(home.gatherer_dir(group), "gatherer.toml"), encoding="utf-8") as fh:
            text = fh.read()
        with open(os.path.join(home.gatherer_dir(made), "gatherer.toml"), "w", encoding="utf-8") as fh:
            fh.write(text.replace(f"The gatherer {group}:", f"The gatherer {made}:", 1))
    except OSError:
        pass


def own(gatherer: str, folder: int) -> dict:
    """The folder `folder` of `gatherer` given a group of its own, where it is (the list's folder menu, `ag groups folder
    ... own`): `split` -- a new group named after it, its actors and folders in it, the rest of their tasks with them --
    then that group placed where the folder was (`place`), and given `gatherer`'s settings. -> split's, with {in,
    folder}: where it is. GroupError: as `split`'s."""
    f = next((x for x in _tree(gatherer)["folders"] if x["id"] == int(folder)), None) if home.merged() else None
    parent = f["parent"] if f else None
    made = split(gatherer, folder)
    _settings_from(gatherer, made["group"])
    place(made["group"], gatherer, parent)
    return {**made, "in": gatherer, "folder": parent}


def above(gatherer: str) -> dict:
    """The group `gatherer`, placed in a folder of another group, made part of that group again (its folder's menu,
    `ag groups folder ... parent`): merged into it (`merge`), a folder of it where it was. -> merge's. GroupError: placed
    nowhere, an actor on its own (it joins by a move), or as `merge`'s."""
    p = places().get(gatherer)
    if is_alone(gatherer):
        raise GroupError("move an actor on its own into its folder's group instead")
    if p is None:
        raise GroupError(f"{_names(gatherer)} isn't in another group's folder, so there is no group above it")
    return merge(gatherer, p["in"], p["folder"])


def is_alone(group: str) -> bool:
    """Whether `group` is an actor's on its own (`alone`): a group of one, no group of the home's."""
    return str(group or "").startswith(ALONE)


def alone(gatherer: str, channel: str, here: bool = False) -> dict:
    """The actor `channel` of `gatherer` taken out of every group (module doc), in one call to ag: its `group` record,
    {group: self:<channel>, was, name: "", was_name, folder: none}, and a `filed` record of each app that goes with it --
    its task's, and its app's own window (`actors`) -- at that group's top; then the apps moved there (the host's
    `regroup`), and the dashboard's own rows of them under that name. Its group of one placed (`place`) where it was --
    `here`: in its folder of `gatherer`, on its own there -- else at the list's top. -> {group, actors, apps, from, in,
    folder}. GroupError: not on
    the home's one database, no such actor, the coordinator agent (it stays with its group), one working in a task
    with other actors (a task moves whole: out of it first), or an app of its task that can't move (`apps`)."""
    if not home.merged():
        raise GroupError("run `ag home merge` first to have an actor on its own")
    channel = str(channel or "").strip()
    if is_alone(gatherer):
        raise GroupError("it is on its own already")
    if channel not in _members(gatherer):
        raise GroupError(f"{gatherer} has no actor {channel}")
    if any(r.get("session_id") == channel and r.get("role") == sessions.COORDINATOR for r in sessions.stored()):
        raise GroupError("the coordinator agent stays with its group")
    items = actors(gatherer, [channel])
    if [c for c in items if not c.startswith(folders.APP)] != [channel]:
        raise GroupError("it's in a task with others. Take it out of the task first.")
    moved = [i.id for i in apps(gatherer, items)]
    to = ALONE + channel
    event = {"type": GROUP, "id": f"{GROUP}:{channel}:{secrets.token_hex(6)}", "properties": {"channel": channel},
             "payload": {"group": to, "was": gatherer, "name": "", "was_name": _names(gatherer), "folder": None}}
    spot = _tree(gatherer)["filed"].get(channel) if here else None
    try:                                              # ag runs it under a group of the home's: the one it leaves
        actions.insert(gatherer, [event, *(folders._filed_event(to, folders.APP + i, None) for i in moved),
                                  _placed(to, gatherer if here else "", spot)])
    except (RuntimeError, OSError, ValueError) as exc:
        raise GroupError(f"ag couldn't make the change ({exc}). Nothing changed.") from None
    if channel not in _members(to):
        raise GroupError(f"ag didn't take it out of {gatherer}. Nothing else changed.")
    _unhook(gatherer, [channel], moved)               # the apps it used that stay: their group's, not its own
    for i in moved:
        _host().regroup(gatherer, i, to)
    _rows(gatherer, to, items)
    return {"group": to, "actors": [channel], "apps": moved, "from": gatherer, "in": gatherer if here else None,
            "folder": spot}


def start_alone(started, gatherer: str, cwd: str, harness: str, permission_mode: str = "auto",
                model: Optional[str] = None) -> dict:
    """A new actor on its own from its start: a session of `harness` in `cwd` (`started`'s `create`), listed as its group
    of one and run under `gatherer`, a group of the home's -- ag runs every session in one (`launch_group`) -- with its
    `group` record, {group: self:<channel>, under: gatherer, name: "", folder: none}, put in before its first call as the
    conversation's first record -- ag writes one of its own only when it has none (ag_harness's `grouped`), and none
    with an insert that brings one -- so even its first call is built with its own context alone. No `was`: it came from no group, so it is never told it left one (the policy's
    `group_changes`). Any harness: one that picks its session's id at its first call (codex's thread, agy's
    conversation) is kept under the session's id all the same (`ag --channel`), so its channel takes the record before
    then. -> the session. GroupError: not on the home's one database, no such group, or ag did not take the record (the
    session forgotten)."""
    if not home.merged():
        raise GroupError("run `ag home merge` first to have an actor on its own")
    if is_alone(gatherer) or gatherer not in data.gatherer_names():
        raise GroupError(f"no group {gatherer!r} to run it under")
    s = started.create(gatherer, cwd, permission_mode, harness, model, alone=True)
    channel = s["session_id"]
    event = {"type": GROUP, "id": f"{GROUP}:{channel}:{secrets.token_hex(6)}", "properties": {"channel": channel},
             "payload": {"group": ALONE + channel, "under": gatherer, "name": "", "folder": None}}
    try:
        actions.insert(gatherer, [event])
    except (RuntimeError, OSError, ValueError) as exc:
        started.discard(channel)
        raise GroupError(f"ag couldn't record it ({exc}). Nothing was started.") from None
    return s


def runs_under(group: str) -> str:
    """The group ag runs a write of `group`'s under (`ag home insert`, module doc): `group` -- or, for an actor on its
    own, the group it left (`launch_group`)."""
    return launch_group(group[len(ALONE):], group) if is_alone(group) else group


def launch_group(channel: str, group: str) -> str:
    """The group a session's process starts under (`ag --gatherer`, sessions.py): its own -- or, for an actor on its
    own, the group it left, as its latest `group` record says (`was`; one started on its own: the one it was started
    under, `under`): ag runs a session in a group of the home, and what the actor shares is its record's, no one's.
    Else the home's first group."""
    if not is_alone(group):
        return group
    path = home.home_db()
    if os.path.exists(path):
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=8)
        try:
            row = conn.execute("SELECT e.payload_json FROM events e JOIN event_types t ON t.event_type_id = e.event_type_id "
                               "WHERE t.name = ? AND ifnull(e.p_channel, '') = ? ORDER BY e.row_id DESC LIMIT 1",
                               (GROUP, channel)).fetchone()
        except sqlite3.Error:
            row = None
        finally:
            conn.close()
        p = (folders._payload(row[0]) or {}) if row else {}
        was = p.get("was") or p.get("under")
        if was and not is_alone(str(was)):
            gone = merges.stored()
            seen = set()
            while was in gone and was not in seen:     # merged into another since: that one
                seen.add(was)
                was = gone[was]
            return str(was)
    names = data.gatherer_names()
    return names[0] if names else group
