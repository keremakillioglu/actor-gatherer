"""The tool gateway (app_kit/DESIGN.md step 3): the apps' tools for every agent, through one MCP server each --
/mcp/<actor>, given to every session at launch whose harness takes one (harness_kit's `mcp_args`: Claude Code, codex)
-- and the same calls through `ag apps` in the agent's shell, for any harness (ag/cli/apps.py).

Who may use an app's instance is access.py's, asked at every call: the agents in the instance's task, or every agent
of its group (an app whose manifest says `access = "group"`), or the group's coordinator agent. What an agent is given
by name when it starts is only what it may use then.

    on(gatherer)                 the apps on for a gatherer: every app installed (found), in every group alike
    offered(gatherer, channels)  those whose tools an agent is given by name when it starts: each "group" app, and each
                                 "task" app it may use an instance of then (every one, for a coordinator agent)
    tools(gatherer, channels)    the tools for the apps themselves (AG_TOOLS: apps_list, apps_help, apps_mine,
                                 apps_call, dashboard_ls), and the offered apps' own, as MCP lists them: `<app>_<tool>`,
                                 each with the host's `instance` argument
    instructions(gatherer, ...)  what every agent is told of the apps: the MCP server's `instructions` (Claude Code adds
                                 them to its system prompt), and `ag apps`'s list -- every app installed, and who may
                                 use it; the "group" apps' own words. A "task" app's own words are the agent's own
                                 instructions (`launch_args`), when it may use one as it starts
    call(actor, name, args)      a tool called by an actor: one of AG_TOOLS, else an app's, to the instance it may use
                                 (`resolve`) -- then as the host calls any (app_host.py's `call`, which asks access.py
                                 again)
    launch_args(session)         what a session's harness is started with for them: the MCP server, where its harness
                                 takes one (`served`); else (Antigravity) instructions naming `ag apps`; the "task"
                                 apps' instructions; and, for one asking `edit_guard`, the guard on its own edit tools
                                 (app_guard.py); none if no app is installed

`HOST` (the AppHost), `ORIGIN` (where the dashboard serves) and `DASHBOARD` (dashboard_ls's answer: coordination.py's
`tree`) are the server's, set as it starts."""

import json
import os
import shlex
import sys
import urllib.parse
from typing import Callable, Dict, List, Optional, Tuple

import app_kit
import harness_kit
from app_kit import AppError, Caller, Instance

from . import access, mcp

GUARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_guard.py")   # the edit guard's script
NAME = "ag-apps"                # the MCP server's name: harnesses show its tools as mcp__ag-apps__<app>_<tool>
HOST = None                     # the server's AppHost (server.py)
ORIGIN = ""                     # where the dashboard serves (server.py)
DASHBOARD: Optional[Callable[[str, str], str]] = None   # dashboard_ls's answer for an actor and a path (server.py)

ABOUT = ("The apps of this dashboard: each a panel the user may have open beside your conversation. What you do in one, "
         "the user sees there; what the user does there, you are told as a message from its stream. You may use an "
         "app's instance when it is in your task -- or, for an app every agent of your group shares, always -- and "
         "each call is checked when you make it. An app's tools are named <app>_<tool>; give `instance` when you may "
         "use more than one of its instances. For the apps themselves: apps_list (every app installed, and who may use "
         "it), apps_help (an app's instructions and tools), apps_mine (the instances you may use now, and why), "
         "apps_call (a tool of an app you may use but were not given by name: one put in your task after you started) "
         "and dashboard_ls (the dashboard's folders, tasks, actors and apps, walked like a directory). Your harness "
         "may show these tools, and the apps', with a prefix for this server (mcp__ag-apps__apps_list).")
CLI = ("Run them in your shell, where they reach the dashboard on this machine: `ag apps list`, `ag apps help <app>`, "
       "`ag apps mine`, `ag apps call <app>_<tool> '<JSON arguments>' [--instance ID]` and `ag tasks [path]`.")
PYTHON = ("From Python -- to loop over an app's tools, or keep what they return out of your context -- `import agapps` "
          "(on PYTHONPATH in your shell): `agapps.app(\"<app>\").<tool>(...)` calls <app>_<tool>, checked as any call "
          "is, and returns its text, or its JSON parsed; `help(agapps)` says the rest.")
LEAD = ("You coordinate this group: you may use every instance of its apps without being in their tasks. A call goes "
        "to the one you name with `instance`, when several are open (a refusal lists them), and, none open, to one "
        "opened for you. Install, uninstall or update an app only when the user asks you to.")
WHO = {access.TASK: "the agents in its task", access.GROUP: "every agent of the group"}


def endpoint(actor: str) -> str:
    """The id of an actor's MCP server for the apps, as mcp.py's `listed` keeps it."""
    return mcp.endpoint("apps", actor)


def actor_of(s: dict) -> str:
    """The id an actor is known by: the one it was started under (a codex session's, before its thread had one)."""
    return s.get("started_as") or s["session_id"]


def on(gatherer: str) -> List["app_kit.Manifest"]:
    """The apps on for `gatherer`: every app installed (found), the same for every group -- there is no turning one off
    in a group (app_kit's finding.py)."""
    if HOST is None:
        return []
    return [h.manifest for _, h in sorted(HOST.apps.items())]


def gone(name: str) -> str:
    """What an agent is told of a call of a tool it isn't given now: one it was given when its session started, its
    app uninstalled (or updated without it) since -- the agent's list of tools is only read again then."""
    names = sorted(HOST.apps) if HOST is not None else []
    return (f"{name}: no such tool now. Its app was uninstalled, or changed, after your session started; the apps "
            f"installed now: {', '.join(names) or 'none'}.")


def channels_of(s: dict) -> Tuple[str, ...]:
    """The channels a session's agent is known by in its gatherer's tasks: its session's, and the one it was started
    under (a codex session's, before its thread had one)."""
    return access.channels_of(s)


def lead(s: dict) -> bool:
    """Whether the session `s` is its gatherer's own agent (sessions.py's COORDINATOR): given every app on, and may use
    every instance of its group (access.py)."""
    from . import sessions                                          # (it imports this module)
    return s.get("role") == sessions.COORDINATOR


def _row(gatherer: str, channels: Tuple[str, ...]) -> dict:
    return {"gatherer": gatherer, "session_id": channels[0] if channels else "",
            "started_as": channels[1] if len(channels) > 1 else None}


def offered(gatherer: str, channels: Tuple[str, ...] = (), head: bool = False) -> List["app_kit.Manifest"]:
    """The apps whose tools an agent of `gatherer` (any of `channels`) is given by name: each "group" app, and each
    "task" app it may use an instance of now (access.py). `head`, the gatherer's own agent (`lead`): every one on."""
    if head:
        return on(gatherer)
    mine = {i.app for i, _ in access.usable(_row(gatherer, channels))} if channels else set()
    return [m for m in on(gatherer) if m.access == access.GROUP or m.name in mine]


def task_apps(gatherer: str, channels: Tuple[str, ...] = ()) -> List["app_kit.Manifest"]:
    """The "task" apps an agent may use an instance of now: their instructions its own, and their edit guard on it,
    when it starts (`launch_args`)."""
    return [m for m in offered(gatherer, channels) if m.access == access.TASK]


# ---- the tools for the apps themselves

AG_TOOLS = (
    {"name": "apps_list", "inputSchema": {"type": "object", "properties": {}},
     "description": "Every app installed in this dashboard: what each is, who may use its instances (the agents in its "
                    "task, or every agent of the group), whether it can start with an agent of its own, and its tools' "
                    "names."},
    {"name": "apps_help", "inputSchema": {"type": "object", "required": ["app"], "properties": {
        "app": {"type": "string", "description": "The app's name, as apps_list gives it."}}},
     "description": "An app's instructions, and each of its tools with what it takes."},
    {"name": "apps_mine", "inputSchema": {"type": "object", "properties": {}},
     "description": "The app instances you may use now: each one's app, id, name and folder, why you may use it (your "
                    "task, your group), and who else is in that task."},
    {"name": "apps_call", "inputSchema": {"type": "object", "required": ["app", "tool"], "properties": {
        "app": {"type": "string", "description": "The app's name, as apps_list gives it."},
        "tool": {"type": "string", "description": "Its tool's name, as apps_help lists it."},
        "arguments": {"type": "object", "description": "The tool's arguments."},
        "instance": {"type": "string", "description": "Which instance, if you may use more than one (its id)."}}},
     "description": "Call a tool of an app you may use but were not given by name: one put in your task after you "
                    "started. The same check as any app tool's: you must be able to use the instance."},
    {"name": "dashboard_ls", "inputSchema": {"type": "object", "properties": {
        "path": {"type": "string", "description": "A folder's path (`Figures/Plots`), `task:<id>`, or `/` for your "
                                                  "group's top; none: where you are."}}},
     "description": "The dashboard's folders, tasks, actors and app instances, walked like a directory: what is in a "
                    "folder or a task, with each actor's status and each app instance's id. Read only."},
)
AG_TOOL_NAMES = tuple(t["name"] for t in AG_TOOLS)


def tools(gatherer: str, channels: Tuple[str, ...] = (), head: bool = False) -> List[dict]:
    """The tools for the apps themselves, and those of the apps an agent of `gatherer` is given (`offered`), as MCP
    lists them."""
    return [*(dict(t) for t in AG_TOOLS), *(t.mcp(m.name, m.label) for m in offered(gatherer, channels, head)
                                            for t in m.tools)]


def instructions(gatherer: str, cli: bool = False, channels: Tuple[str, ...] = (), head: bool = False) -> str:
    """What every agent is told of the apps (module doc): how they are used, every app installed and who may use it,
    and the "group" apps' own words, each under its name -- for `head`, the gatherer's own agent, every app's.
    `cli`: with how to reach them through `ag apps`, for a harness given no MCP server. "" with no app installed."""
    apps = on(gatherer)
    if not apps:
        return ""
    parts = [ABOUT + (" " + CLI if cli else "") + " " + PYTHON + (" " + LEAD if head else ""),
             "Installed:\n" + "\n".join(f"- {m.label} ({m.name}): {m.description or m.label} -- used by {WHO[m.access]}"
                                        for m in apps)]
    for m in apps:
        if m.access == access.GROUP or head:
            about = (m.told() or m.description).strip()
            parts.append(f"## {m.label} ({m.name})\n{about}" if about else f"## {m.label} ({m.name})")
    return "\n\n".join(parts)


def served(s: dict) -> bool:
    """Whether the session `s` is given the apps' MCP server at launch (`launch_args`)."""
    if HOST is None or not ORIGIN or not s.get("gatherer") or not on(s["gatherer"]):
        return False
    h = harness_kit.get(s.get("harness") or harness_kit.DEFAULT)
    return h is not None and h.mcp_args(NAME, f"{ORIGIN}/mcp/{actor_of(s)}") is not None


def launch_args(s: dict) -> List[str]:
    """What the session `s` (a row of sessions' table) is started with for the apps: an MCP server where its harness
    takes one (`mcp_args`), else how to reach them through `ag apps`; as its own instructions (`instruction_args`,
    where it takes those and has none of its own: a gatherer agent's), the "task" apps' instructions it may use one of
    now (and, given no MCP server, `ag apps`); for one asking `edit_guard`, the guard on its harness's own edit tools
    (`edit_guard_args`). [] when no app is installed, or none of these is taken."""
    if HOST is None or not ORIGIN or not s.get("gatherer") or not on(s["gatherer"]):
        return []
    channels = channels_of(s)
    h = harness_kit.get(s.get("harness") or harness_kit.DEFAULT)
    if h is None:
        return []
    served = h.mcp_args(NAME, f"{ORIGIN}/mcp/{actor_of(s)}")
    mine = [] if lead(s) else task_apps(s["gatherer"], channels)
    told = [m.told().strip() for m in mine if m.told().strip()]
    if served is None:
        told.insert(0, instructions(s["gatherer"], cli=True, channels=channels, head=lead(s)))
    out = list(served or [])
    own = bool(s.get("role")) and not str(s.get("role")).startswith("{")   # a gatherer agent's: instructions of its own
    if told and not own:
        out += list(h.instruction_args("\n\n".join(t for t in told if t)) or [])
    if any(m.capabilities.edit_guard for m in mine):
        q = urllib.parse.urlencode({"gatherer": s["gatherer"], "channel": channels[0]})
        command = (f"{shlex.quote(sys.executable)} {shlex.quote(GUARD)} "
                   f"{shlex.quote(f'{ORIGIN}/api/apps/guard?{q}')} {shlex.quote(h.name)}")
        out += list(h.edit_guard_args(command) or [])
    return out


def row_of(rows: List[dict], actor: str) -> dict:
    """The session an actor's id names (its own, or the one it was started under), else AppError."""
    row = next((r for r in rows if actor and actor in (r["session_id"], r.get("started_as"))), None)
    if row is None:
        raise AppError(f"{actor or '(none)'}: not an actor this dashboard runs", 404)
    return row


def _instance_line(i: Instance, why: Optional[str] = None) -> str:
    where = f" in {i.folder}" if i.folder else ""
    return f"{access.shown(i)}{where}" + (f": {why}" if why else "")


def resolve(row: dict, name: str, args: dict) -> Tuple[str, str, Instance, dict]:
    """(app, tool, instance, the tool's own arguments) of a call by the actor of `row` (access.py's, asked now):

    - the app one installed, the tool one of its;
    - the instance the one it names (`instance`), if it may use it;
    - else the one it may use, if one; several: refused, each named;
    - none: a "group" app's (or, for the coordinator agent, any app's) opened for its group and folder, as the app's
      `instances` says; a "task" app's refused, saying which tasks hold one and how one comes to be in its task."""
    gatherer = row["gatherer"]
    head = lead(row)
    apps = {m.name: m for m in on(gatherer)}
    split = app_kit.split_tool_name(name, apps)
    if split is None or apps[split[0]].tool(split[1]) is None:
        raise AppError(f"{name}: no such tool of the apps installed ({', '.join(sorted(apps)) or 'none'})", 404)
    app, tool = split
    m = apps[app]
    args = dict(args or {})
    named = args.pop(app_kit.manifest.INSTANCE_ARG, None)
    mine = access.usable(row, app)
    if named:
        inst = next((i for i, _ in mine if i.id == named), None)
        if inst is None:
            raise AppError(_not_yours(row, m, str(named), mine), 403)
        return app, tool, inst, args
    through = [i for i, w in mine if w not in (access.GROUP_WHY,)]
    if m.access == access.GROUP and not head:
        inst = through[0] if len(through) == 1 else HOST.open(app, gatherer, row.get("cwd") or None, {},
                                                               by=row["session_id"])
        return app, tool, inst, args
    if len(mine) == 1:
        return app, tool, mine[0][0], args
    if mine:
        raise AppError(f"{len(mine)} of {m.label} you may use: say which with `instance` ("
                       + "; ".join(_instance_line(i) for i, _ in mine) + ")")
    if head:
        return app, tool, HOST.open(app, gatherer, row.get("cwd") or None, {}, by=row["session_id"]), args
    raise AppError(_none_yours(gatherer, m), 403)


def _none_yours(gatherer: str, m) -> str:
    held = access.holders(gatherer, m.name)
    return (f"{m.label}: you may use none of its instances. One is yours to use once it is in your task: the user puts "
            f"one in it from the dashboard (\"+\" on your row, or dragging it onto your row). "
            + (f"Open in your group: {'; '.join(held)}." if held else "None is open in your group."))


def _not_yours(row: dict, m, named: str, mine: List[tuple]) -> str:
    there = next((i for i in HOST.instances_of(row["gatherer"], m.name) if i.id == named), None) if HOST else None
    if there is None:
        return (f"{named}: no {m.label} of your group has that id. Yours: "
                + ("; ".join(_instance_line(i, w) for i, w in mine) or "none") + ".")
    return (f"{named}: you may not use {access.shown(there)}: it is not in your task. Yours: "
            + ("; ".join(_instance_line(i, w) for i, w in mine) or "none")
            + ". The user can put it in your task from the dashboard.")


def call(rows: List[dict], actor: str, name: str, args: dict) -> dict:
    """A tool called by an actor (its id): MCP's result, {content, isError} -- a refusal one too, for the agent to
    read."""
    try:
        row = row_of(rows, actor)
        if name in AG_TOOL_NAMES:
            return _ag_tool(row, name, dict(args or {}))
        app, tool, inst, own = resolve(row, name, args)
    except AppError as exc:
        return app_kit.ToolResult.error(str(exc)).to_dict()
    return _call(row, app, tool, inst, own)


def _call(row: dict, app: str, tool: str, inst: Instance, own: dict) -> dict:
    caller = Caller(channel=row["session_id"], gatherer=row["gatherer"], harness=row.get("harness"),
                    folder=row.get("cwd") or None)
    return HOST.call(app, inst, tool, own, caller, reaches_all=lead(row)).to_dict()


def _text(text: str) -> dict:
    return app_kit.ToolResult.text(text).to_dict()


def _ag_tool(row: dict, name: str, args: dict) -> dict:
    """One of AG_TOOLS, for the actor of `row`."""
    g = row["gatherer"]
    if name == "apps_list":
        return _text(apps_list(g))
    if name == "apps_help":
        return _text(apps_help(g, str(args.get("app") or "")))
    if name == "apps_mine":
        return _text(apps_mine(row))
    if name == "dashboard_ls":
        if DASHBOARD is None:
            raise AppError("dashboard_ls: the dashboard has no view of its lists here")
        return _text(DASHBOARD(actor_of(row), str(args.get("path") or "")))
    app, tool = str(args.get("app") or "").strip(), str(args.get("tool") or "").strip()
    if not app or not tool:
        raise AppError("apps_call: `app` and `tool` (apps_help lists an app's tools)")
    if not tool.startswith(app + "_"):
        tool = app_kit.tool_name(app, tool)
    given = args.get("arguments") if isinstance(args.get("arguments"), dict) else {}
    given = {**{k: v for k, v in args.items() if k not in ("app", "tool", "arguments", "instance")}, **given}
    if args.get("instance"):
        given = {**given, app_kit.manifest.INSTANCE_ARG: str(args["instance"])}
    a, t, inst, own = resolve(row, tool, given)
    return _call(row, a, t, inst, own)


def apps_list(gatherer: str) -> str:
    apps = on(gatherer)
    if not apps:
        return "No app is installed."
    lines = []
    for m in apps:
        tools = ", ".join(app_kit.tool_name(m.name, t.name) for t in m.tools) or "none"
        lines.append(f"- {m.label} ({m.name}): {m.description or m.label}. Used by {WHO[m.access]}. "
                     + ("It can start with an agent of its own. " if m.agent.offered else "")
                     + f"Tools: {tools}.")
    return "Apps installed:\n" + "\n".join(lines) + "\n\napps_help <app> gives one's instructions and its tools."


def apps_help(gatherer: str, name: str) -> str:
    m = next((x for x in on(gatherer) if x.name == name or x.label.lower() == name.lower()), None)
    if m is None:
        raise AppError(f"{name or '(none)'}: no such app installed ({', '.join(x.name for x in on(gatherer)) or 'none'})")
    tools = [{"name": app_kit.tool_name(m.name, t.name), "description": t.description, "arguments": t.input_schema}
             for t in m.tools]
    about = (m.told() or m.description).strip()
    return (f"# {m.label} ({m.name})\nUsed by {WHO[m.access]}.\n\n{about}\n\n## Tools\n"
            + json.dumps(tools, indent=1, ensure_ascii=False)
            + "\n\nEach also takes `instance`: which one, if you may use more than one. A tool you were not given by "
              "name: apps_call with `app`, `tool` and `arguments`.")


def apps_mine(row: dict) -> str:
    mine = access.usable(row)
    if lead(row):
        head = "You coordinate this group: you may use every instance of its apps."
    else:
        head = ("The instances you may use now. Every agent of your group may also use the group's apps ("
                + (", ".join(m.label for m in on(row["gatherer"]) if m.access == access.GROUP) or "none")
                + "): one is opened for you on first use.")
    if not mine:
        return head + "\nNone is open for you now."
    from . import tasks
    known = tasks.of(row["gatherer"])
    lines = []
    for i, w in mine:
        tid = known["tasked"].get(tasks.app_item(i.id))
        others = [c for c, t in known["tasked"].items() if t == tid and tasks.app_of(c) is None
                  and c not in channels_of(row)] if tid is not None else []
        lines.append(f"- {_instance_line(i, w)}" + (f" (with actors {', '.join(others)})" if others else ""))
    return head + "\n" + "\n".join(lines)


def listed(rows: List[dict], actor: str) -> dict:
    """What `ag apps` shows an actor: its gatherer's apps it is given, each with its tools and instructions, the
    instances of each it may use now (`usable`) -- and every app installed, as apps_list says it (`installed`)."""
    row = row_of(rows, actor)
    head = lead(row)
    mine: dict = {}
    for i, w in access.usable(row):
        mine.setdefault(i.app, []).append({"id": i.id, "name": i.name, "title": i.title, "folder": i.folder, "why": w})
    channels = channels_of(row)
    return {"gatherer": row["gatherer"],
            "instructions": instructions(row["gatherer"], cli=True, channels=channels, head=head),
            "installed": apps_list(row["gatherer"]),
            "apps": [{"name": m.name, "label": m.label, "access": m.access, "tools": [t.mcp(m.name) for t in m.tools],
                      "usable": mine.get(m.name, [])}
                     for m in offered(row["gatherer"], channels, head)]}
