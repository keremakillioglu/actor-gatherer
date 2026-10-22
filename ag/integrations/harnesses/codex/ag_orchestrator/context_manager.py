"""The context manager as codex's hook. Codex has no hook of its own; the hook server
(ag/integrations/tools/hook_server/hook_server.py) gives it one, and calls this on every
request codex sends its model's endpoint; setup/setup.py sets that up. It is given a
request -- anything with `method`, `path`, `label`, `headers` and `body` -- and returns
codex's request body with the context manager's context as its `input`, or None to
leave the request as it is.

    python -m ag.integrations.tools.hook_server.hook_server --hook ag.integrations.harnesses.codex.ag_orchestrator.context_manager:CodexContextManager [--option cwd=DIR ...]

What it decides, codex's own:

    a model call   a POST to .../responses whose `input` list holds a user
                   message (the Responses API codex speaks); anything else: None
    the thread     the `thread-id` header (then `session-id`, then the body's
                   `prompt_cache_key`), the same when a thread is resumed; none: None
    gatherer       the request's label (/h/<label>/ in the URL codex was pointed
                   at), each thread a channel in it; without one, the thread id,
                   and the channel the thread id too
    cwd            the last <environment_context> in the input's: its <cwd>, or (when
                   it has none) its first workspace root

Then one model call through routing (ag/integrations/tools/ag_orchestrator/call_ag.py) with codex's
adaptor (adaptor/adaptor.py, or the one named by the `adaptor` option), each
gatherer with a context manager server of its own (ag_clients.py). None when
the context manager could not answer, or its context is codex's input as it
was. Options (given by the hook server's --option): `adaptor`, the adaptor
class as `module:Class`; `cwd`, the working directory when a request states
none; `factory` and `path` (paths joined by the OS's path separator), handed
to each gatherer's server.
"""

import importlib
import os
import re
import sys
from typing import Callable, Optional, Union

from ag.integrations.tools.ag_connection.ag_client import AgClient
from ag.integrations.tools.ag_orchestrator.adaptor import CHANNEL, Adaptor
from ag.integrations.tools.ag_orchestrator.call_ag import call_ag, keep_read, report_measured
from .ag_clients import AgClients
from ..adaptor.adaptor import CodexAdaptor

CWD = re.compile(r"<cwd>\s*(.*?)\s*</cwd>", re.S)
ROOT = re.compile(r"<workspace_roots>\s*<root>\s*(.*?)\s*</root>", re.S)


def load_adaptor(spec: str) -> Adaptor:
    """An adaptor from its class's "module:Class"."""
    module, _, attr = spec.partition(":")
    cls = getattr(importlib.import_module(module), attr)
    if not (isinstance(cls, type) and issubclass(cls, Adaptor)):
        raise TypeError(f"{spec} is not an Adaptor")
    return cls()


def is_model_call(method: str, path: str, body) -> bool:
    """Whether the request is a model call whose input the context manager
    answers for: a POST to .../responses with an input list holding a user
    message."""
    if method != "POST" or not path.split("?", 1)[0].rstrip("/").endswith("/responses"):
        return False
    if not isinstance(body, dict) or not isinstance(body.get("input"), list):
        return False
    return any(isinstance(i, dict) and i.get("role") == "user" for i in body["input"])


def thread_of(headers, body: dict) -> Optional[str]:
    """The codex thread id the request belongs to, or None."""
    lower = {k.lower(): v for k, v in (headers or {}).items()}
    return lower.get("thread-id") or lower.get("session-id") or body.get("prompt_cache_key") or None


def texts_of(item) -> list:
    if not isinstance(item, dict):
        return []
    parts = item.get("content")
    if isinstance(parts, str):
        return [parts]
    return [p["text"] for p in parts or [] if isinstance(p, dict) and isinstance(p.get("text"), str)]


def cwd_of(items: list) -> Optional[str]:
    """The agent's working directory, as the last <environment_context> in
    the input states it -- its <cwd>, or, where codex writes none, the first
    of its <workspace_roots> -- None if none does."""
    found = None
    for item in items:
        for text in texts_of(item):
            if "<environment_context>" in text:
                match = CWD.findall(text) or ROOT.findall(text)
                if match:
                    found = match[-1]
    return found


def _print(gatherer: str, line: str) -> None:
    print(f"[{gatherer}] {line}", flush=True)


class CodexContextManager:
    """The hook: `await hook(request)` -> codex's body with a new `input`, or None.

    Args:
        cwd: the working directory when a request does not state one.
        factory, path: handed to each gatherer's server (`--factory`, `--path`).
        ag_clients: the server client per gatherer (`AgClients` of `ag_client.AgClient`
            by default).
        adaptor: the adaptor, or its class as "module:Class"; codex's own by default.
        log: (gatherer, line) -> None, for what each model call came to.
    """

    def __init__(self, cwd: Optional[str] = None, factory: Optional[str] = None, path: Optional[str] = None,
                 ag_clients: Optional[AgClients] = None, log: Callable[[str, str], None] = _print,
                 adaptor: Union[Adaptor, str, None] = None):
        args = (["--factory", factory] if factory else []) + \
            [x for p in (path.split(os.pathsep) if path else []) for x in ("--path", p)]
        self.ag_clients = ag_clients or AgClients(lambda gatherer: AgClient("codex", args=args))
        self.cwd, self.log = cwd, log
        self.adaptor = load_adaptor(adaptor) if isinstance(adaptor, str) else (adaptor or CodexAdaptor())

    async def __call__(self, request) -> Optional[dict]:
        body = request.body
        if not is_model_call(request.method, request.path, body):
            return None
        thread = thread_of(request.headers, body)
        if not thread:
            print("a model call with no thread id; request unchanged", file=sys.stderr, flush=True)
            return None
        gatherer, channel = (request.label, thread) if request.label else (thread, thread)
        items, out = body["input"], {}
        messages, note = await call_ag(self.ag_clients.client(gatherer), gatherer, {CHANNEL: channel},
                                       cwd_of(items) or self.cwd, items, self.adaptor, out=out,
                                       limit=getattr(request, "limit", None))
        self.log(gatherer, f"[{channel}] {note}")
        keep_read(request, gatherer, out)                 # what was sent is the read's context either way
        if messages is None or messages == items:
            return None                                   # nothing to change: codex's own bytes go through
        return dict(body, input=messages)

    async def measured(self, request, tokens: Optional[int]) -> None:
        """The hook server's report, once the answer is back: the call's input tokens, to the read."""
        await report_measured(self.ag_clients, request, tokens)

    async def close(self) -> None:
        """Stop every gatherer's server."""
        await self.ag_clients.close()
