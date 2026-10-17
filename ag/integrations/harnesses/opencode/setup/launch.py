"""opencode's launcher, OpencodeLauncher, for `ag opencode ...`: opencode, with the context manager's plugin
(ag/integrations/harnesses/opencode/setup/setup.ts) added for this run through
OPENCODE_CONFIG_CONTENT, a config opencode merges over its own -- its other
plugins, its configs and their files stay as they are. opencode drops a
plugin named twice, keeping the last -- this one, merged after your global
and project configs -- so a config that loads this one already is no matter
(though options given it there give way to ag's). The gatherer is the
plugin's `gatherer` option.
An OPENCODE_CONFIG_CONTENT of your own is kept, the plugin added to it.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional

from ag.cli.launch import Launch, Launcher, LaunchError, Run

PLUGIN = Path(__file__).resolve().with_name("setup.ts").as_uri()     # opencode's setup


def config_content(existing: str = "", gatherer: Optional[str] = None) -> str:
    """OPENCODE_CONFIG_CONTENT: the one given (if any), with the plugin -- and
    the gatherer as its `gatherer` option."""
    try:
        cfg = json.loads(existing) if existing.strip() else {}
    except ValueError as exc:
        raise LaunchError(f"OPENCODE_CONFIG_CONTENT is not JSON ag can add to: {exc}") from exc
    if not isinstance(cfg, dict):
        raise LaunchError("OPENCODE_CONFIG_CONTENT is not a JSON object")
    plugins = [p for p in cfg.get("plugin") or [] if (p[0] if isinstance(p, list) and p else p) != PLUGIN]
    plugins.append([PLUGIN, {"gatherer": gatherer}] if gatherer else PLUGIN)
    return json.dumps({**cfg, "plugin": plugins})


class OpencodeLauncher(Launcher):
    defaults = {"command": ["opencode"], "env": {}}
    environment = (("AG_OPENCODE_TIMEOUT_MS", "300000", "How long a model call waits for the Gatherer."),
                   ("AG_OPENCODE_COMPACTION", "off", "`allow`: keep OpenCode's own compaction on."))

    def launch(self, run: Run) -> Launch:
        given = run.env.get("OPENCODE_CONFIG_CONTENT", "")
        env = {**run.env, "OPENCODE_CONFIG_CONTENT": config_content(given, run.gatherer)}
        if run.adaptor:
            env["AG_ADAPTOR"] = run.adaptor                                           # setup.ts loads it
        return Launch([*run.command, *run.args], env)

    def describe(self, env: Dict[str, str]) -> List[str]:
        return [f"plugin: {PLUGIN} (OPENCODE_CONFIG_CONTENT)"]
