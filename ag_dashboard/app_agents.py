"""Apps that start an agent of their own (app_kit/DESIGN.md step 8; a manifest's `[agent] start`): DocWriter, say, whose
menu entry makes a new instance in a folder and a new actor there to work with the user in it. Both ways in -- the page's
"+ ⋯" menu (/api/apps/start, api/apps.py) and the gatherer agent's `ag actors new --<app>` (coordination.py) -- come
here, so they make the same thing:

    start(started, host, app, gatherer, cwd, harness, model=None, name=None)
        a new instance of `app` (app_host.py's `open`), in `cwd`; a new session there (sessions.py's `create`) whose
        role says whose it is, {"app": <name>, "key": <instance>} -- the page shows an app's actor by it -- attached to
        the instance before its harness starts, so the tool gateway gives it the app's tools, instructions and guard
        at launch (tool_gateway.py's `launch_args`); named once its gatherer has it (`name`, else the manifest's
        `[agent] name`) -> (its session, as the table has it; the instance)

    role_of(session)   the app and instance a session's role names: {"app": name, "key": id}, or an app's own older
                       form, {"<name>": key} -- None for any other
    Messenger(started)  what the app host is given to pass on an app's own messages to its agents (`send`) and to start
                       one of its own with a message (`start`), as Chat sends and as `start` above makes one
    adopt_all(started, host)   each session whose role names an app the host has (an app's actor from before it was
                       an app: DocWriter's, {"docwriter": key}) attached to that app's instance of that key -- made, if
                       it is not yet, on the session's folder (app_host.py's `adopt`): at the server's start, once
                       each (the host's events keep it)
"""

import json
import os
import threading
import time
from typing import Optional, Tuple

import harness_kit
from app_kit import AppError, Instance

from . import naming, sessions, task_links

NAME_WAIT = 600.0           # how long a new actor's first call is waited for, to name it (its gatherer has it then)


def role(app: str, key: str) -> str:
    return json.dumps({"app": app, "key": key})


def role_of(s: dict) -> Optional[Tuple[str, str]]:
    """(app, instance id) of an app's actor: its role {"app": name, "key": id}, or {"<name>": key} (an app's actor
    from before it was an app, kept so: the host adopts it, app_host.py's `adopt`); None for any other session."""
    try:
        got = json.loads(s.get("role") or "null")
    except (TypeError, ValueError):
        return None
    if not isinstance(got, dict):
        return None
    if isinstance(got.get("app"), str) and isinstance(got.get("key"), str):
        return got["app"], got["key"]
    if len(got) == 1:
        (name, key), = got.items()
        if isinstance(key, str):
            return name, key
    return None


def adopt_all(started: "sessions.Sessions", host) -> None:
    """Each app's actor from before it was an app attached to its instance (module doc)."""
    if host is None:
        return
    for s in started.list():
        got = role_of(s)
        if got is None or got[0] not in host.apps:
            continue
        name, key = got
        try:
            host.adopt(name, s["gatherer"], key, s.get("cwd") or None, s["session_id"])
            task_links.link(s["gatherer"], key, s["session_id"])     # in one task, if its app is in none
        except Exception:  # noqa: BLE001 - one actor's trouble is not the others'
            pass


def start(started: "sessions.Sessions", host, app: str, gatherer: str, cwd: str, harness: str,
          model: Optional[str] = None, name: Optional[str] = None) -> Tuple[dict, Instance]:
    """A new instance of `app` and a new actor working with it (module doc)."""
    m = host.hosted(app).manifest
    if not m.agent.start:
        raise AppError(f"{m.label} starts no agent of its own: open it, and attach an actor to it")
    cwd = os.path.realpath(os.path.abspath(os.path.expanduser((cwd or "").strip() or ".")))
    if not os.path.isdir(cwd):
        raise AppError(f"no directory {cwd}")
    inst = host.open(app, gatherer, cwd, {}, by="user")
    try:
        s = started.create(gatherer, cwd, "auto", harness, model, role=role(app, inst.id))
    except sessions.SessionError as exc:
        host.close_instance(gatherer, inst.id)
        raise AppError(str(exc)) from None
    task_links.link(gatherer, inst.id, s["session_id"])                # the app and its agent: one task
    host.attach(gatherer, inst.id, s["session_id"])
    said = name or m.agent.name.format(app=m.label, folder=os.path.basename(cwd.rstrip("/")) or cwd)
    threading.Thread(target=_name, args=(gatherer, s["session_id"], said), name=f"ag-{app}-name",
                     daemon=True).start()
    return s, inst


class Messenger:
    """An app's messages to its agents (app_host.py's `send_agent`, `start_agent`): typed into the agent's terminal as
    Chat sends a message (sessions.py's `send`), the terminal opened and the agent started if they are not."""

    def __init__(self, started: "sessions.Sessions"):
        self.started = started

    def send(self, gatherer: str, channel: str, text: str) -> None:
        row = next((r for r in self.started.list() if r["session_id"] == channel), None)
        if row is None:                                      # not started here: taken into the table first
            try:
                row = self.started.adopt(gatherer, channel)
            except sessions.SessionError as exc:
                raise AppError(f"{channel}: {exc}", 404) from None
        rules = harness_kit.get(row.get("harness"))
        try:
            self.started.send(row["session_id"], text, fullscreen=bool(rules is None or rules.fullscreen))
        except sessions.NotAtBox:
            raise AppError("its terminal can't take a message now: a dialog or a question is open in it, or "
                           "something is typed there and not sent. Nothing was typed; try again later.", 409) from None
        except sessions.SessionError as exc:
            raise AppError(str(exc), 409) from None

    def start(self, host, instance: Instance, text: str, name: str, harness: Optional[str], model: Optional[str],
              cwd: str) -> str:
        harness = harness or harness_kit.DEFAULT
        if harness not in sessions.HARNESSES:
            raise AppError(f"harness {harness!r}: one of {', '.join(sessions.HARNESSES)}")
        try:
            s = self.started.create(instance.gatherer, cwd, "auto", harness, model, role=role(instance.app, instance.id))
        except sessions.SessionError as exc:
            raise AppError(str(exc)) from None
        task_links.link(instance.gatherer, instance.id, s["session_id"])   # the app and its agent: one task
        host.attach(instance.gatherer, instance.id, s["session_id"], by="app")
        threading.Thread(target=_name, args=(instance.gatherer, s["session_id"], name),
                         name=f"ag-{instance.app}-name", daemon=True).start()
        self.send(instance.gatherer, s["session_id"], text)
        return s["session_id"]


def _name(gatherer: str, sid: str, said: str) -> None:
    """The new actor named `said` once its gatherer has it (its first call): a name is an event there (naming.py) --
    else the list shows it by its first message, which an app's page may have written."""
    end = time.time() + NAME_WAIT
    while time.time() < end and not sessions._has_calls(gatherer, sid):
        time.sleep(2)
    try:
        naming.record(gatherer, sid, said)
    except naming.NamingError:
        pass
