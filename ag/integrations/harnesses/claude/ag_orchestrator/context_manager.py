"""The context manager as Claude Code's hook. Claude Code has no hook that can replace what it sends
its model; the hook server (ag/integrations/tools/hook_server/hook_server.py) gives it one, and calls
this on every request Claude Code sends its ANTHROPIC_BASE_URL; setup/setup.py sets that up. It is given a request -- anything
with `method`, `path`, `label`, `headers` and `body` -- and returns the request body with the context
manager's context as its `messages`, or None to leave the request as it is.

    python -m ag.integrations.tools.hook_server.hook_server --hook ag.integrations.harnesses.claude.ag_orchestrator.context_manager:ClaudeContextManager [--option cwd=DIR ...]

What it decides, Claude Code's own:

    a model call   a POST to .../messages (the Anthropic Messages API) whose `messages` hold a user
                   message and that offers tools -- the agent's own turn. Claude Code's side calls
                   (a title, a summary for its status line) offer none and go through as they are;
                   so do a subagent's (its `Agent` tool), which carry `X-Claude-Code-Agent-Id` and
                   the session's id: a conversation of their own, whose result reaches the session
                   as the Agent call's tool_result
    the session    the `X-Claude-Code-Session-Id` header, else the session id in the body's
                   `metadata.user_id` (a JSON object); none: None. `claude --session-id <uuid>`
                   chooses it, and a resumed session keeps it
    gatherer       the request's label (/h/<label>/ in ANTHROPIC_BASE_URL), each session a channel
                   in it; without one, the session id, and the channel the session id too
    cwd            the `Primary working directory:` Claude Code states in its environment notes,
                   else the `cwd` option

The `system` prompt, `tools`, `thinking` and the rest of the request go through as Claude Code sent
them: only `messages` is the context manager's. Options: `adaptor` (module:Class), `cwd`, `factory`,
`path`, as the codex hook takes them; `system_messages`: how the adaptor sends system messages back
(ClaudeAdaptor), "keep" or "user" for every request, or "auto" (the default): "user" for a Gemini
model (whose gateway moves system messages into its system instruction), else "keep".
"""

import copy
import json
import os
import re
import sys
from typing import Callable, Optional, Union

from ag.integrations.harnesses.codex.ag_orchestrator.ag_clients import AgClients
from ag.integrations.harnesses.codex.ag_orchestrator.context_manager import load_adaptor
from ag.integrations.tools.ag_connection.ag_client import AgClient
from ag.integrations.tools.ag_orchestrator.adaptor import CHANNEL, Adaptor
from ag.integrations.tools.ag_orchestrator.call_ag import call_ag, keep_read, report_measured
from ..adaptor.adaptor import ClaudeAdaptor
from ..adaptor.to_events import Continuity, blocks_of

CWD = re.compile(r"Primary working directory:\s*(\S+)")
SESSION_HEADER = "x-claude-code-session-id"
AGENT_HEADER = "x-claude-code-agent-id"           # set on a subagent's calls only


def is_model_call(method: str, path: str, body) -> bool:
    """Whether the request is the agent's own model call: a POST to .../messages with a messages
    list holding a user message, offering tools."""
    if method != "POST" or not path.split("?", 1)[0].rstrip("/").endswith("/messages"):
        return False
    if not isinstance(body, dict) or not isinstance(body.get("messages"), list) or not body.get("tools"):
        return False
    return any(isinstance(m, dict) and m.get("role") == "user" for m in body["messages"])


def session_of(headers, body: dict) -> Optional[str]:
    """The Claude Code session the request belongs to, or None."""
    lower = {k.lower(): v for k, v in (headers or {}).items()}
    if lower.get(SESSION_HEADER):
        return lower[SESSION_HEADER]
    user = (body.get("metadata") or {}).get("user_id") if isinstance(body, dict) else None
    try:
        return json.loads(user).get("session_id") or None if isinstance(user, str) else None
    except (ValueError, AttributeError):
        return None


def is_subagent(headers) -> bool:
    """Whether the call is a subagent's (Claude Code's `Agent` tool), not the session's own."""
    return any(k.lower() == AGENT_HEADER and v for k, v in (headers or {}).items())


def is_gemini(model) -> bool:
    """Whether the request's model is a Gemini model (as a gateway names it: gemini-..., or provider/gemini-...)."""
    return isinstance(model, str) and model.lower().rsplit("/", 1)[-1].startswith("gemini")


def cwd_of(messages: list) -> Optional[str]:
    """The agent's working directory as Claude Code's notes last state it, or None."""
    found = None
    for m in messages:
        for b in blocks_of(m):
            for match in CWD.findall(str(b.get("text") or "")):
                found = match
    return found


def _print(gatherer: str, line: str) -> None:
    print(f"[{gatherer}] {line}", flush=True)


class ClaudeContextManager:
    """The hook: `await hook(request)` -> Claude Code's body with new `messages`, or None.

    Args:
        cwd: the working directory when a request does not state one.
        factory, path: handed to each gatherer's server (`--factory`, `--path`).
        ag_clients: the server client per gatherer (`AgClients` of `ag_client.AgClient` by default).
        adaptor: the adaptor, or its class as "module:Class"; Claude Code's own by default.
        system_messages: "auto" (by the request's model: Gemini "user", any other "keep"), "keep" or
            "user" -- the adaptor's setting for a request (see ClaudeAdaptor).
        log: (gatherer, line) -> None, for what each model call came to.
    """

    def __init__(self, cwd: Optional[str] = None, factory: Optional[str] = None, path: Optional[str] = None,
                 ag_clients: Optional[AgClients] = None, log: Callable[[str, str], None] = _print,
                 adaptor: Union[Adaptor, str, None] = None, system_messages: str = "auto"):
        args = (["--factory", factory] if factory else []) + \
            [x for p in (path.split(os.pathsep) if path else []) for x in ("--path", p)]
        self.ag_clients = ag_clients or AgClients(lambda gatherer: AgClient("claude", args=args))
        self.cwd, self.log = cwd, log
        self.adaptor = load_adaptor(adaptor) if isinstance(adaptor, str) else (adaptor or ClaudeAdaptor())
        if system_messages not in ("auto", "keep", "user"):
            raise ValueError(f"system_messages: {system_messages!r}, not auto, keep or user")
        self.system_messages = system_messages
        self.adaptors = {}                                  # one per mode: requests run concurrently
        self.continuity = {}                                # (gatherer, channel) -> its Continuity (to_events.py)
        for mode in ("keep", "user"):
            a = copy.copy(self.adaptor)
            a.system_messages = mode                        # the adaptor's own setting (ClaudeAdaptor)
            self.adaptors[mode] = a

    async def __call__(self, request) -> Optional[dict]:
        body = request.body
        if not is_model_call(request.method, request.path, body) or is_subagent(request.headers):
            return None
        session = session_of(request.headers, body)
        if not session:
            print("a model call with no session id; request unchanged", file=sys.stderr, flush=True)
            return None
        gatherer, channel = (request.label, session) if request.label else (session, session)
        messages = body["messages"]
        mode = self.system_messages if self.system_messages != "auto" else \
            ("user" if is_gemini(body.get("model")) else "keep")
        adaptor = self.adaptors[mode]
        if isinstance(adaptor, ClaudeAdaptor):                    # its ids carry on from the channel's last call
            adaptor = adaptor.for_channel(self.continuity.setdefault((gatherer, channel), Continuity()))
        out = {}
        new, note = await call_ag(self.ag_clients.client(gatherer), gatherer, {CHANNEL: channel},
                                  cwd_of(messages) or self.cwd, messages, adaptor, out=out,
                                  limit=getattr(request, "limit", None))
        self.log(gatherer, f"[{channel}] {note}")
        keep_read(request, gatherer, out)                 # what was sent is the read's context either way
        if new is None or new == messages:
            return None                                   # nothing to change: Claude Code's own bytes go through
        return dict(body, messages=new)

    async def measured(self, request, tokens: Optional[int]) -> None:
        """The hook server's report, once the answer is back: the call's input tokens, to the read."""
        await report_measured(self.ag_clients, request, tokens)

    async def close(self) -> None:
        """Stop every gatherer's server."""
        await self.ag_clients.close()
