"""What the reader chose for each app on the Apps page (features/apps/catalog.ts): for an app that can have an agent of
its own (its manifest's [agent] offered), whether opening it -- its one entry in a group's "+ ⋯" menu, a new tab's
"Or open", the Apps page's Open -- starts it with one (a new actor attached to it, app_agents.py's `start`) or on its own.

    opens_with_agent(m)     for manifest `m`: True when it opens with an agent of its own -- the reader's choice, else
                            yes (an app that offers one is mostly used with it); False for an app that offers none
    choose(name, agent)     the reader's choice for app `name`, kept

Kept in <home>/dashboard/app_settings.json, {name: {"agent": bool}}: a file of the dashboard's own, not events -- the
choice is an app's, in no one gatherer, and every page (a browser's, the desktop app's) reads the same. An app
uninstalled keeps its line, for when it is installed again."""

import json
import os
import threading
from typing import Dict

from . import home

_lock = threading.Lock()


def path() -> str:
    return os.path.join(home.HOME, "dashboard", "app_settings.json")


def _read() -> Dict[str, dict]:
    try:
        with open(path(), encoding="utf-8") as fh:
            got = json.load(fh)
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in got.items() if isinstance(v, dict)} if isinstance(got, dict) else {}


def opens_with_agent(m) -> bool:
    """Whether app manifest `m`, opened from a menu, starts with an agent of its own."""
    if not m.agent.offered:
        return False
    agent = _read().get(m.name, {}).get("agent")
    return agent if isinstance(agent, bool) else True


def choose(name: str, agent: bool) -> Dict[str, bool]:
    """App `name` opened with an agent of its own (`agent`), or on its own, from now on -> {agent}."""
    with _lock:
        got = _read()
        got.setdefault(name, {})["agent"] = bool(agent)
        os.makedirs(os.path.dirname(path()), exist_ok=True)
        tmp = path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(got, fh, indent=1, sort_keys=True)
        os.replace(tmp, path())
    return {"agent": bool(agent)}
