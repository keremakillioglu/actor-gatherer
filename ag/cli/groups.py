"""`ag groups`: the home's groups, and who shares context with whom -- read, and changed by name with the rules of the
dashboard list's own drags and switches -- asked of the dashboard (ag_dashboard/group_admin.py) over its local API
(POST /api/groups/manage), as `ag actors` asks it. For the user, from any shell; a coordinator agent uses it only when
the user asks it to.

    ag groups [list]                            every group: where it is, how many actors it has, and the groups and
                                                actors on their own inside its folders
    ag groups show <group>                      one group: its folders, its actors, what is inside it
    ag groups folder <path> own|parent          the folder given a group of its own where it is (own), or a group
                                                inside another group's folder made part of that group again (parent)
    ag groups actor <actor> alone|folder        the actor on its own, staying in its folder (alone), or back in its
                                                folder's group (folder)
    ag groups merge <group> <into> [--folder <path>] [--keep]
                                                the group made a folder of <into> (in its folder <path>), its actors
                                                joining; --keep: put there keeping its own group, a group inside it
    ag groups rename <group> <title>            its title: no one's context changes

A folder has its parent's group or its own; an actor has its folder's group or is on its own. Each change says first who
starts and stops sharing context with whom, then is made; `--dry-run` only says it. A path is a group's name or title,
then its folders' names, joined by "/" (`making_ag/Work/Figures`); a group inside a folder is named in a path as a folder
is. An actor is named by its id (four characters at least) or its name. `--json` prints the answer as JSON. Standard
library only."""

import argparse
import json
import sys
from typing import List

from . import actors


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ag groups", description="The home's groups: who shares context with whom.")
    ap.add_argument("--json", action="store_true", help="print the answer as JSON")
    ap.add_argument("--dry-run", action="store_true", help="say what a change would do, and change nothing")
    sub = ap.add_subparsers(dest="op")
    sub.add_parser("list", help="every group, and what is inside its folders")
    sub.add_parser("show", help="one group: its folders, actors and what is inside it").add_argument("group")
    folder = sub.add_parser("folder", help="a folder given a group of its own (own), or back in its parent's (parent)")
    folder.add_argument("path", help="the folder's path, from its group's name (`making_ag/Work/Figures`)")
    folder.add_argument("to", choices=("own", "parent"))
    actor = sub.add_parser("actor", help="an actor on its own (alone), or back in its folder's group (folder)")
    actor.add_argument("actor", help="its id (or its first characters) or its name")
    actor.add_argument("to", choices=("alone", "folder"))
    merge = sub.add_parser("merge", help="a group made a folder of another (or, --keep, a group inside its folder)")
    merge.add_argument("group")
    merge.add_argument("into", help="the group it goes into")
    merge.add_argument("--folder", help="its folder there, a path in it (none: its top)")
    merge.add_argument("--keep", action="store_true", help="keep its own group: a group inside that folder")
    rename = sub.add_parser("rename", help="a group's title")
    rename.add_argument("group")
    rename.add_argument("title")
    for change in (folder, actor, merge, rename):          # after the command too: `ag groups folder P own --dry-run`
        change.add_argument("--dry-run", action="store_true", default=argparse.SUPPRESS,
                            help="say what it would do, and change nothing")
    return ap


def main(argv: List[str]) -> int:
    opts = parser().parse_args(argv)
    op = opts.op or "list"
    body = {"op": op, "dry_run": bool(opts.dry_run)}
    for k in ("group", "path", "to", "actor", "into", "folder", "keep", "title"):
        v = getattr(opts, k, None)
        if v not in (None, False):
            body[k] = v
    try:
        url = actors.dashboard_url()
        if not url:
            raise actors.ActorsError("no dashboard runs on this home: the groups are changed by the dashboard "
                                     "(`ag dashboard`)")
        got = actors.ask(url, "manage", body, api="groups")
    except actors.ActorsError as exc:
        print(f"ag groups: {exc}", file=sys.stderr)
        return 1
    if opts.json:
        print(json.dumps(got, indent=2))
    else:
        print("\n".join(got.get("said") or []))
        if opts.dry_run and op not in ("list", "show"):
            print("Nothing changed (--dry-run).")
    return 0
