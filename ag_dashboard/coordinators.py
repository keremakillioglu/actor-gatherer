"""Where the COORDINATOR AGENTS are, and which one is over whom (the design "Coordinator agents over folders").

The list is one tree: everything (ALL) -> the folders of groups (gatherer_folders.py) -> the groups -> the folders in a
group (folders.py) -> the actors. A coordinator agent is over one NODE of it, and so over every actor under that node:

    "all"              everything: every group of the home
    "groups:<id>"      a folder of groups (gatherer_folders.py's id), and the groups in it, at any depth
    "group:<name>"     a group, the coordinator agent every group could have before
    "folder:<id>"      a folder in a group (folders.py's id: one of the whole home), and the folders in it

A coordinator agent's node is its session's `over` (sessions.py); none, its group's, as before there were others. There
is none until the user starts one (coordination.py's `ensure`), and a node has one at most. An actor on its own (a group
of one, `self:<channel>`) is under no node: no coordinator agent is over it.

An actor's PLACE is the path of nodes from everything down to the folder it is in (`place`); a coordinator agent's, the
path to its node. The coordinator agent over a set of actors (`nearest`) is that of the deepest node holding them all --
their least common ancestor -- or, with none there, of the nearest node above it that has one; none: no coordinator
agent is over them. It is worked out from the tree as it is when a message is sent, so a moved folder or actor leaves
no stale route.

A coordinator agent over a group, or a folder in one, is a member of that group, private as before (coordination.py's
role record): it is shown the group's work. One above groups -- over a folder of groups, or everything -- is in a group
of its own, `self:<channel>`, like an actor on its own, and its role record names the groups it READS, those under its
node (`reads`): the policy shows it their work, and none of them its."""

from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from . import data, folders, gatherer_folders, titles

ALL = "all"
GROUPS = "groups:"
GROUP = "group:"
FOLDER = "folder:"
ALONE = "self:"


def group_node(name: str) -> str:
    return GROUP + name


def kind(node: Optional[str]) -> Optional[str]:
    """"all", "groups", "group" or "folder"; None for no node."""
    node = str(node or "")
    if node == ALL:
        return ALL
    for prefix in (GROUPS, GROUP, FOLDER):
        if node.startswith(prefix) and len(node) > len(prefix):
            return prefix[:-1]
    return None


def above_groups(node: Optional[str]) -> bool:
    """Whether a coordinator agent over `node` is over several groups: everything, or a folder of groups."""
    return kind(node) in (ALL, "groups")


def node_of(row: dict) -> str:
    """The node of a coordinator agent's session (a row of sessions.py's table): its `over`, else its group's."""
    return str(row.get("over") or "") or group_node(str(row.get("gatherer") or ""))


def parse(text: str) -> str:
    """A node as the page or the API names it, checked: a CoordinationError-worthy ValueError for none."""
    text = str(text or "").strip()
    if kind(text) is None:
        raise ValueError(f"which folder? {text!r} names none")
    if kind(text) in ("groups", "folder"):
        try:
            int(text.split(":", 1)[1])
        except ValueError:
            raise ValueError(f"which folder? {text!r} names none") from None
    return text


class Tree:
    """The list's tree, read once (the groups, their folders, the folders of groups, the groups' titles): what a
    question about places asks of it. `groups`: the home's groups (data.py's `gatherer_names`), else read."""

    def __init__(self, groups: Optional[Sequence[str]] = None):
        self.groups = [g for g in (data.gatherer_names() if groups is None else groups) if not str(g).startswith(ALONE)]
        self.gf = gatherer_folders.stored()
        self.trees: Dict[str, dict] = {}
        self.titles = titles.stored() or {}
        self._folder_group: Optional[Dict[int, str]] = None

    def folders_of(self, group: str) -> dict:
        if group not in self.trees:
            self.trees[group] = folders.of(group)
        return self.trees[group]

    def group_of_folder(self, fid: int) -> Optional[str]:
        """The group the folder `fid` is in; None: none has it."""
        if self._folder_group is None:
            stored = folders.stored()
            self.trees.update({g: t for g, t in stored.items() if g not in self.trees})
            self._folder_group = {f["id"]: g for g, t in stored.items() for f in t.get("folders") or []}
        return self._folder_group.get(int(fid))

    # ---- paths

    def _gf_chain(self, fid: Optional[int]) -> List[str]:
        by = {f["id"]: f for f in self.gf.get("folders") or []}
        out, seen = [], set()
        while fid in by and fid not in seen:
            seen.add(fid)
            out.append(f"{GROUPS}{fid}")
            fid = by[fid]["parent"]
        return list(reversed(out))

    def _folder_chain(self, group: str, fid: Optional[int]) -> List[str]:
        by = {f["id"]: f for f in self.folders_of(group).get("folders") or []}
        out, seen = [], set()
        while fid in by and fid not in seen:
            seen.add(fid)
            out.append(f"{FOLDER}{fid}")
            fid = by[fid]["parent"]
        return list(reversed(out))

    def group_path(self, group: str) -> Optional[List[str]]:
        """The path to the group `group`: everything, its folders of groups, it; None for no group of the home's."""
        if group not in self.groups:
            return None
        return [ALL, *self._gf_chain((self.gf.get("filed") or {}).get(group)), group_node(group)]

    def path(self, node: Optional[str]) -> Optional[List[str]]:
        """The path from everything down to `node`, itself last; None for a node that is not there (a folder deleted)."""
        k = kind(node)
        if k == ALL:
            return [ALL]
        if k == "groups":
            fid = int(str(node).split(":", 1)[1])
            if not any(f["id"] == fid for f in self.gf.get("folders") or []):
                return None
            return [ALL, *self._gf_chain(fid)]
        if k == "group":
            return self.group_path(str(node)[len(GROUP):])
        if k == "folder":
            fid = int(str(node).split(":", 1)[1])
            g = self.group_of_folder(fid)
            top = self.group_path(g) if g else None
            return None if top is None else top + self._folder_chain(g, fid)
        return None

    def place(self, group: str, channel: str, started_as: Optional[str] = None) -> List[str]:
        """The actor `channel` of `group`'s place: the path to the folder it is filed in (by its own id, or the one it was
        started under), else to its group; [] for one under no node (on its own, or of no group of the home's)."""
        top = self.group_path(group)
        if top is None:
            return []
        filed = self.folders_of(group).get("filed") or {}
        fid = filed.get(channel, filed.get(started_as) if started_as else None)
        return top + self._folder_chain(group, fid) if fid is not None else top

    def group_of(self, node: str) -> Optional[str]:
        """The group a node over a group or a folder in one is in; None above groups, or for no such node."""
        k = kind(node)
        if k == "group":
            return str(node)[len(GROUP):] if str(node)[len(GROUP):] in self.groups else None
        if k == "folder":
            return self.group_of_folder(int(str(node).split(":", 1)[1]))
        return None

    def folder_id(self, node: str) -> Optional[int]:
        return int(str(node).split(":", 1)[1]) if kind(node) == "folder" else None

    def under(self, node: str, place: Sequence[str]) -> bool:
        """Whether a place (`place`'s) is under `node`, at any depth, the node itself counted."""
        return bool(place) and node in place

    def reads(self, node: str) -> List[str]:
        """The groups under a node above groups (everything, a folder of groups): what its coordinator agent reads."""
        if not above_groups(node):
            return []
        return sorted(g for g in self.groups if node in (self.group_path(g) or []))

    # ---- names

    def title(self, group: str) -> str:
        return str(self.titles.get(group) or group)

    def label(self, node: Optional[str]) -> str:
        """A node as the agents and the page name it: "everything"; a folder of groups' path (`Research`); a group's
        name; a folder's, after its group's (`paper/Figures`); "" for a node that is not there."""
        k = kind(node)
        if k == ALL:
            return "everything"
        if k == "groups":
            by = {f["id"]: f for f in self.gf.get("folders") or []}
            names = [by[int(n.split(":", 1)[1])]["name"] for n in (self.path(node) or [])[1:]
                     if int(n.split(":", 1)[1]) in by]
            return "/".join(names)
        if k == "group":
            return str(node)[len(GROUP):]
        if k == "folder":
            g = self.group_of(str(node))
            p = folders.path(self.folders_of(g), self.folder_id(str(node))) if g else None
            return f"{g}/{p}" if g and p else ""
        return ""

    def described(self, node: str) -> str:
        """A node at more length, for a coordinator agent's instructions: 'the folder Figures, in the group paper'."""
        k, label = kind(node), self.label(node)
        if k == ALL:
            return "everything: every group of the user's"
        if k == "groups":
            inside = self.reads(node)
            return f"the folder of groups {label}" + (f", which holds the groups {_and(inside)}" if inside else "")
        if k == "group":
            return f"the group {label}"
        if k == "folder":
            g = self.group_of(node) or ""
            return f"the folder {label[len(g) + 1:]}, in the group {g}"
        return "a folder that is no longer there"


def crew_name(tree: Tree, node: str) -> str:
    """A coordinator agent's name, after the node it is over: "Figures coordinator" (a folder's own name), "paper
    coordinator" (a group's title), "Research coordinator" (a folder of groups'), "Everything coordinator"."""
    k = kind(node)
    if k == ALL:
        base = "Everything"
    elif k == "group":
        base = tree.title(str(node)[len(GROUP):])
    else:
        base = tree.label(node).split("/")[-1]
    return f"{base or 'Folder'} coordinator"


def names(rows: Iterable[dict]) -> Dict[str, str]:
    """{session id: its name (`crew_name`)} of the coordinator agents among `rows` (sessions.py's)."""
    crews = [r for r in rows if r.get("role") == "coordinator"]
    if not crews:
        return {}
    tree = Tree()
    return {r["session_id"]: crew_name(tree, node_of(r)) for r in crews}


def _and(names: Iterable[str]) -> str:
    names = list(names)
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1] if names else ""


def common(places: Iterable[Sequence[str]]) -> List[str]:
    """The path to the deepest node every place is under (their least common ancestor); [] when one is under none."""
    places = [list(p) for p in places]
    if not places or any(not p for p in places):
        return []
    out = []
    for nodes in zip(*places):
        if any(n != nodes[0] for n in nodes):
            break
        out.append(nodes[0])
    return out


def nearest(places: Iterable[Sequence[str]], by_node: Dict[str, dict], but: Iterable[str] = ()) -> Tuple[Optional[dict], List[str]]:
    """(the coordinator agent of the deepest node holding every place, else of the nearest node above it with one --
    `by_node`'s, {node: its session}, none of `but`'s channels -- or None; the path to that deepest node)."""
    lca, skip = common(places), set(but)
    for node in reversed(lca):
        row = by_node.get(node)
        if row is not None and row["session_id"] not in skip:
            return row, lca
    return None, lca
