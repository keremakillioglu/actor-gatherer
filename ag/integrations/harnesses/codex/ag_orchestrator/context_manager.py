"""The context manager as codex's hook. Codex has no hook of its own; the hook server
(ag/integrations/tools/hook_server/hook_server.py) gives it one, and calls this on every
request codex sends its model's endpoint; setup/setup.py sets that up. It is given a
request -- anything with `method`, `path`, `label`, `headers` and `body` -- and returns
codex's request body with the context manager's context as its `input`, or None to
leave the request as it is.

    python -m ag.integrations.tools.hook_server.hook_server --hook ag.integrations.harnesses.codex.ag_orchestrator.context_manager:CodexContextManager [--option cwd=DIR ...]

What it decides, codex's own:

    a model call   a POST to .../responses whose `input` list holds a user
                   message (the Responses API codex speaks); anything else: None.
                   Codex says what each call is for in its turn metadata (the
                   `x-codex-turn-metadata` header, else the body's `client_metadata`):
                   `thread_source` user is the thread's own turn; any other is a
                   side call of codex's own, in a thread of its own, and goes through
                   as it is, nothing of it stored, but for two answers --
        thread_title     a title for the thread, after its first message (codex's interactive
                         UI only): its answer, {"title"}, kept as the thread's name (the
                         server's `name`, by "codex": `_names`)
        system           a "catch-up" recap of the thread (/recap), its conversation pasted
                         in: its answer, {"summary", "next_action"}, kept as the thread's
                         recap (the server's `recap`: `_recaps`)
                         -- neither names the thread it is for, so the run tells: the thread
                         whose own turn the same run (`request.run`, the /r/<run>/ codex's
                         launcher puts in its URL) sent last; with no run, or no turn yet,
                         not kept
        subagent         a subagent's thread (`parent_thread_id`): an agent it spawned,
                         /review's reviewer; what it found reaches the thread as a message
        guardian_review  the reviewer that approves an action for --approve-for-me
        memory_consolidation  codex's memories, written in the background
                   A call with no metadata (an older codex) is a turn.
    a compaction   codex compacting its thread's history (/compact, or its own at
                   its limit): `request_kind` compaction, its input ending with a
                   `compaction_trigger` item. The gatherer builds in its place (the
                   server's `compaction`: the history's events inserted, a build that
                   closes the running task), and the call gets that context read only,
                   the trigger after it, for the summary codex goes on from -- which
                   ag does not store, holding the history itself (to_events.py)
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
to each gatherer's server; `files`, "on" (the default) or "off": what each of the
thread's tool calls did to files, found on disk as they run and kept in the gatherer
for the dashboard's Files view -- as the Claude Code hook does (its Files). From each of the thread's own turns on,
codex's rollout of it is followed, and what it says recorded as events of the thread (harness_kit.codex's Rollout;
session_files.py) -- as the Claude Code hook does its record.
"""

import importlib
import json
import os
import sys
import time
from typing import Callable, Optional, Tuple, Union

from harness_kit import Codex
from harness_kit.codex import (METADATA, TRIGGER, TURN, compaction_split, cwd_of,  # noqa: F401 - codex's rules for
                               is_model_call, metadata_of, side_call, texts_of, thread_of)  # its calls, as this module had them

from ag.integrations.tools.ag_connection.ag_client import AgClient
from ag.integrations.tools.ag_orchestrator.adaptor import CHANNEL, Adaptor
from ag.integrations.tools.ag_orchestrator.call_ag import READ, call_ag, keep_read, preamble_of, read_of, report_measured
from ag.integrations.tools.ag_orchestrator.proxy_hook import ProxyHook
from ag.integrations.tools.ag_orchestrator.file_touches import Files
from .ag_clients import AgClients
from .counting import Counter
from ..adaptor.adaptor import CodexAdaptor

ANSWERED = "codex_answered"   # the hook's key in the hook server's `request.state`: where a call's answer is kept
FILES = "codex_files"         # the same, for what the answer's calls do to files: (gatherer, thread, cwd, since)
SIDE = "codex_side"                   # the same, for a side call whose answer is kept: (kind, gatherer, thread)
KEPT = ("thread_title", "system")     # the side calls whose answers are kept: a title, a recap
NAME_CHARS = 120                      # the longest name kept (codex asks for 36 characters at most)
COUNT_FROM = 0.5      # of the budget, by the policy's count: from there a context is counted before it is sent


def load_adaptor(spec: str) -> Adaptor:
    """An adaptor from its class's "module:Class"."""
    module, _, attr = spec.partition(":")
    cls = getattr(importlib.import_module(module), attr)
    if not (isinstance(cls, type) and issubclass(cls, Adaptor)):
        raise TypeError(f"{spec} is not an Adaptor")
    return cls()


def answer_object(answer: dict) -> dict:
    """What a side call's answer says, read as the JSON object codex asked for (its output schema): the
    text of its messages; {} when it is not one."""
    text = "".join(t for item in answer.get("output_items") or [] if isinstance(item, dict)
                   and item.get("type") == "message" for t in texts_of(item))
    try:
        found = json.loads(text)
    except ValueError:
        return {}
    return found if isinstance(found, dict) else {}


def _print(gatherer: str, line: str) -> None:
    print(f"[{gatherer}] {line}", flush=True)


class CodexContextManager(ProxyHook):
    """The hook: `await hook(request)` -> codex's body with a new `input`, or None.

    Args:
        cwd: the working directory when a request does not state one.
        factory, path: handed to each gatherer's server (`--factory`, `--path`).
        ag_clients: the server client per gatherer (`AgClients` of `ag_client.AgClient`
            by default).
        adaptor: the adaptor, or its class as "module:Class"; codex's own by default.
        files: "on" (what each tool call did to files, found on disk) or "off".
        log: (gatherer, line) -> None, for what each model call came to.
    """
    harness = Codex()
    ANSWERED, FILES = ANSWERED, FILES

    def __init__(self, cwd: Optional[str] = None, factory: Optional[str] = None, path: Optional[str] = None,
                 ag_clients: Optional[AgClients] = None, log: Callable[[str, str], None] = _print,
                 adaptor: Union[Adaptor, str, None] = None, count: str = "on", files: str = "on"):
        args = (["--factory", factory] if factory else []) + \
            [x for p in (path.split(os.pathsep) if path else []) for x in ("--path", p)]
        ag_clients = ag_clients or AgClients(lambda gatherer: AgClient("codex", args=args))
        if files not in ("on", "off"):
            raise ValueError(f"files: {files!r}, not on or off")
        super().__init__(ag_clients, log, Files(ag_clients, log) if files == "on" else None)
        self.cwd = cwd
        self.adaptor = load_adaptor(adaptor) if isinstance(adaptor, str) else (adaptor or CodexAdaptor())
        if count not in ("on", "check", "off"):
            raise ValueError(f"count: {count!r}, not on, check or off")
        self.counter = Counter(self.adaptor, enabled=count != "off", log=log)
        self.count_events = count == "on"
        self.runs = {}                    # (label, run) -> (gatherer, thread): the thread whose own turn it sent last
        self.latest = {}                  # (gatherer, thread) -> the read its newest call's context came from

    async def __call__(self, request) -> Optional[dict]:
        body, since = request.body, time.time()
        call = self.harness.call(request.method, request.path, request.headers, body)
        if call is None:
            return None
        thread = call.session
        if not thread:
            print("a model call with no thread id; request unchanged", file=sys.stderr, flush=True)
            return None
        gatherer, channel = (request.label, thread) if request.label else (thread, thread)
        metadata = call.detail.get("metadata") or {}
        kind, run = call.detail.get("source"), getattr(request, "run", None)
        if kind is not None:
            of = self.runs.get((request.label, run)) if kind in KEPT and run else None
            if of is not None and isinstance(getattr(request, "state", None), dict):
                request.state[SIDE] = (kind, *of)
                self.log(of[0], f"[{channel}] codex's own {kind} call, for {of[1]}: as it is, its answer kept")
            else:
                self.log(gatherer, f"[{channel}] codex's own {kind} call: as it is, not stored")
            if of is not None:                            # recorded in the thread it is for; one of a thread of its own, not
                self.called(*of, call, source=kind)
            return None
        if run:
            self.runs[(request.label, run)] = (gatherer, channel)
        self.following(request, gatherer, channel, call)       # its rollout, followed (session_files.py)
        items, out = body["input"], {}
        cwd = cwd_of(items) or self.cwd
        compaction = compaction_split(metadata, items)
        if compaction is not None:
            self.called(gatherer, channel, call)
            return await self.compaction(request, gatherer, channel, body, cwd, *compaction)
        if isinstance(getattr(request, "state", None), dict):
            request.state[ANSWERED] = (gatherer, channel, cwd)
            if self.files is not None:
                request.state[FILES] = (gatherer, channel, cwd, since)
        if self.files is not None:                         # the results of the last answer's calls: checked
            self.files.arrived(gatherer, channel, cwd, items)
        client = self.ag_clients.client(gatherer)
        preamble = preamble_of({"instructions": body.get("instructions"), "tools": body.get("tools")})

        async def read():
            out = {}
            new, note = await call_ag(client, gatherer, {CHANNEL: channel}, cwd, items, self.adaptor, out=out,
                                      limit=getattr(request, "limit", None), preamble=preamble,
                                      process=getattr(request, "process", None), run=run)
            self.log(gatherer, f"[{channel}] {note}")
            return new, out

        messages, out = await read()
        self.counter.learn(gatherer, channel, out.get("context"))      # reasoning as costed: for the check
        size, budget = out.get("sent_tokens"), out.get("budget")      # all of it, as the provider counts
        if "read_id" in out and budget and size is not None and size >= COUNT_FROM * budget:
            counted = await self.counter.exact(gatherer, channel, request,
                                               dict(body, input=items if messages is None else messages))
            if counted is not None and counted > budget:
                self.log(gatherer, f"[{channel}] counted {counted} tokens before sending (ag's count {size}), "
                                   f"over the budget {budget}: read again")
                await client.request("measured", {"gatherer": gatherer, "read_id": out["read_id"], "tokens": counted})
                again, out_again = await read()
                if "read_id" in out_again:
                    messages, out = again, out_again
        keep_read(request, gatherer, out)                 # what was sent is the read's context either way
        self.called(gatherer, channel, call, out.get("read_id"))
        if isinstance(out.get("read_id"), int):
            self.latest[(gatherer, channel)] = max(out["read_id"], self.latest.get((gatherer, channel), 0))
        sent = items if messages is None else messages
        if self.count_events and "read_id" in out:
            self.counter.sent(gatherer, channel, out, sent, preamble)
            self.counter.start(request, client, gatherer, {CHANNEL: channel}, body, items, sent, out)
        if messages is None or messages == items:
            return None                                   # nothing to change: codex's own bytes go through
        return dict(body, input=messages)

    async def compaction(self, request, gatherer: str, channel: str, body: dict, cwd: Optional[str], history: list,
                         trigger: list) -> Optional[dict]:
        """A compaction call's body: the gatherer built in codex's place (the server's `compaction`), its
        context read only, with codex's trigger after it (codex requires it last); None (codex's own)
        when there is none."""
        new, note = await call_ag(self.ag_clients.client(gatherer), gatherer, {CHANNEL: channel}, cwd, history,
                                  self.adaptor, limit=getattr(request, "limit", None), op="compaction",
                                  preamble=preamble_of({"instructions": body.get("instructions"), "tools": body.get("tools")}))
        self.log(gatherer, f"[{channel}] compaction: {note}")
        if new is None:
            return None
        return dict(body, input=new + [dict(t) for t in trigger])

    async def measured(self, request, tokens: Optional[int]) -> None:
        """The hook server's report, once the answer is back: the call's input tokens, to the read -- and
        to the counter, which counts by them what the count endpoint cannot (`Counter.reported`)."""
        await report_measured(self.ag_clients, request, tokens)
        state = getattr(request, "state", None) or {}
        read, answered = state.get(READ), state.get(ANSWERED)
        if self.count_events and read and answered and isinstance(tokens, int):
            gatherer, read_id = read
            self.counter.reported(request, self.ag_clients.client(gatherer), gatherer, answered[1], read_id, tokens,
                                  request.body if isinstance(request.body, dict) else {})

    def overtaken(self, request, gatherer: str, channel: str) -> bool:
        """Whether a later call of the thread has been read since this one: codex sends its next call
        once it has the whole answer -- before the end of its stream is written, before the hook server
        is done with it -- and that call carries this answer back, stored. Recorded now, it would show
        twice until the thread's next call."""
        read_id = read_of(request)
        return isinstance(read_id, int) and read_id < self.latest.get((gatherer, channel), 0)

    async def side_answered(self, request, status: int, answer) -> bool:
        """A side call's answer, kept for the thread it was for: a title as its name (by "codex"); a recap
        -- its summary, and the next action when it says one -- as its recap. Not kept: a failed answer, or
        one that is not what codex asked for ({"title"}, {"summary", "next_action"})."""
        side = (getattr(request, "state", None) or {}).get(SIDE)
        if side is None:
            return False
        kind, gatherer, thread = side
        ok = status == 200 and isinstance(answer, dict) and not answer.get("error")
        reply = self.harness.read(answer.get("output_items") or []) if ok else []
        if kind == "thread_title":
            text = self.harness.title(reply)
            await self.named(gatherer, thread, text, "codex")
        else:
            text = self.harness.recap(reply)
            await self.recapped(gatherer, thread, text)
        if not text:
            self.log(gatherer, f"[{thread}] codex's {kind}: nothing to keep ({status})")
        return True
