"""What `ag groups` asks of the dashboard (POST /api/groups/manage, ag/cli/groups.py): the home's groups read, and
changed by name, with the rules of the list's own drags and switches (groups.py, the Notes design "Groups: folders,
defaults and Manage groups"). A folder takes its parent's group or has its own; an actor has its folder's group or is
on its own. Each change is said first, in words -- who starts and stops sharing context with whom -- then done, unless
`dry_run`: then only said.

    {op: "list"}                             every group: where it is, how many actors it has, the groups and the
                                             actors on their own inside its folders; then those on their own at the top
    {op: "show", group}                      one group: where it is, its folders, its actors, what is inside it
    {op: "folder", path, to: own|parent}     the folder `path` given a group of its own where it is (groups.py's `own`),
                                             or the group `path` names -- inside another's folder -- made part of that
                                             group again (`above`)
    {op: "actor", actor, to: alone|folder}   the actor on its own, staying in its folder (`alone`'s `here`), or back
                                             in its folder's group (`move`)
    {op: "merge", group, into, folder?, keep?}   the group dropped into `into`'s folder `folder` (a path in it):
                                             made a folder there (`merge`), or, `keep`, a group inside it (`place`)
    {op: "rename", group, title}             the group's title (titles.py): no one's context changes

A PATH names a group by its name or title, then folders of it by name, joined by "/" (`making_ag/Work/Figures`): a
name that is no folder there may be a group placed in that folder, whose folders the rest of the path names. An ACTOR is
named by its id (or its first characters, four at least) or its name. -> {said: [lines], done, ...}; GroupError (said
as the error) for a name not found, or a change the rules refuse."""

from typing import Dict, List, Optional, Tuple

from . import data, folders, groups, titles
from .groups import GroupError

OWN, PARENT, ALONE, FOLDER = "own", "parent", "alone", "folder"


def _title(name: str) -> str:
    return "on its own" if groups.is_alone(name) else (titles.stored() or {}).get(name) or name


def _actor_title(a: dict) -> str:
    named = a.get("name")
    text = named.get("text") if isinstance(named, dict) else named
    first = str(a.get("last_user_message") or "").strip().splitlines()
    return str(text or (first[0][:60] if first else "") or "")


def _who(a: dict) -> str:
    title = _actor_title(a)
    return a["channel"][:8] + (f' "{title}"' if title else "")


def _plural(n: int, one: str) -> str:
    return f"{n} {one}" + ("" if n == 1 else "s")


class _Home:
    """The home as the list has it: its groups (by name), their trees, where each placed group is."""

    def __init__(self):
        got = data.home()
        self.groups: Dict[str, dict] = {g["name"]: g for g in got["gatherers"]}
        self.trees = folders.stored()
        self.places = groups.places()

    def tree(self, group: str) -> dict:
        return self.trees.get(group) or {"folders": [], "filed": {}}

    def actors(self, group: str) -> List[dict]:
        return [a for a in (self.groups.get(group) or {}).get("agents") or [] if a.get("role") != "coordinator"]

    def group(self, ref: str) -> str:
        """The group `ref` names, by its name or title (not an actor's on its own)."""
        ref = str(ref or "").strip()
        names = [n for n in self.groups if not groups.is_alone(n)]
        found = [n for n in names if n == ref] or [n for n in names if n.lower() == ref.lower()] or \
            [n for n in names if _title(n).lower() == ref.lower()]
        if not found:
            raise GroupError(f"no group {ref!r}: `ag groups` lists them")
        if len(found) > 1:
            raise GroupError(f"{ref!r} names several groups: {', '.join(found)}")
        return found[0]

    def folder_path(self, group: str, fid: Optional[int]) -> str:
        """`group`'s folder `fid` as a path from the group's title (None: the group alone)."""
        byid = {f["id"]: f for f in self.tree(group)["folders"]}
        parts = []
        while fid is not None and fid in byid:
            parts.append(byid[fid]["name"])
            fid = byid[fid]["parent"]
        return "/".join([_title(group), *reversed(parts)])

    def where(self, group: str) -> str:
        p = self.places.get(group)
        return f"in {self.folder_path(p['in'], p['folder'])}" if p else "at the list's top"

    def placed_in(self, group: str, fid: Optional[int]) -> List[str]:
        return sorted((g for g, p in self.places.items() if p["in"] == group and p["folder"] == fid and g in self.groups),
                      key=lambda g: _title(g).lower())

    def path(self, ref: str) -> Tuple[str, Optional[int], bool]:
        """(group, folder id or None, whether the path's last name was a group) of the path `ref` (module doc)."""
        parts = [p.strip() for p in str(ref or "").split("/") if p.strip()]
        if not parts:
            raise GroupError("which folder? A path: the group's name, then its folders' (`making_ag/Work`)")
        group, fid, is_group = self.group(parts[0]), None, True
        for name in parts[1:]:
            kid = next((f for f in self.tree(group)["folders"] if f["parent"] == fid and f["name"].lower() == name.lower()), None)
            if kid is not None:
                fid, is_group = kid["id"], False
                continue
            inside = [g for g in self.placed_in(group, fid) if not groups.is_alone(g)
                      and name.lower() in (g.lower(), _title(g).lower())]
            if not inside:
                raise GroupError(f"{self.folder_path(group, fid)} has no folder or group {name!r}")
            group, fid, is_group = inside[0], None, True
        return group, fid, is_group

    def actor(self, ref: str) -> Tuple[str, dict]:
        """(its group, the actor) that `ref` names: its id, its first characters, or its name."""
        ref = str(ref or "").strip()
        every = [(g, a) for g in self.groups for a in (self.groups[g].get("agents") or [])]
        found = [x for x in every if x[1]["channel"] == ref] or \
            ([x for x in every if x[1]["channel"].startswith(ref)] if len(ref) >= 4 else []) or \
            [x for x in every if ref and _actor_title(x[1]).lower() == ref.lower()]
        if not found:
            raise GroupError(f"no actor {ref!r}: give its id (four characters at least) or its name")
        if len(found) > 1:
            raise GroupError(f"{ref!r} names several actors: " + ", ".join(_who(a) for _, a in found[:6]))
        return found[0]


def _members_line(n: int, others: int, group: str) -> str:
    return f"{_plural(n, 'actor')} of it" + (f" and the {_plural(others, 'actor')} of {_title(group)}" if others else "")


def listing(h: _Home) -> dict:
    lines = ["Groups: each shares context within itself only."]

    def inside(group: str, fid: Optional[int], depth: int) -> None:
        pad = "  " * depth
        for g in h.placed_in(group, fid):
            if groups.is_alone(g):
                for a in h.actors(g):
                    lines.append(f"{pad}- {_who(a)}, in {h.folder_path(group, fid)}: on its own")
            else:
                lines.append(f"{pad}- {_title(g)} ({g}), in {h.folder_path(group, fid)}: "
                             f"{_plural(len(h.actors(g)), 'actor')}, a group of its own")
                tree(g, depth + 1)

    def tree(group: str, depth: int) -> None:
        inside(group, None, depth)
        for f in h.tree(group)["folders"]:
            inside(group, f["id"], depth)

    top = [g for g in h.groups if g not in h.places]
    for g in sorted((g for g in top if not groups.is_alone(g)), key=lambda g: _title(g).lower()):
        lines.append(f"- {_title(g)}" + (f" ({g})" if _title(g) != g else "") + f": {_plural(len(h.actors(g)), 'actor')}")
        tree(g, 1)
    lone = [a for g in top if groups.is_alone(g) for a in h.actors(g)]
    if lone:
        lines.append("On their own, at the list's top:")
        lines.extend(f"- {_who(a)}" for a in lone)
    return {"said": lines, "done": False, "places": h.places}


def show(h: _Home, ref: str) -> dict:
    g = h.group(ref)
    filed = h.tree(g)["filed"]
    lines = [f"{_title(g)} ({g}), {h.where(g)}: {_plural(len(h.actors(g)), 'actor')}, sharing context with each other only."]
    for f in h.tree(g)["folders"]:
        lines.append(f"- folder {h.folder_path(g, f['id'])}")
    for a in h.actors(g):
        fid = filed.get(a["channel"])
        lines.append(f"- {_who(a)} -- {a.get('status') or 'idle'}" + (f", in {h.folder_path(g, fid)}" if fid is not None else ""))
    for fid in [None, *(f["id"] for f in h.tree(g)["folders"])]:
        for x in h.placed_in(g, fid):
            what = "on its own" if groups.is_alone(x) else f"the group {_title(x)} ({_plural(len(h.actors(x)), 'actor')})"
            who = ", ".join(_who(a) for a in h.actors(x)) if groups.is_alone(x) else ""
            lines.append(f"- inside {h.folder_path(g, fid)}: {who + ' ' if who else ''}{what}")
    return {"said": lines, "done": False, "group": g}


def _leaving(n: int, others: int, group: str) -> str:
    """What `n` actors leaving `group` (`others` staying) are told, in words."""
    one = n == 1
    return (("Its actor stops" if one else f"Its {n} actors stop") + " sharing context with "
            + (f"the {_plural(others, 'other actor')} of {_title(group)}" if others else f"anyone else in {_title(group)}")
            + ("" if one else ", and share with each other only")
            + ("; it rebuilds its context at its next call." if one else "; they rebuild their context at their next call."))


def folder(h: _Home, ref: str, to: str, dry_run: bool) -> dict:
    group, fid, is_group = h.path(ref)
    if to == OWN:
        if is_group:
            raise GroupError(f"{h.folder_path(group, None)} has its own group already")
        moving = [c for c in groups.actors(group, (), fid) if not c.startswith(folders.APP)]
        others = len([a for a in h.actors(group) if a["channel"] not in moving])
        said = [f"{h.folder_path(group, fid)} becomes a group of its own where it is, named after it, with "
                f"{_title(group)}'s settings.",
                _leaving(len(moving), others, group) if moving
                else "No actor is in it: those started there later share with each other only."]
        if dry_run:
            return {"said": said, "done": False}
        made = groups.own(group, fid)
        return {"said": said + [f"Done: {made['group']} is a group of its own, in {h.folder_path(group, fid)}."],
                "done": True, "own": made}
    if to != PARENT:
        raise GroupError("to what? own (a group of its own) or parent (its parent's group)")
    if not is_group:
        raise GroupError(f"{h.folder_path(group, fid)} has its parent's group already")
    p = h.places.get(group)
    if p is None:
        raise GroupError(f"{_title(group)} is at the list's top: there is no group above it")
    plan = groups.merge_plan(group, p["in"], p["folder"])
    said = [f"{_title(group)} becomes a folder of {_title(p['in'])} again, named {plan['folder']}, in "
            f"{h.folder_path(p['in'], p['folder'])}; the group itself goes from the list.",
            f"The {_members_line(plan['actors'], len(h.actors(p['in'])), p['in'])} share context with each other from "
            "then on; those that move rebuild their context at their next call."]
    if dry_run:
        return {"said": said, "done": False}
    merged = groups.above(group)
    return {"said": said + [f"Done: {_title(group)} is a folder of {_title(p['in'])}."], "done": True, "merged": merged}


def actor(h: _Home, ref: str, to: str, dry_run: bool) -> dict:
    group, a = h.actor(ref)
    who = _who(a)
    if to == ALONE:
        if groups.is_alone(group):
            raise GroupError(f"{who} is on its own already")
        fid = h.tree(group)["filed"].get(a["channel"])
        said = [f"{who} leaves {_title(group)} ({_plural(len(h.actors(group)) - 1, 'other')}) and works on its own, "
                f"staying in {h.folder_path(group, fid)}: it shares context with no other actor, and none with it. It "
                "rebuilds its context at its next call."]
        if dry_run:
            return {"said": said, "done": False}
        got = groups.alone(group, a["channel"], here=True)
        return {"said": said + [f"Done: {who} is on its own."], "done": True, "alone": got}
    if to != FOLDER:
        raise GroupError("to what? folder (its folder's group) or alone (on its own)")
    if not groups.is_alone(group):
        raise GroupError(f"{who} has its folder's group already ({_title(group)})")
    p = h.places.get(group)
    if p is None:
        raise GroupError(f"{who} is at the list's top, in no folder: drag it into a folder, or move it into a group "
                         "(`ag actors move ... --group`)")
    said = [f"{who} joins {_title(p['in'])} ({_plural(len(h.actors(p['in'])), 'actor')}), its folder's group: it shares "
            "context with them from then on, and rebuilds its context at its next call."]
    if dry_run:
        return {"said": said, "done": False}
    moved = groups.move(group, p["in"], [a["channel"]], into=p["folder"])
    return {"said": said + [f"Done: {who} is in {_title(p['in'])}."], "done": True, "moved": moved}


def merge(h: _Home, ref: str, into: str, at: Optional[str], keep: bool, dry_run: bool) -> dict:
    g = h.group(ref)
    to, fid, is_group = h.path(f"{into}/{at}" if at else into)
    if is_group and at:
        raise GroupError(f"{at!r} is a group inside {_title(into)}: name a folder")
    where = h.folder_path(to, fid)
    if keep:
        said = [f"{_title(g)} goes into {where}, keeping its own group: no actor starts or stops sharing context."]
        if dry_run:
            return {"said": said, "done": False}
        got = groups.place(g, to, fid)
        return {"said": said + [f"Done: {_title(g)} is inside {where}."], "done": True, "placed": got}
    plan = groups.merge_plan(g, to, fid)
    said = [f"{_title(g)} becomes a folder of {_title(to)}, named {plan['folder']}, in {where}; the group itself goes "
            "from the list.",
            f"The {_members_line(plan['actors'], len(h.actors(to)), to)} share context with each other from then on; "
            "those that move rebuild their context at their next call."]
    if dry_run:
        return {"said": said, "done": False}
    merged = groups.merge(g, to, fid)
    return {"said": said + [f"Done: {_title(g)} is a folder of {_title(to)}."], "done": True, "merged": merged}


def rename(h: _Home, ref: str, title: str, dry_run: bool) -> dict:
    g = h.group(ref)
    title = folders.folder_name(title)
    said = [f"{_title(g)} is called {title} from now on; no one's context changes."]
    if not dry_run:
        titles.give(g, title)
    return {"said": said, "done": not dry_run}


def manage(body: dict) -> dict:
    """The answer to one `ag groups` command (module doc)."""
    op, dry = str(body.get("op") or "list"), bool(body.get("dry_run"))
    h = _Home()
    try:
        if op == "list":
            return listing(h)
        if op == "show":
            return show(h, str(body.get("group") or ""))
        if op == "folder":
            return folder(h, str(body.get("path") or ""), str(body.get("to") or ""), dry)
        if op == "actor":
            return actor(h, str(body.get("actor") or ""), str(body.get("to") or ""), dry)
        if op == "merge":
            return merge(h, str(body.get("group") or ""), str(body.get("into") or ""), body.get("folder") or None,
                         bool(body.get("keep")), dry)
        if op == "rename":
            return rename(h, str(body.get("group") or ""), str(body.get("title") or ""), dry)
    except folders.FolderError as exc:
        raise GroupError(str(exc)) from None
    raise GroupError(f"no command {op!r}: one of list, show, folder, actor, merge, rename")
