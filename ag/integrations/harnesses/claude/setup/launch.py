"""Claude Code's launcher, ClaudeLauncher, for `ag claude ...`: Claude Code, its Anthropic API pointed at a
hook server that calls the context manager (its setup, setup.py), for this run only:

    ANTHROPIC_BASE_URL = "http://127.0.0.1:<port>[/h/<gatherer>]<path>"

The hook server relays to where Claude Code would have gone: the `upstream` setting, else
ANTHROPIC_BASE_URL as the environment has it, else https://api.anthropic.com. Its key or login, its
headers, the model and everything else stay as they were; nothing is written to Claude Code's settings.
Each Claude Code session is a channel in the run's gatherer.

When the upstream is Anthropic's own API, ag also sets ENABLE_TOOL_SEARCH=true (unless the environment
sets it): Claude Code turns tool search off for a base URL that is not a first-party host, and then
sends every tool in full on every call, which breaks the cache.

`system_messages` ("keep" or "user") forces how the hook sends system messages back for every request;
unset, the hook chooses by each request's model. `trace_root` traces every model call there (the
request as the model got it, and its answer), each under its Claude Code session; `log_dir` keeps the
requests the hook changed, before and after.
"""

import os
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

from ag.cli.launch import Launch, Launcher, LaunchError, Run
from .hook_servers import HookServers

SETUP = "ag.integrations.harnesses.claude.setup.setup"     # Claude Code's setup: the hook server with its hook
DEFAULT_API = "https://api.anthropic.com"
FIRST_PARTY = ("api.anthropic.com",)                    # hosts Claude Code's tool search works with
SESSION_HEADER = "x-claude-code-session-id"             # the trace files each call under its session


def upstream_of(settings: Dict[str, Any], env: Dict[str, str]):
    """(origin, path) of where Claude Code's requests go without ag."""
    url = str(settings.get("upstream") or env.get("ANTHROPIC_BASE_URL") or DEFAULT_API)
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise LaunchError(f"Claude Code's API is at {url}, which ag cannot relay to")
    return f"{parts.scheme}://{parts.netloc}", parts.path.rstrip("/")


def base_url(server_url: str, gatherer: Optional[str], path: str) -> str:
    return server_url + (f"/h/{gatherer}" if gatherer else "") + path


class ClaudeLauncher(Launcher):
    defaults = {"command": ["claude"], "upstream": "", "port": 4113, "log_dir": "", "trace_root": "", "system_messages": "", "env": {}}

    def __init__(self, settings: Dict[str, Any], home: str):
        super().__init__(settings, home)
        self.servers = HookServers(home)

    def launch(self, run: Run) -> Launch:
        """Claude Code, ANTHROPIC_BASE_URL pointed at the hook server -- started if none with its upstream
        is running (not in a dry run)."""
        origin, path = upstream_of(self.settings, run.env)
        log_dir = os.path.expanduser(str(self.settings.get("log_dir") or ""))
        trace_root = os.path.expanduser(str(self.settings.get("trace_root") or ""))
        port = int(self.settings["port"])
        options = {"adaptor": run.adaptor} if run.adaptor else {}
        first_party = urlsplit(origin).hostname in FIRST_PARTY
        if self.settings.get("system_messages"):            # else the hook's own: by the request's model
            options["system_messages"] = str(self.settings["system_messages"])
        notes = [f"model trace: {trace_root}"] if trace_root else []
        if run.dry_run:
            found = self.servers.find(SETUP, origin, log_dir, options, trace_root)
            server_url = found.url if found else f"http://127.0.0.1:{port}"
            notes.append(f"hook server: {server_url}{'' if found else ' (not started: dry run)'} -> {origin}")
        else:
            if any(origin == s.url for s in self.servers.running()):
                raise LaunchError(f"Claude Code's API already points at a hook server ag started ({origin}); "
                                  f"run Claude Code through ag with its own API address")
            try:
                server_url = self.servers.start(SETUP, origin, port, log_dir, options, trace_root=trace_root,
                                                thread_headers=(SESSION_HEADER,)).url
            except RuntimeError as exc:
                raise LaunchError(str(exc)) from exc
        url = base_url(server_url, run.gatherer, path)
        notes.append(f"ANTHROPIC_BASE_URL={url} -> {origin}{path}")
        if options.get("system_messages"):
            notes.append(f"system messages: {options['system_messages']} (the system_messages setting)")
        env = {**run.env, "ANTHROPIC_BASE_URL": url}
        if first_party and "ENABLE_TOOL_SEARCH" not in run.env:
            env["ENABLE_TOOL_SEARCH"] = "true"
            notes.append("ENABLE_TOOL_SEARCH=true (the hook server forwards to Anthropic's API)")
        return Launch([*run.command, *run.args], env, notes)

    def describe(self, env: Dict[str, str]) -> List[str]:
        try:
            origin, path = upstream_of(self.settings, env)
        except LaunchError as exc:
            return [f"API: {exc}"]
        return [f"API: {origin}{path}"]

    def status(self) -> List[str]:
        """The hook servers ag started, one line each."""
        return [f"hook server :{s.port}  pid {s.pid}  -> {s.upstream}"
                + (f"  logs {s.log_dir}" if s.log_dir else "")
                + f"  output {self.servers.log(s.port)}"
                for s in self.servers.running()]

    def stop(self) -> List[str]:
        """Stop the hook servers ag started."""
        stopped = []
        for s in self.servers.running():
            self.servers.stop(s)
            stopped.append(f"stopped the hook server :{s.port} (-> {s.upstream})")
        return stopped
