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
for the dashboard's Files view -- as the Claude Code hook does (its Files).
"""

import importlib
import json
import os
import re
import sys
import time
from typing import Callable, Optional, Tuple, Union

from ag.integrations.tools.ag_connection.ag_client import AgClient
from ag.integrations.tools.ag_orchestrator.adaptor import CHANNEL, Adaptor
from ag.integrations.tools.ag_orchestrator.call_ag import (STREAMING, call_ag, keep_read, pending_ag, preamble_of,
                                                    read_of, report_failed, report_measured)
from ag.integrations.tools.ag_orchestrator.file_touches import Files
from .ag_clients import AgClients
from ..adaptor.adaptor import CodexAdaptor

CWD = re.compile(r"<cwd>\s*(.*?)\s*</cwd>", re.S)
ROOT = re.compile(r"<workspace_roots>\s*<root>\s*(.*?)\s*</root>", re.S)
ANSWERED = "codex_answered"   # the hook's key in the hook server's `request.state`: where a call's answer is kept
FILES = "codex_files"         # the same, for what the answer's calls do to files: (gatherer, thread, cwd, since)
METADATA = "x-codex-turn-metadata"   # codex's header (and client_metadata key) saying what a call is for
TURN = "user"                         # the thread_source of a thread's own turn; any other is a side call
TRIGGER = "compaction_trigger"        # a compaction call's last item, which codex requires last
SIDE = "codex_side"                   # the same, for a side call whose answer is kept: (kind, gatherer, thread)
KEPT = ("thread_title", "system")     # the side calls whose answers are kept: a title, a recap
NAME_CHARS = 120                      # the longest name kept (codex asks for 36 characters at most)


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


def metadata_of(headers, body: dict) -> dict:
    """What codex says of the call (its turn metadata: thread_source, request_kind, parent_thread_id,
    ...), from its header, else the body's client_metadata; {} when it says nothing."""
    lower = {k.lower(): v for k, v in (headers or {}).items()}
    raw = lower.get(METADATA) or ((body.get("client_metadata") or {}) if isinstance(body.get("client_metadata"), dict)
                                  else {}).get(METADATA)
    try:
        found = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return {}
    return found if isinstance(found, dict) else {}


def side_call(metadata: dict) -> Optional[str]:
    """The kind of codex's own side call this is (its thread_source: thread_title, system, subagent,
    guardian_review, ...), or None: the thread's own turn -- a user source, or none said."""
    source = metadata.get("thread_source")
    if metadata.get("parent_thread_id") and source in (None, TURN):
        source = "subagent"
    return None if source in (None, TURN) else str(source)


def compaction_split(metadata: dict, items: list) -> Optional[Tuple[list, list]]:
    """(the history, the trigger) of a compaction call -- `request_kind` compaction, or an input ending
    with a `compaction_trigger` -- else None."""
    last = items[-1] if items else None
    if isinstance(last, dict) and last.get("type") == TRIGGER:
        return items[:-1], [last]
    if metadata.get("request_kind") == "compaction":
        return items, []
    return None


def texts_of(item) -> list:
    if not isinstance(item, dict):
        return []
    parts = item.get("content")
    if isinstance(parts, str):
        return [parts]
    return [p["text"] for p in parts or [] if isinstance(p, dict) and isinstance(p.get("text"), str)]


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
        files: "on" (what each tool call did to files, found on disk) or "off".
        log: (gatherer, line) -> None, for what each model call came to.
    """

    def __init__(self, cwd: Optional[str] = None, factory: Optional[str] = None, path: Optional[str] = None,
                 ag_clients: Optional[AgClients] = None, log: Callable[[str, str], None] = _print,
                 adaptor: Union[Adaptor, str, None] = None, files: str = "on"):
        args = (["--factory", factory] if factory else []) + \
            [x for p in (path.split(os.pathsep) if path else []) for x in ("--path", p)]
        self.ag_clients = ag_clients or AgClients(lambda gatherer: AgClient("codex", args=args))
        self.cwd, self.log = cwd, log
        self.adaptor = load_adaptor(adaptor) if isinstance(adaptor, str) else (adaptor or CodexAdaptor())
        if files not in ("on", "off"):
            raise ValueError(f"files: {files!r}, not on or off")
        self.files = Files(self.ag_clients, log) if files == "on" else None
        self.runs = {}                    # (label, run) -> (gatherer, thread): the thread whose own turn it sent last
        self.latest = {}                  # (gatherer, thread) -> the read its newest call's context came from

    async def __call__(self, request) -> Optional[dict]:
        body, since = request.body, time.time()
        if not is_model_call(request.method, request.path, body):
            return None
        thread = thread_of(request.headers, body)
        if not thread:
            print("a model call with no thread id; request unchanged", file=sys.stderr, flush=True)
            return None
        gatherer, channel = (request.label, thread) if request.label else (thread, thread)
        metadata = metadata_of(request.headers, body)
        kind, run = side_call(metadata), getattr(request, "run", None)
        if kind is not None:
            of = self.runs.get((request.label, run)) if kind in KEPT and run else None
            if of is not None and isinstance(getattr(request, "state", None), dict):
                request.state[SIDE] = (kind, *of)
                self.log(of[0], f"[{channel}] codex's own {kind} call, for {of[1]}: as it is, its answer kept")
            else:
                self.log(gatherer, f"[{channel}] codex's own {kind} call: as it is, not stored")
            return None
        if run:
            self.runs[(request.label, run)] = (gatherer, channel)
        items, out = body["input"], {}
        cwd = cwd_of(items) or self.cwd
        compaction = compaction_split(metadata, items)
        if compaction is not None:
            return await self.compaction(request, gatherer, channel, body, cwd, *compaction)
        if isinstance(getattr(request, "state", None), dict):
            request.state[ANSWERED] = (gatherer, channel, cwd)
            if self.files is not None:
                request.state[FILES] = (gatherer, channel, cwd, since)
        if self.files is not None:                         # the results of the last answer's calls: checked
            self.files.arrived(gatherer, channel, cwd, items)
        messages, note = await call_ag(self.ag_clients.client(gatherer), gatherer, {CHANNEL: channel},
                                       cwd, items, self.adaptor, out=out,
                                       limit=getattr(request, "limit", None),
                                       preamble=preamble_of({"instructions": body.get("instructions"), "tools": body.get("tools")}),
                                       process=getattr(request, "process", None), run=run)
        self.log(gatherer, f"[{channel}] {note}")
        keep_read(request, gatherer, out)                 # what was sent is the read's context either way
        if isinstance(out.get("read_id"), int):
            self.latest[(gatherer, channel)] = max(out["read_id"], self.latest.get((gatherer, channel), 0))
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
        """The hook server's report, once the answer is back: the call's input tokens, to the read."""
        await report_measured(self.ag_clients, request, tokens)

    async def failed(self, request, status: Optional[int], error: str) -> None:
        """The hook server's report that one of the session's own calls failed -- its endpoint answered an
        error, or could not be reached -- to the read it came from: what tells a turn that stopped on an
        error from one under way."""
        await report_failed(self.ag_clients, request, status, error)

    async def before_end(self, request, status: int, answer: dict) -> None:
        """The hook server's report, once the answer to one of the thread's own calls is back whole and
        before codex has its end -- before it runs the tools the answer calls: the files they name,
        looked at as they are (file_touches)."""
        kept = (getattr(request, "state", None) or {}).get(FILES)
        if kept is None or self.files is None or status != 200 or not isinstance(answer, dict) or answer.get("error"):
            return
        gatherer, channel, cwd, since = kept              # the answer's calls can't have run before it began
        self.files.started(gatherer, channel, cwd, answer.get("output_items") or [],
                           getattr(request, "answer_started", None) or since)

    async def streamed(self, request, answer: dict) -> None:
        """The hook server's report, while the answer to a model call streams, that an output item is
        done: the items done so far kept as pending, stopped STREAMING, in place of those kept before --
        what codex wrote before a tool call seen as codex shows it. `answered` replaces them."""
        kept = (getattr(request, "state", None) or {}).get(ANSWERED)
        if kept is None or not isinstance(answer, dict) or not answer.get("output_items") or not answer.get("response_id"):
            return
        gatherer, channel, cwd = kept
        if self.overtaken(request, gatherer, channel):
            return
        note = await pending_ag(self.ag_clients.client(gatherer), gatherer, {CHANNEL: channel}, cwd,
                                answer["output_items"], self.adaptor, answer["response_id"], STREAMING)
        self.log(gatherer, f"[{channel}] streaming: {note}")

    async def answered(self, request, status: int, answer: dict) -> None:
        """The hook server's report, once codex has the whole answer to a model call: its output items,
        as events, kept as pending (the server's `pending`) until the thread's next call stores them
        -- so a reader of the gatherer sees the turn's last reply, which no call carries until the
        user writes again, and a tool call while it runs; in place of the items kept while it streamed
        (`streamed`). A failed answer, or one with no output, is not kept; nor one a later call of the
        thread has carried back already (`overtaken`). A side call's answer is kept for its thread
        (`side_answered`): a title, a recap."""
        side = (getattr(request, "state", None) or {}).get(SIDE)
        if side is not None:
            return await self.side_answered(side, status, answer)
        kept = (getattr(request, "state", None) or {}).get(ANSWERED)
        if kept is None or status != 200:
            return
        if not isinstance(answer, dict) or answer.get("error") or not answer.get("output_items"):
            return
        gatherer, channel, cwd = kept
        if self.overtaken(request, gatherer, channel):
            return
        note = await pending_ag(self.ag_clients.client(gatherer), gatherer, {CHANNEL: channel}, cwd,
                                answer["output_items"], self.adaptor, answer.get("response_id"),
                                answer.get("status"), read_of(request))
        self.log(gatherer, f"[{channel}] answered ({answer.get('status')}): {note}")

    def overtaken(self, request, gatherer: str, channel: str) -> bool:
        """Whether a later call of the thread has been read since this one: codex sends its next call
        once it has the whole answer -- before the end of its stream is written, before the hook server
        is done with it -- and that call carries this answer back, stored. Kept as pending now, it would
        show twice until the thread's next call."""
        read_id = read_of(request)
        return isinstance(read_id, int) and read_id < self.latest.get((gatherer, channel), 0)

    async def side_answered(self, side: Tuple[str, str, str], status: int, answer: dict) -> None:
        """A side call's answer, kept for the thread it was for: a title as its name (by "codex"); a recap
        -- its summary, and the next action when it says one -- as its recap. Not kept: a failed answer, or
        one that is not what codex asked for ({"title"}, {"summary", "next_action"})."""
        kind, gatherer, thread = side
        got = answer_object(answer) if status == 200 and isinstance(answer, dict) and not answer.get("error") else {}
        if kind == "thread_title":
            text = " ".join(str(got.get("title") or "").split())[:NAME_CHARS]
            op, body = "name", {"gatherer": gatherer, "session": thread, "text": text, "by": "codex"}
        else:
            summary, then = str(got.get("summary") or "").strip(), str(got.get("next_action") or "").strip()
            text = summary + (f"\n\nNext: {then}" if summary and then else "")
            op, body = "recap", {"gatherer": gatherer, "session": thread, "text": text}
        if not text:
            self.log(gatherer, f"[{thread}] codex's {kind}: nothing to keep ({status})")
            return
        try:
            kept = await self.ag_clients.client(gatherer).request(op, body)
        except Exception as exc:  # noqa: BLE001 - a lost name or recap never breaks the call
            kept = {"error": repr(exc)}
        self.log(gatherer, f"[{thread}] {op}: " + ("kept" if isinstance(kept, dict) and not kept.get("error")
                                                   else f"not kept: {kept}"))

    async def close(self) -> None:
        """Let file checks under way finish, then stop every gatherer's server."""
        if self.files is not None:
            await self.files.close()
        await self.ag_clients.close()
