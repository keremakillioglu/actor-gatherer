"""agapps: the dashboard's apps, from an agent's own Python -- the same tools its harness gives it (MCP's `<app>_<tool>`)
and `ag apps call` runs, called from a script, so it can loop over them and keep what it reads out of its context.

    import agapps
    notes = agapps.app("notes")              # an app, by its name
    pages = notes.read()                     # its tool `read`: notes_read, with these arguments as keywords
    notes.add(page="To dos", markdown="- [ ] call Maya")
    agapps.mine()                            # the app instances you may use now, and why
    agapps.installed()                       # every app installed, and who may use it
    agapps.about("notes")                    # an app's instructions and its tools, with what each takes
    agapps.tasks()                           # the dashboard's folders, tasks, actors and apps (`ag tasks`)
    agapps.call("notes_read", {"page": "To dos"})   # any tool, by its full name

Every call goes to the dashboard that runs you, which checks it as it checks a tool call: you may use an app's instance
when it is in your task -- or, for an app every agent of your group shares, always -- and a refusal says why. Give
`instance=` (to `app` or to a call) when you may use more than one of an app's instances.

What a call returns: its text; a JSON object or list, parsed, when its text is one; a picture as an `Image` (`.save`
it to look at it); several parts, a list of them. A refusal or a failed call raises `AppError`, its text the reason.

Who calls is the session the script runs in, as its harness says (CLAUDE_CODE_SESSION_ID, CODEX_THREAD_ID), else
AG_ACTOR (which the dashboard sets in the sessions it starts). The dashboard is AG_DASHBOARD's, else the one the home
names (<home>/dashboard/address.json). ag puts this file's folder on PYTHONPATH in every session it starts.

Standard library only, and Python 3.8 on: it runs in whatever Python an agent's script runs in, not ag's."""

import base64
import errno
import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

__all__ = ["AppError", "Image", "App", "app", "call", "mine", "installed", "about", "tasks"]

#: The asker's id: its harness's session, else the one the dashboard started it under (ag/cli/actors.py's).
ACTOR_VARS = ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "AG_ACTOR")
DASHBOARD_VAR = "AG_DASHBOARD"
TIMEOUT = 120.0                 # seconds a call is waited for: a tool its panel answers waits for an open panel
#: A connection refused by the sandbox the script runs in, not by the dashboard (macOS's seatbelt and Linux's seccomp,
#: as Codex runs commands: no network, even to this machine).
SANDBOXED = (errno.EPERM, errno.EACCES)


class AppError(Exception):
    """A call refused by the dashboard (you may not use that instance, no such tool, ...) or failed in its app: `str()`
    of it is what the dashboard or the app said."""


class Image(object):
    """A picture a tool returned: its media type and bytes."""

    def __init__(self, mime_type: str, data: bytes):
        self.mime_type = mime_type
        self.data = data

    def save(self, path: str) -> str:
        """Written to `path` (a folder: a file named for it there); the path written."""
        if os.path.isdir(path):
            path = os.path.join(path, "picture." + (self.mime_type.split("/")[-1] or "png"))
        with open(path, "wb") as fh:
            fh.write(self.data)
        return path

    def __repr__(self) -> str:
        return "<Image {} {} bytes>".format(self.mime_type, len(self.data))


def actor() -> Optional[str]:
    """The id of the session this runs in, as the dashboard knows it; None outside one."""
    return next((os.environ[v] for v in ACTOR_VARS if os.environ.get(v)), None)


def dashboard() -> Optional[str]:
    """The address of the dashboard that runs this session; None if there is none."""
    if os.environ.get(DASHBOARD_VAR):
        return os.environ[DASHBOARD_VAR].rstrip("/")
    home = os.path.abspath(os.path.expanduser(os.environ.get("AG_HOME") or "~/.ag"))
    try:
        with open(os.path.join(home, "dashboard", "address.json"), encoding="utf-8") as fh:
            return str(json.load(fh)["url"]).rstrip("/")
    except (OSError, ValueError, KeyError, TypeError):
        return None


def call(tool: str, args: Optional[Dict[str, Any]] = None, /, *, instance: Optional[str] = None,
         raw: bool = False, timeout: float = TIMEOUT, **kwargs: Any) -> Any:
    """A tool called by its full name (`notes_read`; `apps_mine`), its arguments as `args` and/or keywords; `instance`,
    which one of the app's. Its answer as the module's doc says (`raw`: the result as MCP gives it, errors and all).
    `instance`, `raw` and `timeout` are this function's own: a tool's argument of one of those names goes in `args`."""
    who, url = actor(), dashboard()
    if not who:
        raise AppError("not run by an actor: agapps calls the apps as the session it runs in "
                       "({}, or AG_ACTOR)".format(", ".join(ACTOR_VARS[:2])))
    if not url:
        raise AppError("no dashboard runs on this home: the apps are the dashboard's (`ag dashboard`)")
    sent = dict(args or {}, **kwargs)
    if instance:
        sent["instance"] = instance
    got = _post(url + "/api/apps/agent/call", {"actor": who, "tool": tool, "args": sent}, timeout)
    if raw:
        return got
    parts = [_part(p) for p in got.get("content") or []]
    if got.get("isError"):
        raise AppError("\n".join(p for p in parts if isinstance(p, str)) or "{} failed".format(tool))
    if not parts:
        return None
    return parts[0] if len(parts) == 1 else parts


class App(object):
    """An app, by its name: each of its tools a method -- `app("notes").read(page="To dos")` calls notes_read. A tool
    whose name is not one Python can write after a dot, by `.call("<tool>", ...)`."""

    def __init__(self, name: str, instance: Optional[str] = None):
        self.name = name
        self.instance = instance

    def call(self, tool: str, args: Optional[Dict[str, Any]] = None, /, **kwargs: Any) -> Any:
        kwargs.setdefault("instance", self.instance)
        return call("{}_{}".format(self.name, tool), args, **kwargs)

    def __getattr__(self, tool: str) -> Any:
        if tool.startswith("_"):
            raise AttributeError(tool)
        return lambda args=None, /, **kwargs: self.call(tool, args, **kwargs)

    def __repr__(self) -> str:
        return "<App {}{}>".format(self.name, " instance " + self.instance if self.instance else "")


def app(name: str, instance: Optional[str] = None) -> App:
    """The app `name` (as `installed()` lists it), its tools as methods; `instance`, which one of its, when you may use
    more than one."""
    return App(name, instance)


def mine() -> str:
    """The app instances you may use now, and why (your task, your group, ...)."""
    return call("apps_mine")


def installed() -> str:
    """Every app installed, and who may use it."""
    return call("apps_list")


def about(name: str) -> str:
    """An app's instructions and its tools, with what each takes."""
    return call("apps_help", {"app": name})


def tasks(path: str = "") -> str:
    """The dashboard's folders, tasks, actors and apps at `path` (none: the top), walked like a directory."""
    return call("dashboard_ls", {"path": path} if path else {})


def _part(p: Dict[str, Any]) -> Any:
    if p.get("type") == "text":
        text = p.get("text") or ""
        if text[:1] in "{[":
            try:
                return json.loads(text)
            except ValueError:
                pass
        return text
    if p.get("type") == "image":
        return Image(p.get("mimeType") or "image/png", base64.b64decode(p.get("data") or ""))
    return p


def _post(url: str, body: Dict[str, Any], timeout: float) -> Dict[str, Any]:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            said = json.loads(exc.read()).get("error")
        except ValueError:
            said = None
        raise AppError(said or "the dashboard answered {}".format(exc.code)) from None
    except (urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        if getattr(reason, "errno", None) in SANDBOXED:
            raise AppError("a sandbox keeps this script from reaching the dashboard at {} ({}): run it again outside "
                           "the sandbox -- in Codex, with sandbox_permissions \"require_escalated\" -- as it only talks "
                           "to the dashboard on this machine".format(url, reason)) from None
        raise AppError("no dashboard answers at {} ({})".format(url, reason)) from None

