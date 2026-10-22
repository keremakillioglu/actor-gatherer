"""Claude Code's launcher, ClaudeLauncher, for `ag claude ...`: Claude Code, its Anthropic API pointed at a
hook server that calls the context manager (its setup, setup.py), for this run only:

    ANTHROPIC_BASE_URL = "http://127.0.0.1:<port>[/h/<gatherer>][/l/<limit>]<path>"

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

Claude Code keeps its own automatic compaction; the run states where it compacts (`/l/<limit>`),
for the context manager to keep under (`harness_limit`): its auto-compact window less the
auto-compact buffer it keeps, as Claude Code itself reports them -- `/context` in print mode, a
local command that calls no model, run with the run's model and auto-compact flags and
environment (`probe`). When that cannot be asked, Claude Code's documented rules stand in
(`documented`): the model (`--model`, else ANTHROPIC_MODEL, else settings.json `model` in
$CLAUDE_CONFIG_DIR or ~/.claude) has CLAUDE_CODE_MAX_CONTEXT_TOKENS, else 1M for a `[1m]` model
or a native 1M one (unless CLAUDE_CODE_DISABLE_1M_CONTEXT), else 200K; an auto-compact window
set and smaller replaces it (CLAUDE_CODE_AUTO_COMPACT_WINDOW, `--autocompact`, the settings'
`modelSettings.<model>.autoCompactWindow`, `autoCompactWindow`, first found); less BUFFER.
CLAUDE_AUTOCOMPACT_PCT_OVERRIDE, which `/context` does not show, lowers it further. A model
switched to inside the session is not followed.
"""

import json
import os
import re
import subprocess
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from ag.cli.launch import Launch, Launcher, LaunchError, Run
from .hook_servers import HookServers

SETUP = "ag.integrations.harnesses.claude.setup.setup"     # Claude Code's setup: the hook server with its hook
DEFAULT_API = "https://api.anthropic.com"
FIRST_PARTY = ("api.anthropic.com",)                    # hosts Claude Code's tool search works with
SESSION_HEADER = "x-claude-code-session-id"             # the trace files each call under its session
WINDOW, WINDOW_1M = 200_000, 1_000_000                  # Claude Code's windows: the default, and extended
BUFFER = 33_000                                         # the auto-compact buffer Claude Code keeps below its window
NATIVE_1M = re.compile(r"fable|sonnet-(?:[5-9]|\d{2,})|haiku-(?:5-5|[6-9]|\d{2,})|opus-(?:4-(?:[7-9]|\d{2,})|[5-9]|\d{2,})"
                       r"|^(?:opus|sonnet|haiku|fable)$")    # the aliases name the newest, native 1M


def upstream_of(settings: Dict[str, Any], env: Dict[str, str]):
    """(origin, path) of where Claude Code's requests go without ag."""
    url = str(settings.get("upstream") or env.get("ANTHROPIC_BASE_URL") or DEFAULT_API)
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise LaunchError(f"Claude Code's API is at {url}, which ag cannot relay to")
    return f"{parts.scheme}://{parts.netloc}", parts.path.rstrip("/")


def base_url(server_url: str, gatherer: Optional[str], path: str, limit: Optional[int] = None) -> str:
    return server_url + (f"/h/{gatherer}" if gatherer else "") + (f"/l/{limit}" if limit else "") + path


def tokens(value: Any, thousands: bool = False) -> Optional[int]:
    """A token count as Claude Code takes one: a number, or "200k", "1M"; with `thousands`
    (a flag's or a command's value), a bare 100-1000 is thousands. None if it is none."""
    text = str(value).strip().lower() if value is not None else ""
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*([km]?)", text)
    if not match:
        return None
    n = float(match.group(1)) * {"": 1, "k": 1_000, "m": 1_000_000}[match.group(2)]
    if thousands and not match.group(2) and 100 <= n <= 1000:
        n *= 1000
    return int(n) or None


def flag(args: List[str], name: str) -> Optional[str]:
    """The value of `--name v` or `--name=v` in the arguments, the last one given."""
    found = None
    for i, a in enumerate(args):
        if a == "--":
            break
        if a == name and i + 1 < len(args):
            found = args[i + 1]
        elif a.startswith(name + "="):
            found = a[len(name) + 1:]
    return found


def claude_settings(env: Dict[str, str]) -> Dict[str, Any]:
    """Claude Code's user settings.json, {} if there is none to read."""
    path = os.path.join(os.path.expanduser(env.get("CLAUDE_CONFIG_DIR") or "~/.claude"), "settings.json")
    try:
        with open(path, encoding="utf-8") as fh:
            found = json.load(fh)
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


CONTEXT_TOKENS = re.compile(r"\*\*Tokens:\*\*\s*[0-9.]+\s*[km]?\s*/\s*([0-9.]+\s*[km]?)", re.I)
CONTEXT_BUFFER = re.compile(r"^\|\s*Autocompact buffer\s*\|\s*([0-9.]+\s*[km]?)\s*\|", re.I | re.M)
DEAD_API = "http://127.0.0.1:9"       # where the probe's Claude Code would call the model: nothing answers
PROBED_FLAGS = ("--model", "--autocompact", "--settings", "--setting-sources")


def context_of(text: str) -> Optional[Tuple[int, Optional[int]]]:
    """(the window, the auto-compact buffer or None when none is shown) from Claude Code's
    `/context` report; None if it is not one."""
    window = CONTEXT_TOKENS.search(text)
    if not window or not tokens(window.group(1).replace(" ", "")):
        return None
    buffer = CONTEXT_BUFFER.search(text)
    return tokens(window.group(1).replace(" ", "")), tokens(buffer.group(1).replace(" ", "")) if buffer else None


def probe(command: List[str], args: List[str], env: Dict[str, str]) -> Optional[Tuple[int, Optional[int]]]:
    """Ask Claude Code itself: `/context` in print mode, a local command that calls no model, with the
    run's model and auto-compact flags and its environment, its API pointed at an address nothing
    answers (DEAD_API) and its session not kept. (window, buffer) as `context_of`, or None."""
    given = [x for name in PROBED_FLAGS if flag(args, name) is not None for x in (name, flag(args, name))]
    try:
        done = subprocess.run([*command, "-p", "/context", "--no-session-persistence", "--strict-mcp-config", *given],
                              env={**os.environ, **env, "ANTHROPIC_BASE_URL": DEAD_API}, capture_output=True,
                              text=True, timeout=60, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    return context_of(done.stdout) if done.returncode == 0 else None


def documented(args: List[str], env: Dict[str, str], settings: Dict[str, Any]) -> Tuple[int, str]:
    """(the auto-compact window, how that was found) by Claude Code's documented rules, for when
    `/context` cannot be asked: the model's window, else the auto-compact window when one is set
    and smaller."""
    model = flag(args, "--model") or env.get("ANTHROPIC_MODEL") or settings.get("model")
    model = str(model).strip() if model else ""
    plain = model.lower().replace("[1m]", "")
    native = bool(plain and NATIVE_1M.search(plain)) and not env.get("CLAUDE_CODE_DISABLE_1M_CONTEXT")
    if tokens(env.get("CLAUDE_CODE_MAX_CONTEXT_TOKENS")):
        window, source = tokens(env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"]), "CLAUDE_CODE_MAX_CONTEXT_TOKENS"
    elif "[1m]" in model.lower() or native:
        window, source = WINDOW_1M, f"{model}'s 1M window"
    else:
        window = WINDOW
        source = f"{model}'s 200K window" if model else "the 200K window (no model named)"
    per_model = ((settings.get("modelSettings") or {}).get(model) or {}).get("autoCompactWindow") if model else None
    for value, thousands, name in ((env.get("CLAUDE_CODE_AUTO_COMPACT_WINDOW"), False, "CLAUDE_CODE_AUTO_COMPACT_WINDOW"),
                                   (flag(args, "--autocompact"), True, "--autocompact"),
                                   (per_model, False, f"modelSettings.{model}.autoCompactWindow"),
                                   (settings.get("autoCompactWindow"), False, "autoCompactWindow")):
        if tokens(value, thousands):
            return min(tokens(value, thousands), window), f"{name} (window {window})"
    return window, source


def harness_limit(args: List[str], env: Dict[str, str], settings: Dict[str, Any],
                  asked: Optional[Callable[[], Optional[Tuple[int, Optional[int]]]]] = None) -> Tuple[int, str]:
    """(where Claude Code compacts by itself in this run, how that was found): its auto-compact
    window less its auto-compact buffer, both as `/context` reports them (`asked`, the probe),
    else by the documented rules less BUFFER; then CLAUDE_AUTOCOMPACT_PCT_OVERRIDE percent of the
    window, when lower (`/context` does not show it)."""
    found = asked() if asked else None
    if found:
        window, buffer = found
        source = f"Claude Code's /context: window {window}, auto-compact buffer " + \
            (f"{buffer}" if buffer else f"none shown, {BUFFER} assumed")
    else:
        window, source = documented(args, env, settings)
        buffer, source = None, f"{source}, less the {BUFFER} buffer (/context could not be asked)"
    at = window - (buffer or BUFFER)
    percent = tokens(env.get("CLAUDE_AUTOCOMPACT_PCT_OVERRIDE"))
    if percent and percent < 100 and window * percent // 100 < at:
        at, source = window * percent // 100, f"CLAUDE_AUTOCOMPACT_PCT_OVERRIDE={percent} of {window}; {source}"
    return at, source


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
        command = list(run.command)
        limit, how = harness_limit(run.args, run.env, claude_settings(run.env),
                                   lambda: probe(command, run.args, run.env))
        url = base_url(server_url, run.gatherer, path, limit)
        notes.append(f"ANTHROPIC_BASE_URL={url} -> {origin}{path}")
        notes.append(f"Claude Code's own limit: {limit} tokens, {how}; the context manager keeps under it")
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
