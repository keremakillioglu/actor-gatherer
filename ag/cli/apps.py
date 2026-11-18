"""`ag apps`: the apps of the gatherer an actor works in -- each one's tools, and a call of one -- asked of the
dashboard (ag_dashboard/tool_gateway.py), over its local API (POST /api/apps/agent...), as `ag actors` asks it. For an
agent whose harness the dashboard gives no MCP server; one it gives one (Claude Code, codex) has the same tools there.

    ag apps [list]                              the gatherer's apps: what each says of itself, its tools (with what
                                                each takes) and the ones you are attached to
    ag apps call <app>_<tool> [ARGS]            a tool called: ARGS its arguments, a JSON object (- reads it from
                                                stdin; none: {}); --instance I, which one, when attached to several

Installing (the dashboard's Apps page does the same; an app installed is on in every group, its tools given to an
agent when its terminal next starts):

    ag apps list --all                          every app installed, those that couldn't load, those to install
    ag apps install <folder | git URL | name>   copied aside and checked, what it may do and gives agents printed, then
                                                asked (--yes: not asked); a name: an app that comes with ag, uninstalled
    ag apps uninstall <name> [--data]           asked first (--yes: not); --data: its data/ deleted too
    ag apps update <name>                       its git source fetched again, what changes printed, then asked

Who asks is the session the command runs in, as for `ag actors` (--as names another). `--json` prints the answer as
JSON. Standard library only."""

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Callable, List

from . import actors

CATALOG_OPS = ("install", "uninstall", "update")


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ag apps", description="The apps of this actor's gatherer: their tools, and a "
                                 "call of one.")
    ap.add_argument("--as", dest="who", help="ask as this actor (its id), not the session the command runs in")
    ap.add_argument("--json", action="store_true", help="print the answer as JSON")
    sub = ap.add_subparsers(dest="op")
    ls = sub.add_parser("list", help="the gatherer's apps and their tools")
    ls.add_argument("--all", action="store_true",
                    help="every app installed, those that couldn't load, those to install")
    c = sub.add_parser("call", help="call an app's tool")
    c.add_argument("tool", help="<app>_<tool>, as `ag apps` lists it")
    c.add_argument("args", nargs="?", default="{}", help="its arguments, a JSON object (- reads it from stdin)")
    c.add_argument("--instance", help="which one, when you are attached to more than one")
    i = sub.add_parser("install", help="install an app: a folder, a git URL, or the name of one that comes with ag")
    i.add_argument("source", help="a folder, a git URL, or the name of an app that comes with ag, uninstalled")
    i.add_argument("--yes", action="store_true", help="install it without asking")
    u = sub.add_parser("uninstall", help="uninstall an app: its windows close, agents lose its tools")
    u.add_argument("name")
    u.add_argument("--data", action="store_true", help="delete its data too")
    u.add_argument("--yes", action="store_true", help="uninstall it without asking")
    up = sub.add_parser("update", help="update an app installed from git to its newest commit")
    up.add_argument("name")
    up.add_argument("--yes", action="store_true", help="update it without asking")
    return ap


def main(argv: List[str]) -> int:
    opts = parser().parse_args(argv)
    op = opts.op or "list"
    try:
        url = actors.dashboard_url()
        if not url:
            raise actors.ActorsError("no dashboard runs on this home: the apps are the dashboard's (`ag dashboard`)")
        if op in CATALOG_OPS or (op == "list" and getattr(opts, "all", False)):
            return installing(url, op, opts)
        actor = actors.actor_id(given=opts.who)
        if not actor:
            raise actors.ActorsError("not run by an actor: say which with --as <id>")
        if op == "call":
            raw = sys.stdin.read() if opts.args == "-" else opts.args
            try:
                args = json.loads(raw or "{}")
            except ValueError as exc:
                raise actors.ActorsError(f"its arguments are not JSON: {exc}") from None
            if not isinstance(args, dict):
                raise actors.ActorsError("its arguments are a JSON object")
            if opts.instance:
                args["instance"] = opts.instance
            got = actors.ask(url, "agent/call", {"actor": actor, "tool": opts.tool, "args": args}, api="apps")
        else:
            got = actors.ask(url, "agent", {"actor": actor}, api="apps")
    except actors.ActorsError as exc:
        print(f"ag apps: {exc}", file=sys.stderr)
        return 1
    if opts.json:
        print(json.dumps(got, indent=2))
    elif op == "call":
        print(said(got))
    else:
        print(listed(got))
    return 1 if op == "call" and got.get("isError") else 0


def said(result: dict) -> str:
    """A tool's result as text: its text parts, and a line for each picture or other part."""
    out = []
    for part in result.get("content") or []:
        if part.get("type") == "text":
            out.append(part.get("text", ""))
        else:
            out.append(f"[{part.get('type')}{': ' + part['mimeType'] if part.get('mimeType') else ''}]")
    return "\n".join(out) or ("(an error, with no words)" if result.get("isError") else "(done)")


def listed(got: dict) -> str:
    if not got.get("apps"):
        return f"No app is on in gatherer {got.get('gatherer')}."
    out = [got.get("instructions", "").strip(), ""]
    for a in got["apps"]:
        said = "open" if "open" in a else "attached"         # a gatherer agent's: the open ones, attached to none
        mine = ", ".join(f"{i['id']} ({i.get('name') or i.get('title') or i.get('folder') or i['id']})" for i in a.get(said) or [])
        out.append(f"{a['label']} ({a['name']})" + (f" -- {said}: {mine}" if mine else ""))
        for t in a.get("tools") or []:
            props = (t.get("inputSchema") or {}).get("properties") or {}
            need = set((t.get("inputSchema") or {}).get("required") or [])
            args = ", ".join(f"{k}{'' if k in need else '?'}" for k in props if k != "instance")
            out.append(f"  {t['name']}({args}): {t.get('description', '')}")
        out.append("")
    return "\n".join(out).rstrip()


# -- installing: the Apps page's routes (api/app_catalog.py)

def _get(url: str, path: str) -> dict:
    try:
        with urllib.request.urlopen(f"{url}{path}", timeout=actors.TIMEOUT) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raise actors.ActorsError(f"the dashboard answered {exc.code}") from None
    except (urllib.error.URLError, OSError) as exc:
        raise actors.ActorsError(f"the dashboard didn't answer: {exc}") from None


def _confirm(question: str, yes: bool, ask: Callable[[str], str] = input) -> bool:
    if yes:
        return True
    if not sys.stdin.isatty():
        raise actors.ActorsError("not asked (no terminal to ask in): add --yes to go ahead")
    return ask(f"{question} [y/N] ").strip().lower() in ("y", "yes")


def _staged_ok(ask: Callable[[], bool], post: Callable[[str, dict], dict], st: dict) -> bool:
    """Whether to go on with a staged app: asked; not (or not asked), it is discarded -- never left staged."""
    try:
        ok = ask()
    except BaseException:
        post("discard", {"id": st["id"]})
        raise
    if not ok:
        post("discard", {"id": st["id"]})
    return ok


def installing(url: str, op: str, opts) -> int:
    def post(what: str, body: dict) -> dict:
        return actors.ask(url, what, body, api="apps")

    got = _get(url, "/api/apps/catalog")
    names = {a["name"]: a for a in got.get("installed") or []}
    if op == "list":
        print(json.dumps(got, indent=2) if opts.json else catalog_said(got))
        return 0
    if op == "uninstall":
        a = names.get(opts.name)
        if a is None:
            raise actors.ActorsError(f"{opts.name} isn't installed (`ag apps list --all`)")
        print(uninstall_said(a, opts.data))
        if not _confirm(f"Uninstall {a['label']}?", opts.yes):
            print("Not uninstalled.")
            return 1
        done = post("uninstall", {"name": opts.name, "data": opts.data})
        print(f"Uninstalled {a['label']}." + ("" if opts.data else f" Its data is kept in {a['data']['path']}."))
        return 0 if done.get("name") else 1
    if op == "install":
        back = next((a for a in got.get("available") or [] if a["name"] == opts.source and a["origin"] == "builtin"),
                    None)
        if back is not None:                                     # one that comes with ag, uninstalled: back
            post("install", {"builtin": back["name"]})
            print(f"Installed {back['label']} again: it's on in every group.")
            return 0
        st = post("stage", {"source": opts.source})
        if st.get("installed"):
            post("discard", {"id": st["id"]})
            raise actors.ActorsError(f"{st['name']} is installed already: `ag apps update {st['name']}`")
        print(staged_said(st))
        if not _staged_ok(lambda: _confirm(f"Install {st['label']}?", opts.yes), post, st):
            print("Not installed.")
            return 1
        post("install", {"id": st["id"]})
        print(f"Installed {st['label']}: it's on in every group. Agents get its tools when their terminal next starts.")
        return 0
    a = names.get(opts.name)                                     # update
    if a is None or a.get("kind") != "git":
        raise actors.ActorsError(f"{opts.name} isn't installed from git, so it can't be updated")
    st = post("stage", {"source": a["source"]})
    print(changes_said(st))
    if st.get("commit") == a.get("commit"):
        post("discard", {"id": st["id"]})
        print(f"{a['label']} is up to date.")
        return 0
    if not _staged_ok(lambda: _confirm(f"Update {a['label']}?", opts.yes), post, st):
        print("Not updated.")
        return 1
    post("install", {"id": st["id"], "update": True})
    print(f"Updated {a['label']} to {st['version']}.")
    return 0


def _where(a: dict) -> str:
    return {"builtin": "comes with ag", "path": "in AG_APPS_PATH", "index": "ag's index"}.get(
        a.get("origin") or "", a.get("source") or "installed")


def _who(a: dict) -> str:
    return "every agent" if a.get("offer") == "always" else "agents attached to it"


def catalog_said(got: dict) -> str:
    out = ["Installed (on in every group):"]
    for a in got.get("installed") or []:
        windows = sum((a.get("open") or {}).values())
        out.append(f"  {a['label']} ({a['name']}) {a['version']} -- {_where(a)}; {len(a['tools'])} tools for "
                   f"{_who(a)}, ~{a['tokens']} tokens each" + (f"; {windows} open" if windows else ""))
    if got.get("available"):
        out.append("Available to install (`ag apps install <source or name>`):")
        for a in got["available"]:
            out.append(f"  {a['label']} ({a['name']}) -- {a.get('description') or ''} "
                       f"[{a['name'] if a.get('origin') == 'builtin' else a.get('source')}]")
    if got.get("broken"):
        out.append("Couldn't load:")
        for b in got["broken"]:
            out.append(f"  {b['folder']}: {b['error']}")
    return "\n".join(out)


def staged_said(st: dict) -> str:
    out = [f"{st['label']} ({st['name']}) {st['version']}: {st.get('description') or ''}",
           f"  from {st['source']}" + (f" at {st['commit'][:7]}" if st.get("commit") else ""),
           f"  agents get: {len(st['tools'])} tools ({', '.join(st['tools'])}), ~{st['tokens']} tokens each, "
           f"{_who(st)}"]
    can = list(st.get("can") or [])
    if st.get("own_process"):
        can.insert(0, "running its own process on this computer")
    for c in can:
        out.append(f"  it can: {c}")
    for s in st.get("schedules") or []:
        out.append(f"  it works on its own: {s}")
    out.append("Installing runs its code on this computer with your permissions: ag doesn't sandbox it.")
    return "\n".join(out)


def changes_said(st: dict) -> str:
    ch = st.get("changes") or {}
    out = [f"{st['label']}: {' -> '.join(ch.get('version') or [st['version']])}"]
    out += [f"  a new tool: {t}" for t in ch.get("tools_added") or []]
    out += [f"  a tool gone: {t}" for t in ch.get("tools_gone") or []]
    out += [f"  new, it can: {c}" for c in ch.get("can_added") or []]
    if ch.get("own_process"):
        out.append("  new, it runs its own process on this computer")
    return "\n".join(out)


def uninstall_said(a: dict, data: bool) -> str:
    windows = sum((a.get("open") or {}).values())
    out = [f"{a['label']} ({a['name']}): " + (f"its {windows} open window(s) close; " if windows else "")
           + "agents lose its tools when their terminal next starts; what it put in your history stays."]
    if a.get("origin") == "builtin":
        out.append("It comes with ag: `ag apps install " + a["name"] + "` brings it back.")
    out.append(f"Its data ({a['data']['path']}) is " + ("deleted." if data else "kept."))
    return "\n".join(out)
