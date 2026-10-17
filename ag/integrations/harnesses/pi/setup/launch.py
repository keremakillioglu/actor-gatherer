"""pi's launcher, PiLauncher, for `ag pi ...`: pi, with the context manager's extension (ag/integrations/harnesses/pi/setup/setup.ts)
loaded for this run by `-e` -- pi's settings, its other extensions and
packages, stay as they are.

When pi's settings already install this package (the global
<agent dir>/settings.json, PI_CODING_AGENT_DIR or ~/.pi/agent, or the
project's .pi/settings.json), pi loads the extension itself and `-e` is left
out, so it is not loaded twice; pi without ag then runs the context manager
too (`pi remove <this clone>` undoes that).

The gatherer is given by the extension's own flag, `--ag-gatherer NAME`.
pi's own package commands (install, remove, update, list, config) run as
they are.
"""

import json
import os
from typing import Any, Dict, List, Optional

from ag.cli.launch import REPO, Launch, Launcher, Run

EXTENSION = os.path.join(os.path.dirname(os.path.abspath(__file__)), "setup.ts")   # pi's setup
COMMANDS = ("install", "remove", "update", "list", "config")
REMOTE = ("npm:", "git:", "http://", "https://", "ssh://", "git@")


def settings_files(cwd: str, env: Dict[str, str]) -> List[str]:
    agent = os.path.expanduser(env.get("PI_CODING_AGENT_DIR") or "~/.pi/agent")
    return [os.path.join(agent, "settings.json"), os.path.join(cwd, ".pi", "settings.json")]


def _same(path: str, base: str, target: str) -> bool:
    full = os.path.join(base, os.path.expanduser(path))
    return os.path.realpath(full) == os.path.realpath(target)


def installed_in(cwd: str, env: Dict[str, str]) -> Optional[str]:
    """The settings file that installs this package (or its extension), if any."""
    for settings in settings_files(cwd, env):
        try:
            with open(settings, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        base = os.path.dirname(settings)
        for entry in data.get("packages") or []:
            source = entry.get("source") if isinstance(entry, dict) else entry
            if isinstance(source, str) and not source.startswith(REMOTE) and _same(source, base, REPO):
                return settings
        for entry in data.get("extensions") or []:
            if isinstance(entry, str) and _same(entry, base, EXTENSION):
                return settings
    return None


def argv(command: List[str], args: List[str], cwd: str, env: Dict[str, str],
         gatherer: Optional[str] = None) -> List[str]:
    """pi's command: the extension by -e (unless pi's settings install it), the
    gatherer by the extension's own --ag-gatherer."""
    if args and args[0] in COMMANDS:
        return [*command, *args]
    extension = [] if installed_in(cwd, env) else ["-e", EXTENSION]
    return [*command, *extension, *(["--ag-gatherer", gatherer] if gatherer else []), *args]


class PiLauncher(Launcher):
    defaults = {"command": ["pi"], "env": {}}
    environment = (("AG_PI_TIMEOUT_MS", "300000", "How long a model call waits for the Gatherer."),
                   ("AG_PI_COMPACTION", "off", "`allow`: keep Pi's own compaction on."))

    def launch(self, run: Run) -> Launch:
        notes = []
        if not (run.args and run.args[0] in COMMANDS):
            where = installed_in(run.cwd, run.env)
            if where:
                notes.append(f"the extension is installed by {where}; pi loads it itself")
        env = {**run.env, "AG_ADAPTOR": run.adaptor} if run.adaptor else run.env      # setup.ts loads it
        return Launch(argv(run.command, run.args, run.cwd, run.env, run.gatherer), env, notes)

    def describe(self, env: Dict[str, str]) -> List[str]:
        where = installed_in(os.getcwd(), env)
        return [f"extension: {'installed by ' + where + ' (pi without ag runs it too)' if where else 'added by -e'}"]
