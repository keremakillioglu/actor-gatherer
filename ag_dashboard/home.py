"""Where the dashboard reads from: the context manager's home (AG_HOME, default ~/.ag), as ag
lays it out -- the dashboard's only knowledge of ag, which it never imports:

    gatherers/<gatherer>/context.db      the gatherer's database (read-only)
    gatherers/<gatherer>/gatherer.toml   its config: the policy
    logs/llm/*.json                      the Gatherer's model calls, one file each
    hook_server/<port>.json              each hook server ag started: pid, port, upstream

HOME is a module attribute, so a test (or `--home`) can point it elsewhere."""

import json
import os
import re
from typing import List

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


def _alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
    except (ProcessLookupError, ValueError, TypeError):
        return False
    except PermissionError:
        return True
    return True


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
