"""The tool gateway (app_kit/DESIGN.md step 3): the apps' tools for every agent, through one MCP server each --
/mcp/<actor>, given to every session at launch whose harness takes one (harness_kit's `mcp_args`: Claude Code, codex)
-- and the same calls through `ag apps` in the agent's shell, for any harness (ag/cli/apps.py).

    on(gatherer)                 the apps on for a gatherer: every app installed (found), in every group alike
    offered(gatherer, channels)  those an agent is given: each on whose manifest's `offer` is "always", and each
                                 "attached" one it is attached to an instance of
    tools(gatherer, channels)    their tools, as MCP lists them: `<app>_<tool>`, each with the host's `instance` argument
    instructions(gatherer, ...)  what agents are told of the "always" ones: the MCP server's `instructions` (Claude Code
                                 adds them to its system prompt), and `ag apps`'s list. An "attached" app's are the
                                 agent's own instructions (`launch_args`), as a DocWriter's actor's were
    call(actor, name, args)      a tool called by an actor: to the instance it is attached to -- the one it names
                                 (`instance`) when it has several; none, one opened for its gatherer and folder, and it
                                 attached -- then as the host calls any (app_host.py's `call`)
    launch_args(session)         what a session's harness is started with for them: the MCP server, where its harness
                                 takes one (`served`); else (Antigravity) instructions naming `ag apps`; the attached
                                 apps' instructions; and, attached to one asking `edit_guard`, the guard on its own
                                 edit tools (app_guard.py); none if no app is offered it

`HOST` (the AppHost) and `ORIGIN` (where the dashboard serves) are the server's, set as it starts."""

import os
import shlex
import sys
import urllib.parse
from typing import List, Optional, Tuple

import app_kit
import harness_kit
from app_kit import AppError, Caller, Instance

from . import mcp

GUARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_guard.py")   # the edit guard's script
NAME = "ag-apps"                # the MCP server's name: harnesses show its tools as mcp__ag-apps__<app>_<tool>
HOST = None                     # the server's AppHost (server.py)
ORIGIN = ""                     # where the dashboard serves (server.py)
CLI = ("Run `ag apps` in your shell to list them and what each tool takes, and `ag apps call <app>_<tool> '<JSON "
       "arguments>'` to call one: it reaches the dashboard on this machine.")


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


def channels_of(s: dict) -> Tuple[str, ...]:
    """The channels a session's agent is known by in its gatherer's attachments: its session's, and the one it was
    started under (a codex session's, before its thread had one)."""
    return tuple(c for c in (s.get("session_id"), s.get("started_as")) if c)


def attached_apps(gatherer: str, channels: Tuple[str, ...] = ()) -> List["app_kit.Manifest"]:
    """The apps on for `gatherer` whose instances the agent (any of `channels`) is attached to."""
    if HOST is None or not channels:
        return []
    names = {i.app for c in channels for i in HOST.attached_to(gatherer, c)}
    return [m for m in on(gatherer) if m.name in names]


def lead(s: dict) -> bool:
    """Whether the session `s` is its gatherer's own agent (sessions.py's COORDINATOR): given every app on, attached to
    none."""
    from . import sessions                                          # (it imports this module)
    return s.get("role") == sessions.COORDINATOR


def offered(gatherer: str, channels: Tuple[str, ...] = (), head: bool = False) -> List["app_kit.Manifest"]:
    """The apps an agent of `gatherer` (any of `channels`) is given: those on whose `offer` is "always", and the
    "attached" ones it is attached to an instance of. `head`, the gatherer's own agent (`lead`): every one on."""
    if head:
        return on(gatherer)
    mine = {m.name for m in attached_apps(gatherer, channels)}
    return [m for m in on(gatherer) if m.offer == "always" or m.name in mine]


def tools(gatherer: str, channels: Tuple[str, ...] = (), head: bool = False) -> List[dict]:
    """The tools of the apps an agent of `gatherer` is given (`offered`), as MCP lists them."""
    return [t.mcp(m.name, m.label) for m in offered(gatherer, channels, head) for t in m.tools]


LEAD = ("You are attached to none of them, and reach every one: a call goes to the gatherer's open instance of its "
        "app -- the one you name with `instance`, when several are open (a refusal lists them) -- and, none open, to "
        "one opened for you.")


def instructions(gatherer: str, cli: bool = False, channels: Tuple[str, ...] = (), head: bool = False) -> str:
    """What agents are told of the apps they are given whose `offer` is "always": each one's own words, under its
    name. `cli`: with how to reach them through `ag apps`, for a harness given no MCP server -- and the "attached" ones
    too, which it reaches the same way. `head`, the gatherer's own agent: of every one, and how it reaches them."""
    apps = [m for m in offered(gatherer, channels, head) if m.offer == "always" or cli or head]
    if not apps:
        return ""
    parts = ["The apps of this gatherer: tools you can call, each on an app the user may also have open beside your "
             "conversation. What you do in one, the user sees there; what the user does there, you are told as a "
             "message. Each app's tools are named <app>_<tool>." + (" " + CLI if cli else "") +
             (" " + LEAD if head else "")]
    for m in apps:
        about = (m.instructions or m.description).strip()
        parts.append(f"## {m.label} ({m.name})\n{about}" if about else f"## {m.label} ({m.name})")
    return "\n\n".join(parts)


def served(s: dict) -> bool:
    """Whether the session `s` is given the apps' MCP server at launch (`launch_args`)."""
    if HOST is None or not ORIGIN or not s.get("gatherer") or not offered(s["gatherer"], channels_of(s), lead(s)):
        return False
    h = harness_kit.get(s.get("harness") or harness_kit.DEFAULT)
    return h is not None and h.mcp_args(NAME, f"{ORIGIN}/mcp/{actor_of(s)}") is not None


def launch_args(s: dict) -> List[str]:
    """What the session `s` (a row of sessions' table) is started with for the apps it is given (`offered`): an MCP
    server where its harness takes one (`mcp_args`), else how to reach them through `ag apps`; as its own instructions
    (`instruction_args`, where it takes those and has none of its own: a gatherer agent's), the attached apps'
    instructions (and, given no MCP server, `ag apps`); attached to an app asking `edit_guard`, the guard on its
    harness's own edit tools (`edit_guard_args`). [] when it is given no app, or none of these is taken."""
    if HOST is None or not ORIGIN or not s.get("gatherer"):
        return []
    channels = channels_of(s)
    if not offered(s["gatherer"], channels, lead(s)):
        return []
    h = harness_kit.get(s.get("harness") or harness_kit.DEFAULT)
    if h is None:
        return []
    served = h.mcp_args(NAME, f"{ORIGIN}/mcp/{actor_of(s)}")
    mine = attached_apps(s["gatherer"], channels)
    told = [m.instructions.strip() for m in mine if m.offer == "attached" and m.instructions.strip()]
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


def resolve(row: dict, name: str, args: dict) -> Tuple[str, str, Instance, dict]:
    """(app, tool, instance, the tool's own arguments) of a call by the actor of `row`: the app one on for its
    gatherer; the instance the one it names, or the one it is attached to -- none: one opened for its gatherer and
    folder, as the app's `instances` says, and the actor attached to it; in the actor's task (task_links.py) only if
    opened for it alone, by this call, and not the gatherer's one of an app it has one of (an instance others use: their
    task, or none, kept). A gatherer's own agent (`lead`): every app's, attached to none -- the instance the one it
    names of the gatherer's open ones, else the one open, none: one opened."""
    gatherer, channel = row["gatherer"], row["session_id"]
    head = lead(row)
    apps = {m.name: m for m in offered(gatherer, channels_of(row), head)}
    split = app_kit.split_tool_name(name, apps)
    if split is None or apps[split[0]].tool(split[1]) is None:
        raise AppError(f"{name}: no such tool of this gatherer's apps ({', '.join(sorted(apps)) or 'none on'})", 404)
    app, tool = split
    args = dict(args or {})
    named = args.pop(app_kit.manifest.INSTANCE_ARG, None)
    if head:
        mine, which = HOST.instances_of(gatherer, app), "open in this gatherer"
    else:
        mine, which = [i for c in channels_of(row) for i in HOST.attached_to(gatherer, c) if i.app == app], \
            "you are attached to"
    if named:
        inst = next((i for i in mine if i.id == named), None)
        if inst is None:
            raise AppError(f"{named}: not a {apps[app].label} {which} ({', '.join(i.id for i in mine) or 'none'})", 403)
    elif len(mine) == 1:
        inst = mine[0]
    elif mine:
        raise AppError(f"{len(mine)} of {apps[app].label} {which}: say which with `instance` "
                       f"({', '.join(f'{i.id} ({i.name or i.title or i.folder or i.id})' for i in mine)})")
    else:
        with HOST.lock:
            had = set(HOST.instances)
        inst = HOST.open(app, gatherer, row.get("cwd") or None, {}, by=channel)
        if not head:
            if inst.id not in had and apps[app].instances != "one":
                from . import task_links                                     # (it imports this module)
                task_links.link(gatherer, inst.id, channel)                 # opened for it: in its task
            HOST.attach(gatherer, inst.id, channel, by=channel)
    return app, tool, inst, args


def call(rows: List[dict], actor: str, name: str, args: dict) -> dict:
    """A tool called by an actor (its id): MCP's result, {content, isError} -- a refusal one too, for the agent to
    read."""
    try:
        row = row_of(rows, actor)
        app, tool, inst, own = resolve(row, name, args)
    except AppError as exc:
        return app_kit.ToolResult.error(str(exc)).to_dict()
    caller = Caller(channel=row["session_id"], gatherer=row["gatherer"], harness=row.get("harness"),
                    folder=row.get("cwd") or None)
    return HOST.call(app, inst, tool, own, caller, reaches_all=lead(row)).to_dict()


def listed(rows: List[dict], actor: str) -> dict:
    """What `ag apps` shows an actor: its gatherer's apps, each with its tools and instructions, and the instances it
    is attached to -- a gatherer's own agent, attached to none: the gatherer's open ones (`open`), each its to name."""
    row = row_of(rows, actor)
    head = lead(row)
    mine: dict = {}
    for i in HOST.instances_of(row["gatherer"]) if head else HOST.attached_to(row["gatherer"], row["session_id"]):
        mine.setdefault(i.app, []).append({"id": i.id, "name": i.name, "title": i.title, "folder": i.folder})
    channels = channels_of(row)
    return {"gatherer": row["gatherer"],
            "instructions": instructions(row["gatherer"], cli=True, channels=channels, head=head),
            "apps": [{"name": m.name, "label": m.label, "tools": [t.mcp(m.name) for t in m.tools],
                      ("open" if head else "attached"): mine.get(m.name, [])}
                     for m in offered(row["gatherer"], channels, head)]}
