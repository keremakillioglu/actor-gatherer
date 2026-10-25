"""The context manager as Claude Code's hook. Claude Code has no hook that can replace what it sends
its model; the hook server (ag/integrations/tools/hook_server/hook_server.py) gives it one, and calls
this on every request Claude Code sends its ANTHROPIC_BASE_URL; setup/setup.py sets that up. It is given a request -- anything
with `method`, `path`, `label`, `headers` and `body` -- and returns the request body with the context
manager's context as its `messages`, or None to leave the request as it is.

    python -m ag.integrations.tools.hook_server.hook_server --hook ag.integrations.harnesses.claude.ag_orchestrator.context_manager:ClaudeContextManager [--option cwd=DIR ...]

What it decides, Claude Code's own:

    a model call   a POST to .../messages (the Anthropic Messages API) whose `messages` hold a user
                   message and that offers tools -- the agent's own turn. Claude Code's side calls
                   (a title, a summary for its status line) offer none and go through as they are,
                   and so does its WebSearch tool's own call, which offers the web search server tool
                   alone (`Perform a web search for the query: ...`, the search's summary its result);
                   so do a subagent's (its `Agent` tool), which carry `X-Claude-Code-Agent-Id` and
                   the session's id: a conversation of their own, whose result reaches the session
                   as the Agent call's tool_result. Claude Code's other side calls that do offer
                   tools -- `X-Claude-Code-Request-Class` auxiliary or side_reply -- go through as
                   they are too, but for one:
    a suggestion   Claude Code's prompt suggestion: its conversation so far (the session's last
                   call, as it was) with a user message asking what the user might type next
                   (`[SUGGESTION MODE: ...`), and after it any tool call the suggestion's model
                   made with Claude Code's refusal of it. Not a turn: the conversation's events are
                   inserted, the context the next call would get is made read only (the server's
                   `context`: nothing else of the gatherer changes, no read), the suggestion's own
                   messages are put after it, and that is sent -- nothing of it stored, counted or
                   measured
    a recap        Claude Code's "while you were away" recap: its conversation so far with a user
                   message asking for a short summary (`The user stepped away and is coming
                   back.`). Sent as a suggestion is -- the context read only, the recap's message
                   after it, no events of its own -- and its answer, once back, kept as the
                   session's recap (the server's `recap`: `_recaps`, never history)
    a compaction   Claude Code compacting its history (/compact, or its own at its limit): its
                   conversation with, at the end of its last user message, the instruction to
                   summarize it (`CRITICAL: Respond with TEXT ONLY. ...`). The gatherer builds in
                   its place (the server's `compaction`: the conversation's events inserted, a
                   build that closes the running task, waited for and adopted at the next call),
                   and the compaction call gets the context read only, the instruction after it,
                   for the summary Claude Code goes on from -- which ag does not store, holding
                   the history itself (to_events.py)
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
model (whose gateway moves system messages into its system instruction), else "keep"; `count`:
"on" (the default), "check" or "off" -- see Counting; `files`: "on" (the default) or "off" -- see Files.

Counting (counting.py). ag's own count of a context is not Claude's: Claude's tokenizer makes about
half as many tokens again of the same text, and the thinking Claude Code sends back (encrypted) is
counted by the API but not by ag. With `count` "on", once each call is sent, what it holds that is
not counted yet -- its new steps, its thinking, ag's items, the system prompt and tools -- is
counted by the API's /v1/messages/count_tokens, at the request's own upstream with its own
credentials, in the background, and the counts set in place of ag's (the server's `counted`): the
policy then sizes contexts in Claude's tokens. And before a call is sent ("on" or "check"): once
ag's count of all the call sends reaches COUNT_FROM of the policy's budget, the request is counted
exactly (about 0.1 s); a count over the budget is reported as the read's size (`measured`) and the
context read again, so the policy, seeing it, switches to a build or makes one. Under a build, the
thinking from before the switch is not sent (counting.py says why). Tool search itself, a server
tool, cannot be counted and is left out (the count then differs from the call's by a few dozen
tokens); an upstream that cannot count is not asked again.

Files (ag/integrations/tools/ag_orchestrator/file_touches/). With `files` "on", what each of the session's tool calls
did to files is found on disk as they run, and kept in the gatherer (the server's `touches`) for the
dashboard's Files view: once an answer is back whole, before Claude Code has its end (`before_end`),
the files its calls name are looked at; once their results come in, with the session's next call,
the files are looked at again, and the changes the operating system reported under the session's
directory taken -- in the background, the call not held up.
"""

import copy
import json
import os
import re
import sys
import time
from typing import Callable, Optional, Tuple, Union

from ag.integrations.harnesses.codex.ag_orchestrator.ag_clients import AgClients
from ag.integrations.harnesses.codex.ag_orchestrator.context_manager import load_adaptor
from ag.integrations.tools.ag_connection.ag_client import AgClient
from ag.integrations.tools.ag_orchestrator.adaptor import CHANNEL, Adaptor
from ag.integrations.tools.hook_server.hook_server import Answer
from ag.integrations.tools.ag_orchestrator.call_ag import call_ag, keep_read, pending_ag, preamble_of, report_measured
from ag.integrations.tools.ag_orchestrator.file_touches import Files
from ..adaptor import to_messages as back
from ..adaptor.adaptor import ClaudeAdaptor
from ..adaptor.to_events import Continuity, blocks_of
from .counting import Counter, countable  # noqa: F401 - countable: this module's before counting.py

CWD = re.compile(r"Primary working directory:\s*(\S+)")
SESSION_HEADER = "x-claude-code-session-id"
AGENT_HEADER = "x-claude-code-agent-id"           # set on a subagent's calls only
REQUEST_CLASS_HEADER = "x-claude-code-request-class"   # main, subagent, workflow, compaction, auxiliary, side_reply
SIDE_CLASSES = ("auxiliary", "side_reply")       # Claude Code's side calls, not the session's turns
SUGGESTION = "[SUGGESTION MODE:"                 # how Claude Code's prompt suggestion asks
RECAP = "The user stepped away and is coming back."   # how Claude Code's away recap asks
COMPACTION = "CRITICAL: Respond with TEXT ONLY"  # how Claude Code's compaction call asks for its summary
WEB_SEARCH = "web_search_"                       # the web search server tool's type, before its version
ANSWERED = "claude_answered"   # the hook's key in the hook server's `request.state`: where a call's answer is kept
RECAPPED = "claude_recap"      # the same, for a recap: (gatherer, session), its answer kept as the session's recap
FILES = "claude_files"         # the same, for what the answer's calls do to files: (gatherer, session, cwd, since)
COUNT_FROM = 0.5            # of the budget, by the policy's count: from there a context is counted before it is sent


def is_model_call(method: str, path: str, body) -> bool:
    """Whether the request is the agent's own model call: a POST to .../messages with a messages
    list holding a user message, offering tools -- not the web search server tool alone, which is
    Claude Code's WebSearch tool searching."""
    if method != "POST" or not path.split("?", 1)[0].rstrip("/").endswith("/messages"):
        return False
    if not isinstance(body, dict) or not isinstance(body.get("messages"), list) or not body.get("tools"):
        return False
    if all(is_web_search(t) for t in body["tools"]):
        return False
    return any(isinstance(m, dict) and m.get("role") == "user" for m in body["messages"])


def is_web_search(tool) -> bool:
    """Whether a tool offered is the API's web search server tool (`web_search_20250305`, ...)."""
    return isinstance(tool, dict) and str(tool.get("type") or "").startswith(WEB_SEARCH)


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


def request_class(headers) -> Optional[str]:
    """What Claude Code says the call is (`X-Claude-Code-Request-Class`), or None."""
    return next((str(v).lower() for k, v in (headers or {}).items() if k.lower() == REQUEST_CLASS_HEADER and v), None)


def suggestion_at(messages: list, opening: str = SUGGESTION) -> Optional[int]:
    """Where a prompt suggestion's own message is -- a user message of text alone opening with
    `opening` (`[SUGGESTION MODE:`), after the conversation it forks -- or None: not a suggestion.
    It is the last message, or followed only by the suggestion's own tool calls, each an assistant
    message and the user message of its results: Claude Code refuses a tool the suggestion's model
    calls (`No tools needed for suggestion`) and asks it again, the refusal after the call."""
    if len(messages) < 2 or not isinstance(messages[-1], dict) or messages[-1].get("role") != "user":
        return None
    at = len(messages) - 1
    while at >= 2 and any(b.get("type") == "tool_result" for b in blocks_of(messages[at])) and \
            isinstance(messages[at - 1], dict) and messages[at - 1].get("role") == "assistant":
        at -= 2                                           # a call of the suggestion's own, and its refusal
    blocks = blocks_of(messages[at])
    if at < 1 or not blocks or messages[at].get("role") != "user" or any(b.get("type") != "text" for b in blocks):
        return None
    return at if str(blocks[0].get("text") or "").lstrip().startswith(opening) else None


def recap_at(messages: list) -> Optional[int]:
    """Where a recap's own message is, as `suggestion_at` finds a suggestion's; None: not a recap."""
    return suggestion_at(messages, RECAP)


def compaction_split(messages: list) -> Optional[Tuple[list, list]]:
    """(the conversation, the instruction's blocks) of a compaction call -- the last user message's
    text blocks from the one opening with `CRITICAL: Respond with TEXT ONLY` on are the instruction,
    the rest the conversation -- or None: not a compaction."""
    at = next((i for i in range(len(messages) - 1, -1, -1)
               if isinstance(messages[i], dict) and messages[i].get("role") == "user"), None)
    if at is None or at < len(messages) - 2:          # the last user message, or just before a system note
        return None
    blocks = blocks_of(messages[at])
    start = next((j for j, b in enumerate(blocks) if b.get("type") == "text"
                  and str(b.get("text") or "").lstrip().startswith(COMPACTION)), None)
    if start is None:
        return None
    rest = [dict(messages[at], content=blocks[:start])] if start else []
    return messages[:at] + rest + messages[at + 1:], blocks[start:]


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
        count: "on" (a context near its budget counted before it is sent, and every call's new
            events after it is), "check" (only the first), or "off".
        files: "on" (what each tool call did to files, found on disk -- see Files) or "off".
        log: (gatherer, line) -> None, for what each model call came to.
    """

    def __init__(self, cwd: Optional[str] = None, factory: Optional[str] = None, path: Optional[str] = None,
                 ag_clients: Optional[AgClients] = None, log: Callable[[str, str], None] = _print,
                 adaptor: Union[Adaptor, str, None] = None, system_messages: str = "auto", count: str = "on",
                 files: str = "on"):
        args = (["--factory", factory] if factory else []) + \
            [x for p in (path.split(os.pathsep) if path else []) for x in ("--path", p)]
        self.ag_clients = ag_clients or AgClients(lambda gatherer: AgClient("claude", args=args))
        self.cwd, self.log = cwd, log
        self.adaptor = load_adaptor(adaptor) if isinstance(adaptor, str) else (adaptor or ClaudeAdaptor())
        if system_messages not in ("auto", "keep", "user"):
            raise ValueError(f"system_messages: {system_messages!r}, not auto, keep or user")
        self.system_messages = system_messages
        if count not in ("on", "check", "off"):
            raise ValueError(f"count: {count!r}, not on, check or off")
        self.counter = Counter(enabled=count != "off", log=log)
        self.count_events = count == "on"
        if files not in ("on", "off"):
            raise ValueError(f"files: {files!r}, not on or off")
        self.files = Files(self.ag_clients, log) if files == "on" else None
        self.adaptors = {}                                  # one per mode: requests run concurrently
        self.continuity = {}                                # (gatherer, channel) -> its Continuity (to_events.py)
        for mode in ("keep", "user"):
            a = copy.copy(self.adaptor)
            a.system_messages = mode                        # the adaptor's own setting (ClaudeAdaptor)
            self.adaptors[mode] = a

    async def __call__(self, request) -> Optional[dict]:
        body, since = request.body, time.time()
        if not is_model_call(request.method, request.path, body) or is_subagent(request.headers):
            return None
        session = session_of(request.headers, body)
        if not session:
            print("a model call with no session id; request unchanged", file=sys.stderr, flush=True)
            return None
        gatherer, channel = (request.label, session) if request.label else (session, session)
        client = self.ag_clients.client(gatherer)
        refused = await self.refused(client, gatherer, channel, getattr(request, "process", None))
        if refused is not None:
            return refused
        messages = body["messages"]
        recap = recap_at(messages)
        at = suggestion_at(messages) if recap is None else recap
        if at is None and request_class(request.headers) in SIDE_CLASSES:
            return None                                   # a side call of Claude Code's own: as it is
        mode = self.system_messages if self.system_messages != "auto" else \
            ("user" if is_gemini(body.get("model")) else "keep")
        adaptor = self.adaptors[mode]
        if isinstance(adaptor, ClaudeAdaptor):                    # its ids carry on from the channel's last call
            adaptor = adaptor.for_channel(self.continuity.setdefault((gatherer, channel), Continuity()))
        if recap is not None and isinstance(getattr(request, "state", None), dict):
            request.state[RECAPPED] = (gatherer, channel)
        if at is not None:
            return await self.side_call(request, client, gatherer, channel, body, messages[:at], messages[at:],
                                        adaptor, mode, "context", "recap" if recap is not None else "suggestion")
        compaction = compaction_split(messages)
        if compaction is not None:
            history, instruction = compaction
            return await self.side_call(request, client, gatherer, channel, body, history,
                                        [{"role": "user", "content": instruction}], adaptor, mode, "compaction",
                                        "compaction")

        cwd = cwd_of(messages) or self.cwd
        if isinstance(getattr(request, "state", None), dict):
            request.state[ANSWERED] = (gatherer, channel, cwd)
            if self.files is not None:
                request.state[FILES] = (gatherer, channel, cwd, since)
        if self.files is not None:                         # the results of the last answer's calls: checked
            self.files.arrived(gatherer, channel, cwd, messages)

        async def read():
            out = {}
            new, note = await call_ag(client, gatherer, {CHANNEL: channel}, cwd,
                                      messages, adaptor, out=out, limit=getattr(request, "limit", None),
                                      preamble=preamble_of({"system": body.get("system"), "tools": body.get("tools")}),
                                      process=getattr(request, "process", None))
            self.log(gatherer, f"[{channel}] {note}")
            return new, out

        new, out = await read()
        size, budget = out.get("sent_tokens"), out.get("budget")      # all of it, as the provider counts
        if "read_id" in out and budget and size is not None and size >= COUNT_FROM * budget:
            counted = await self.counter.exact(request, dict(body, messages=messages if new is None else new))
            if counted is not None and counted > budget:
                self.log(gatherer, f"[{channel}] counted {counted} tokens before sending (ag's count {size}), "
                                   f"over the budget {budget}: read again")
                await client.request("measured", {"gatherer": gatherer, "read_id": out["read_id"], "tokens": counted})
                again, out_again = await read()
                if "read_id" in out_again:
                    new, out = again, out_again
        keep_read(request, gatherer, out)                 # what was sent is the read's context either way
        if new is not None and "read_id" in out:
            new = self.counter.fresh_thinking(gatherer, channel, out.get("basis"), new)
            out["left_out"] = self.counter.left_out(gatherer, channel)     # off the read's sent_tokens
        sent = messages if new is None else new
        if self.count_events and "read_id" in out:
            self.counter.start(request, client, gatherer, {CHANNEL: channel}, body, messages, sent, out)
        if new is None or new == messages:
            return None                                   # nothing to change: Claude Code's own bytes go through
        return dict(body, messages=new)

    async def refused(self, client, gatherer: str, channel: str, process: Optional[dict]):
        """None when the call may go on: its process opens the session (the server's `claim`), or it
        cannot be told. Else the hook server's Answer refusing it: another process that still runs
        has the session open -- after a /resume to it, say -- and two must never write one session."""
        if not process:
            return None
        try:
            answer = await client.request("claim", {"gatherer": gatherer, "session": channel, "process": process})
        except Exception as exc:  # noqa: BLE001 - a claim that cannot be made never blocks the call
            self.log(gatherer, f"[{channel}] could not claim the session: {exc!r}")
            return None
        if not isinstance(answer, dict) or answer.get("claimed") is not False:
            return None
        held = answer.get("holder") or {}
        why = (f"ag: session {channel} is open in another process ({held.get('pid')}, since "
               f"{held.get('opened_at')}): close it there first, or resume another session")
        self.log(gatherer, f"[{channel}] refused: {why}")
        return Answer(400, {"type": "error", "error": {"type": "invalid_request_error", "message": why}})

    async def side_call(self, request, client, gatherer: str, channel: str, body: dict, history: list,
                        prompt: list, adaptor, mode: str, op: str, what: str) -> Optional[dict]:
        """A side call's body (a prompt suggestion, a compaction): the context the session's next call
        would get, read only (`op`: the server's `context`, or `compaction`, which builds first), with
        the call's own message after it; None (Claude Code's own) when there is none."""
        out = {}
        new, note = await call_ag(client, gatherer, {CHANNEL: channel}, cwd_of(history) or self.cwd, history,
                                  adaptor, out=out, limit=getattr(request, "limit", None), op=op,
                                  preamble=preamble_of({"system": body.get("system"), "tools": body.get("tools")}))
        self.log(gatherer, f"[{channel}] {what}: {note}")
        if new is None:
            return None
        new = self.counter.fresh_thinking(gatherer, channel, out.get("basis"), new)
        joined = new + [dict(m) for m in prompt]
        joined = back.as_user(back.tools_placed(joined)) if mode == "user" else back.placed(back.tools_placed(joined))
        return dict(body, messages=joined)

    async def measured(self, request, tokens: Optional[int]) -> None:
        """The hook server's report, once the answer is back: the call's input tokens, to the read."""
        await report_measured(self.ag_clients, request, tokens)

    async def before_end(self, request, status: int, answer: dict) -> None:
        """The hook server's report, once the answer to one of the session's own calls is back whole and
        before Claude Code has its end -- before it runs the tools the answer calls: the files they
        name, looked at as they are (Files)."""
        kept = (getattr(request, "state", None) or {}).get(FILES)
        if kept is None or self.files is None or status != 200 or not isinstance(answer, dict) or answer.get("error"):
            return
        gatherer, channel, cwd, since = kept              # the answer's calls can't have run before it began
        self.files.started(gatherer, channel, cwd, answer.get("output_items") or [],
                           getattr(request, "answer_started", None) or since)

    async def answered(self, request, status: int, answer: dict) -> None:
        """The hook server's report, once Claude Code has the whole answer to one of the session's
        own calls: the answer's events kept as pending (the server's `pending`) until the channel's
        next call stores them as events -- so a reader of the gatherer sees the reply that ends a
        turn, which no call carries until the user writes again, and a tool call while it runs. A
        failed answer, or one with no content, is not kept. A recap's answer is kept as the
        session's recap instead (the server's `recap`), never as events."""
        recapped = (getattr(request, "state", None) or {}).get(RECAPPED)
        if recapped is not None:
            await self.recapped(recapped, status, answer)
            return
        kept = (getattr(request, "state", None) or {}).get(ANSWERED)
        if kept is None or status != 200:
            return
        if not isinstance(answer, dict) or answer.get("error") or not answer.get("output_items"):
            return
        gatherer, channel, cwd = kept
        note = await pending_ag(self.ag_clients.client(gatherer), gatherer, {CHANNEL: channel}, cwd,
                                [{"role": "assistant", "content": answer["output_items"]}], self.adaptor,
                                answer.get("response_id"), answer.get("status"))
        self.log(gatherer, f"[{channel}] answered ({answer.get('status')}): {note}")

    async def recapped(self, recapped: Tuple[str, str], status: int, answer: dict) -> None:
        """A recap's answer, kept as its session's recap: the text of its answer, if any."""
        if status != 200 or not isinstance(answer, dict) or answer.get("error"):
            return
        text = "\n".join(str(b.get("text") or "") for b in answer.get("output_items") or []
                         if isinstance(b, dict) and b.get("type") == "text").strip()
        if not text:
            return
        gatherer, session = recapped
        try:
            got = await self.ag_clients.client(gatherer).request("recap", {"gatherer": gatherer, "session": session,
                                                                           "text": text})
        except Exception as exc:  # noqa: BLE001 - a lost recap never breaks the call
            got = {"error": repr(exc)}
        self.log(gatherer, f"[{session}] recap: " + (f"kept ({got.get('recap_id')})" if isinstance(got, dict)
                                                     and not got.get("error") else f"not kept: {got}"))

    async def close(self) -> None:
        """Let counts and file checks still under way finish, then stop every gatherer's server."""
        await self.counter.close()
        if self.files is not None:
            await self.files.close()
        await self.ag_clients.close()
