"""Where the dashboard reads from: the context manager's home (AG_HOME, default ~/.ag), as ag
lays it out -- the dashboard's only knowledge of ag, which it never imports:

    gatherers/<gatherer>/context.db      the gatherer's database (read-only)
    gatherers/<gatherer>/gatherer.toml   its config: the policy
    logs/llm/*.json                      the Gatherer's model calls, one file each
    hook_server/<port>.json              each hook server ag started: pid, port, upstream

and the dashboard's own, beside them:

    dashboard/views/*.js                 the reader's own chat views, which the page loads

and, of each read, the harness's process that made the call (`_reads.pid`, `pid_started`: the
boot's id and the process's start in clock ticks, as /proc gives them), to tell whether it runs.

HOME is a module attribute, so a test (or `--home`) can point it elsewhere."""

import json
import os
import re
from typing import List, Optional

HOME = os.path.abspath(os.path.expanduser(os.environ.get("AG_HOME") or "~/.ag"))

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def gatherers_dir() -> str:
    return os.path.join(HOME, "gatherers")


def gatherer_dir(gatherer: str) -> str:
    """The gatherer's directory: unsafe characters in its name become `_`, as ag names it."""
    key = _UNSAFE.sub("_", (gatherer or "").strip())
    return os.path.join(gatherers_dir(), "unknown" if key in ("", ".", "..") else key)


def db_path(gatherer: str) -> str:
    return os.path.join(gatherer_dir(gatherer), "context.db")


def llm_log_dir() -> str:
    return os.path.join(HOME, "logs", "llm")


VIEW_FILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\.js")


def views_dir() -> str:
    return os.path.join(HOME, "dashboard", "views")


def view_names() -> List[str]:
    """The reader's own chat views: the .js files in views_dir(), by name; [] when there is none."""
    d = views_dir()
    return sorted(n for n in os.listdir(d) if VIEW_FILE.fullmatch(n) and os.path.isfile(os.path.join(d, n))) \
        if os.path.isdir(d) else []


def view_file(name: str) -> Optional[str]:
    """The path of the view named `name`, None when it is not one of view_names() (no other path is served)."""
    return os.path.join(views_dir(), name) if name in view_names() else None


def _alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
    except (ProcessLookupError, ValueError, TypeError):
        return False
    except PermissionError:
        return True
    return True


def _boot_id() -> Optional[str]:
    try:
        with open("/proc/sys/kernel/random/boot_id", encoding="ascii") as fh:
            return fh.read().strip()
    except OSError:
        return None


def process_alive(pid, started) -> Optional[bool]:
    """Whether the process ag recorded -- `pid`, started at `started` ("<boot id>:<start ticks>") --
    still runs: False when no process has that pid, or a later one does (another start, another
    boot); None when it cannot be told (nothing recorded, no /proc)."""
    if not isinstance(pid, int) or not isinstance(started, str) or not os.path.isdir("/proc"):
        return None
    try:
        with open(f"/proc/{pid}/stat", encoding="ascii", errors="replace") as fh:
            fields = fh.read().rsplit(")", 1)[-1].split()
    except OSError:
        return False
    boot = _boot_id()
    if boot is None or len(fields) < 20:
        return None
    return started == f"{boot}:{fields[19]}"


def hook_servers() -> List[dict]:
    """The hook servers ag started that are still running: {port, pid, upstream}. Their records
    are only read: a dead one's is left for ag to remove."""
    d = os.path.join(HOME, "hook_server")
    found = []
    for name in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(d, name), encoding="utf-8") as fh:
                s = json.load(fh)
        except (OSError, ValueError):
            continue
        if isinstance(s, dict) and _alive(s.get("pid")):
            found.append({"port": s.get("port"), "pid": s.get("pid"), "upstream": s.get("upstream")})
    return found
