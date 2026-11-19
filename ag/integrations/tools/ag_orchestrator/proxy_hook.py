"""What a proxy hook does for every harness (the Claude Code and codex hooks build on it): once the hook server has a
call's answer, as it streams and once whole, the answer is recorded as events of the session -- each complete part
(`reply_part`), then its end (`reply_end`) -- and a call that failed as `call_failed`; every call it sees is recorded as
`model_call` (records.py) -- a turn's as it comes in, before ag reads for it (`calling`). A side call whose answer is the session's recap or name is the subclass's to read
(`side_answered`). From each call of a session on, the harness's own record of it is followed (`following`,
session_files.py): what it says that no call carries recorded as it is written. What an answer asks the user, and what
a call's new pieces say of background tasks, are recorded too (`derive`: harness_kit's `derived`), each once, by the
harness's own ids. What a call is, the harness's rules say (its `harness`, harness_kit's).

The harness's own hooks report to the hook server too, where its launcher pointed them (a POST to HOOK_PATH, under the
URL's /h/<gatherer>/): a permission it asks in its terminal before a tool runs (harness_kit's `hooked`), recorded as
`asked` (`reported`) -- the subclass answers the hook {} at once, deciding nothing: the harness's dialog drawn as ever. Its thread calling
its model again -- the session's turn, or the subagent that asked -- is what says the dialog was answered: neither runs
on while it waits; recorded `ask_settled` (`moved_on`). A "No" that interrupts the turn, or Esc, its record says.

A subclass gives:
    harness           the harness's rules (harness_kit.Harness)
    ANSWERED, FILES   its keys in the hook server's `request.state`: where a call's (gatherer, channel, cwd) is kept
                      for its answer, and (gatherer, channel, cwd, since) for the files the answer's calls touch
    answer_items      the harness's messages an answer's output items are (Claude Code's: one assistant message)
and may override `overtaken` (an answer a later call has carried back already) and `side_answered`.

What the hook server reports once the harness has an answer (`answered`, `failed`) or as it streams (`streamed`, a
task of its own) is recorded then and there: the harness waits on none of it. Its report that the harness hung up on a
call while the hook was still reading for it (`hung_up`: Esc, as ag waited for its build) goes to ag at once. A model call is recorded in the
background, so the call is not held up for it; `close` waits for what is under way.
"""

import asyncio
import os
import subprocess
import time
from typing import Callable, Dict, List, Optional, Set, Tuple

from harness_kit import Call, Fact, Facts, Harness, Part
from harness_kit.base import HOOK_PATH

from .adaptor import CHANNEL
from .call_ag import HUNG_UP, READ, call_ag, keep_read, read_of, report_measured
from .records import Outbox, call_failed, derived, model_call, recap, reply_end, reply_parts, name
from .session_files import SessionFiles


PROC = "/proc"


def process_ended(pid) -> Optional[bool]:
    """Whether process `pid` has ended: True when it is gone or a zombie (exited, its parent yet to reap it -- as a
    harness is for a moment after its terminal closes), False while it runs, None when it cannot be told. From /proc
    where there is one, else from `ps` (macOS): a call to make when the process's end matters, not on every request."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    if os.path.isdir(PROC):
        try:
            with open(os.path.join(PROC, str(pid), "stat"), encoding="ascii", errors="replace") as fh:
                fields = fh.read().rsplit(")", 1)[-1].split()      # after the command, which may hold spaces and ')'
        except FileNotFoundError:
            return True
        except OSError:
            return None
        return bool(fields) and fields[0] in ("Z", "X")
    try:
        done = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    state = done.stdout.strip()
    if not state:
        return True if done.returncode == 1 else None              # ps: 1 when there is no such process
    return state.startswith("Z")


class ProxyHook:
    harness: Harness
    ANSWERED = "answered"
    FILES = "files"
    SESSION = "ag_session"           # its key in `request.state`: the call's (gatherer, channel), once known (`following`)

    #: How long the hook waits for ag to take a hang-up (`hung_up`): it answers at once, beside the reads.
    HUNG_UP_SECONDS = 5.0

    def __init__(self, ag_clients, log: Callable[[str, str], None], files=None, sessions: Optional[SessionFiles] = ...):
        self.ag_clients, self.log, self.files = ag_clients, log, files
        self.outbox = Outbox(ag_clients, log)        # every event it records: in order per channel, none lost to a lock
        self.sessions = SessionFiles(ag_clients, log, outbox=self.outbox) if sessions is ... else sessions
        self.adaptor = getattr(self, "adaptor", None)
        self.under_way: Set[asyncio.Future] = set()
        #: (gatherer, channel) -> {an open permission's key: the subagent that asked, None the session itself}
        self.permissions: Dict[Tuple[str, str], Dict[str, Optional[str]]] = {}
        #: (label, run, actor) -> the harness's own session the run opened, kept in the actor's channel (`channel_of`)
        self.mains: Dict[Tuple[Optional[str], Optional[str], str], str] = {}

    # ---- which channel a session is kept in

    def channel_of(self, request, session: str) -> str:
        """The channel the harness's own session `session` is kept in: the one the run's starter chose for it (the
        URL's /a/<channel>/, `request.actor`) where it is the run's own -- the first session of its own the run calls
        the model in: the one it opened or resumed -- so a session the dashboard started on a harness that picks its id
        only at its first call (codex's thread, agy's conversation) is kept under the dashboard's id from that call on,
        and never renamed; any other session (one the run opened later: codex's /new) and a run with no /a/, the
        session's own id."""
        actor = getattr(request, "actor", None)
        if not actor or not session:
            return session
        mains = self.__dict__.setdefault("mains", {})
        own = mains.setdefault((getattr(request, "label", None), getattr(request, "run", None), actor), session)
        return actor if own == session else session

    # ---- recording, in the background

    def keep(self, coro) -> None:
        """Run `coro` in the background, kept until it is done (`close` waits for it)."""
        task = asyncio.ensure_future(coro)
        self.under_way.add(task)
        task.add_done_callback(self.under_way.discard)

    async def recorded(self, gatherer: str, channel: str, events: list) -> Optional[dict]:
        """`events` recorded in the channel, after those before them (records.py's `Outbox`: never raises, never
        lost to a locked database) -- the server's answer, None when not stored now."""
        return await self.outbox.record(gatherer, channel, events) if events else None

    def called(self, gatherer: str, channel: str, call: Call, read_id: Optional[int] = None, **detail) -> None:
        """A model call the hook saw, recorded (`model_call`), in the background: its kind, the harness and its version
        -- and `derives`, that this hook records what its answers ask and its tasks (`derive`), so a reader may take
        their absence as none."""
        self.keep(self.recorded(gatherer, channel, [model_call(call.kind, self.harness.name, call.version, read_id,
                                                               {"derives": True, **detail})]))

    async def calling(self, request, gatherer: str, channel: str, call: Call) -> None:
        """A turn's call recorded as it comes in (`model_call`), before ag reads for it -- which can take seconds, as it
        waits for a build -- with the run it came from (`request.run`, the URL's /r/: the process a dashboard's terminal
        started), where known: what tells a reader the harness has begun its turn (a key that stops it now stops it),
        and which session a new process works in (a codex thread, an agy conversation) -- `session`, the harness's own
        id for it, where that is not the channel (`channel_of`: the dashboard's, `request.actor`). Awaited, in the session's own
        lane at ag's server: so it is stored before the read begins, and a new gatherer's database is made by one lane,
        not two at once."""
        await self.recorded(gatherer, channel, [model_call(call.kind, self.harness.name, call.version, None,
                                                           {"derives": True, "run": getattr(request, "run", None),
                                                            **({"session": call.session} if call.session and
                                                               call.session != channel else {})})])

    def derive(self, gatherer: str, channel: str, parts: List[Part], history: Optional[list] = None,
               asks: bool = True) -> None:
        """What `parts` -- an answer's, or a call's new pieces -- say besides the conversation (harness_kit's `derived`:
        an ask, an asking call's result, a background task started, stopped or noticed), recorded in the background,
        beside the session's reads; a task's output file followed while it runs (session_files.py's `task`). `asks`:
        what the parts ask too (a call's new pieces open with the answer that asked: recorded already)."""
        try:
            facts = [f for f in self.harness.derived(parts, time.time(), history)
                     if not (f.type == Facts.ASKED and (self.harness.asks_recorded or not asks))]
        except Exception as exc:  # noqa: BLE001 - a lost record never breaks the call
            self.log(gatherer, f"[{channel}] nothing derived: {exc!r}")
            return
        if not facts:
            return
        if self.sessions is not None:
            for f in facts:
                if f.type in (Facts.TASK_STARTED, Facts.TASK_ENDED):
                    self.sessions.task(gatherer, channel, f.data["task"], f.data.get("output") if f.type == Facts.TASK_STARTED else None)
        self.keep(self.outbox.record(gatherer, channel, [derived(f) for f in facts], beside=True))

    def following(self, request, gatherer: str, channel: str, call: Call) -> None:
        """The session's own record followed (session_files.py), from this call of it on: where it runs, and the
        harness's own folder for it as its launcher named it (`request.config`, the URL's /c/). The call's session kept
        on the request, for a hang-up while ag reads for it (`hung_up`)."""
        if isinstance(getattr(request, "state", None), dict):
            request.state[self.SESSION] = (gatherer, channel)
        if self.sessions is not None and call is not None and call.session:
            self.sessions.follow(gatherer, channel, self.harness, call.session, call.cwd, getattr(request, "config", None))

    async def recapped(self, gatherer: str, channel: str, text: Optional[str]) -> None:
        """A recap the harness made of the session, recorded."""
        if text and await self.recorded(gatherer, channel, [recap(text)]) is not None:
            self.log(gatherer, f"[{channel}] recap: kept")

    async def named(self, gatherer: str, channel: str, text: Optional[str], by: str) -> None:
        """A name for the session, recorded as `by` gave it."""
        if text and await self.recorded(gatherer, channel, [name(text, by)]) is not None:
            self.log(gatherer, f"[{channel}] name: kept")

    # ---- the harness's own hooks' reports

    @staticmethod
    def reporting(request) -> bool:
        """Whether the request is one of the harness's own hooks' reports (a POST to HOOK_PATH), not a model call."""
        return getattr(request, "method", None) == "POST" and getattr(request, "path", None) == HOOK_PATH

    def reported(self, request, gatherer: Optional[str], channel: Optional[str]) -> None:
        """A hook's report (`reporting`) of the session `channel`: what it says (harness_kit's `hooked`: a permission
        asked) recorded in the background, beside the session's reads -- the hook is answered at once. A permission is
        kept open until its thread calls its model again, or asks again (`moved_on`)."""
        body = getattr(request, "body", None)
        if not gatherer or not channel or not isinstance(body, dict):
            return
        try:
            facts = self.harness.hooked(body, time.time())
        except Exception as exc:  # noqa: BLE001 - a lost record never holds the harness up
            self.log(gatherer, f"[{channel}] hook report not read: {exc!r}")
            return
        events = []
        for f in facts:
            if f.type == Facts.ASKED and f.data.get("kind") == "permission":
                events += self._settled(gatherer, channel, f.data.get("agent"))    # its dialogs come one at a time
                self.permissions.setdefault((gatherer, channel), {})[f.data["call"]] = f.data.get("agent")
                self.log(gatherer, f"[{channel}] asks permission: {f.data.get('tool')}, {f.data.get('said')}"
                                   + (f" (subagent {f.data['agent']})" if f.data.get("agent") else ""))
            events.append(derived(f))
        if events:
            self.keep(self.outbox.record(gatherer, channel, events, beside=True))

    def moved_on(self, gatherer: str, channel: str, agent: Optional[str] = None) -> None:
        """The session's turn (`agent` None), or its subagent `agent`, calls its model: the permission it asked is
        answered -- it does not call again while its dialog waits. Recorded `ask_settled`, in the background."""
        events = self._settled(gatherer, channel, agent)
        if events:
            self.keep(self.outbox.record(gatherer, channel, events, beside=True))

    def _settled(self, gatherer: str, channel: str, agent: Optional[str]) -> List[dict]:
        """The permissions `agent` (None: the session itself) asked that are open, closed: their `ask_settled` events --
        answered, as it calls its model again or asks again (it draws one dialog at a time, the next once the last is
        answered)."""
        open_ = self.permissions.get((gatherer, channel))
        done = [k for k, by in (open_ or {}).items() if by == agent]
        for k in done:
            del open_[k]
        if open_ is not None and not open_:
            self.permissions.pop((gatherer, channel), None)
        now = time.time()
        return [derived(Fact(Facts.ASK_SETTLED, k, now, {"call": k, "how": "answered", "result": None})) for k in done]

    # ---- a turn: its context read by ag

    #: Of the budget, by the policy's count: from there a turn's context is counted before it is sent, and read again
    #: if it is over (`turn`).
    COUNT_FROM = 0.5

    async def turn(self, request, call: Call, gatherer: str, channel: str, cwd: Optional[str], items: list, field: str,
                   body: dict, preamble: list, since: float, adaptor=None, run: Optional[str] = None,
                   first: Optional[Callable[[dict], None]] = None) -> Tuple[Optional[list], dict]:
        """A turn's call of the session, read for by ag, the same for every harness: recorded before ag reads for it
        (`calling`); its keys kept for its answer; the files its last answer's calls touched checked, and what came
        since derived (`arrived`); its context read (`call_ag`), and -- from COUNT_FROM of the budget -- counted as the
        provider counts (`count`) and read again if over; the read kept (`kept`), and the counter started (`counting`).
        `items` is the harness's history, sent as `body[field]`; `adaptor`, this call's (else the hook's); `first`, what
        the call does with its first read's `out`, before it is counted. -> (the history to send, or None: the harness's
        own; the read's `out`)."""
        await self.calling(request, gatherer, channel, call)
        if isinstance(getattr(request, "state", None), dict):
            request.state[self.ANSWERED] = (gatherer, channel, cwd)
            if self.files is not None:
                request.state[self.FILES] = (gatherer, channel, cwd, since)
        if self.files is not None:                         # the results of the last answer's calls: checked
            self.files.arrived(gatherer, channel, cwd, items)
        self.arrived(gatherer, channel, items)
        client = self.ag_clients.client(gatherer)

        async def read():
            out = {}
            new, note = await call_ag(client, gatherer, {CHANNEL: channel}, cwd, items, adaptor or self.adaptor, out=out,
                                      limit=getattr(request, "limit", None), preamble=preamble,
                                      process=getattr(request, "process", None), run=run)
            self.log(gatherer, f"[{channel}] {note}")
            return new, out

        new, out = await read()
        if first is not None:
            first(out)
        stored = list(out.get("inserted") or [])           # what this call stored, over both reads
        size, budget = out.get("sent_tokens"), out.get("budget")      # all of it, as the provider counts
        if "read_id" in out and budget and size is not None and size >= self.COUNT_FROM * budget:
            counted = await self.count(request, gatherer, channel, dict(body, **{field: items if new is None else new}))
            if counted is not None and counted > budget:
                self.log(gatherer, f"[{channel}] counted {counted} tokens before sending (ag's count {size}), "
                                   f"over the budget {budget}: read again")
                await client.request("measured", {"gatherer": gatherer, "read_id": out["read_id"], "tokens": counted})
                again, out_again = await read()
                stored += out_again.get("inserted") or []
                if "read_id" in out_again:
                    new, out = again, out_again
        keep_read(request, gatherer, out)                 # what was sent is the read's context either way
        self.kept(request, gatherer, channel, call, out, stored)
        new = self.sending(new, out)
        if self.count_events and "read_id" in out:
            self.counting(request, client, gatherer, channel, body, items, items if new is None else new, out, preamble)
        return new, out

    def arrived(self, gatherer: str, channel: str, items: list) -> None:
        """A turn's history come in, before ag reads for it: what the subclass reads of it (`derive`). Nothing here."""

    async def count(self, request, gatherer: str, channel: str, body: dict) -> Optional[int]:
        """The tokens `body` holds, as the provider counts them; None when it cannot be told (the shared counter's)."""
        return await self.counter.exact(gatherer, channel, request, body)

    def kept(self, request, gatherer: str, channel: str, call: Call, out: dict, stored: List[int]) -> None:
        """A turn's read kept for its answer: what the subclass keeps beside it (`stored`, the rows its reads stored).
        Nothing here."""

    def sending(self, new: Optional[list], out: dict) -> Optional[list]:
        """The history to send, as the subclass changes it last. As it is here."""
        return new

    def counting(self, request, client, gatherer: str, channel: str, body: dict, items: list, sent: list, out: dict,
                 preamble: list) -> None:
        """What was sent, to the counter (the shared one's, counting.py): kept, and counted as the call goes."""
        self.counter.sent(gatherer, channel, out, sent, preamble)
        self.counter.start(request, client, gatherer, {CHANNEL: channel}, body, items, sent, out)

    # ---- the hook server's reports

    async def hung_up(self, request) -> None:
        """The hook server's report that the harness hung up on a call while the hook still read for it (the user pressed
        Esc as ag waited for its build): ag told (its `hung_up`), so the session's read stops waiting and answers with what
        it has -- nothing will be sent. The hook then finishes as it would, and the hang-up is recorded (`failed`)."""
        state = getattr(request, "state", None) or {}
        kept = state.get(self.ANSWERED) or state.get(self.SESSION)
        if kept is None:
            return
        gatherer, channel = kept[0], kept[1]
        try:
            got = await asyncio.wait_for(self.ag_clients.client(gatherer).request(
                "hung_up", {"gatherer": gatherer, "properties": {CHANNEL: channel}}), self.HUNG_UP_SECONDS)
        except asyncio.TimeoutError:
            return
        if isinstance(got, dict) and got.get("stopped") and not state.get("ag_stopped"):
            state["ag_stopped"] = True
            self.log(gatherer, f"[{channel}] the harness hung up as ag read for the call: told to stop waiting")

    def answer_items(self, output_items: list) -> list:
        """The harness's messages an answer's output items are, as its adaptor takes them."""
        return output_items

    def overtaken(self, request, gatherer: str, channel: str) -> bool:
        """Whether a later call of the channel has carried this answer back already: then it is not recorded."""
        return False

    async def side_answered(self, request, status: int, answer) -> bool:
        """Whether the answer is a side call's the subclass kept (a recap, a title), read by it; False: a call of the
        session's own."""
        return False

    async def reply(self, request, answer: dict, ended: bool) -> Optional[str]:
        """The answer's parts recorded, and -- once it `ended` -- its end, why it stopped: a note, None when there is
        nothing."""
        kept = (getattr(request, "state", None) or {}).get(self.ANSWERED)
        if kept is None or not isinstance(answer, dict) or not answer.get("output_items"):
            return None
        gatherer, channel, _cwd = kept
        if self.overtaken(request, gatherer, channel):
            return None
        try:
            events = self.adaptor.to_events(self.answer_items(answer["output_items"]))
        except Exception as exc:  # noqa: BLE001 - a lost record never breaks the call
            return f"could not make events: {exc!r}; nothing kept"
        answer_id = answer.get("response_id") or f"read{read_of(request)}"
        out = reply_parts(answer_id, events)
        if ended:
            out.append(reply_end(answer_id, answer.get("status"), read_of(request)))
        await self.recorded(gatherer, channel, out)
        if ended:                                         # what it asks the user, once the answer is whole
            body = getattr(request, "body", None)
            history = body.get("messages") or body.get("input") or body.get("contents") if isinstance(body, dict) else None
            self.derive(gatherer, channel, self.harness.read(self.harness.items(self.answer_items(answer["output_items"]))),
                        self.harness.items(history) if isinstance(history, list) else None)
        return f"{len(events)} parts" + (f", ended ({answer.get('status')})" if ended else "")

    async def streamed(self, request, answer: dict) -> None:
        """The hook server's report, while the answer to one of the session's own calls streams, that a part of it is
        complete: the parts complete so far recorded (`reply_part`, each once) -- so a reader of the gatherer sees what
        the agent wrote before a tool call as the harness shows it, not once the call's input has streamed too."""
        if not isinstance(answer, dict) or not answer.get("response_id"):
            return
        note = await self.reply(request, answer, False)
        kept = (getattr(request, "state", None) or {}).get(self.ANSWERED)
        if note and kept:
            self.log(kept[0], f"[{kept[1]}] streaming: {note}")

    async def answered(self, request, status: int, answer: dict) -> None:
        """The hook server's report, once the harness has the whole answer to one of the session's own calls: its parts
        and its end recorded (`reply_part`, `reply_end`) -- so a reader of the gatherer sees the reply that ends a
        turn, which no call carries until the user writes again, and a tool call while it runs. A failed answer, or one
        with no content, is not; a side call's is the subclass's (`side_answered`)."""
        if await self.side_answered(request, status, answer):
            return
        if status != 200 or not isinstance(answer, dict) or answer.get("error"):
            return
        note = await self.reply(request, answer, True)
        kept = (getattr(request, "state", None) or {}).get(self.ANSWERED)
        if note and kept:
            self.log(kept[0], f"[{kept[1]}] answered ({answer.get('status')}): {note}")

    async def measured(self, request, tokens: Optional[int]) -> None:
        """The hook server's report, once the answer is back: the call's input tokens, to the read -- and to the
        counter, which counts by them what the count endpoint cannot (the shared counter's `reported`, counting.py)."""
        await report_measured(self.ag_clients, request, tokens)
        reported = getattr(getattr(self, "counter", None), "reported", None)   # Claude Code's own counter has none
        state = getattr(request, "state", None) or {}
        read, answered = state.get(READ), state.get(self.ANSWERED)
        if reported and getattr(self, "count_events", False) and read and answered and isinstance(tokens, int):
            gatherer, read_id = read
            reported(request, self.ag_clients.client(gatherer), gatherer, answered[1], read_id, tokens,
                     request.body if isinstance(request.body, dict) else {})

    async def failed(self, request, status: Optional[int], error: str, withdrawn: Optional[bool] = None) -> None:
        """The hook server's report that one of the session's own calls failed -- its endpoint answered an error, or
        could not be reached: recorded (`call_failed`), on the read it came from -- what tells a turn that stopped on an
        error from one under way. `withdrawn`: a hook's own, whether it had what the call stored withdrawn -- on a
        hang-up, none (False) unless it says it did."""
        kept = (getattr(request, "state", None) or {}).get(self.ANSWERED)
        if kept is None:
            return
        gatherer, channel, _cwd = kept
        reached = getattr(request, "answer_reached", None) if status == HUNG_UP else None   # Esc: before its words, or after
        withdrawn = bool(withdrawn) if status == HUNG_UP else None
        await self.recorded(gatherer, channel, [call_failed(read_of(request), status, error, reached, withdrawn)])

    @staticmethod
    async def harness_ended(request) -> bool:
        """Whether the harness's process that made the call has ended (`process_ended`) -- its run, the URL's /r/,
        where its launcher names it by its process id (ag execs the harness, so it is the harness's), else the process
        the connection came from (Linux): a call it dropped as its terminal closed, which a harness does once its
        process is gone, not one it gave up (Esc). False where that cannot be told."""
        run = getattr(request, "run", None)
        process = getattr(request, "process", None)
        pid = int(run) if isinstance(run, str) and run.isdigit() else (
            process.get("pid") if isinstance(process, dict) else None)
        if not pid:
            return False
        return bool(await asyncio.to_thread(process_ended, pid))

    async def before_end(self, request, status: int, answer: dict) -> None:
        """The hook server's report, once the answer to one of the session's own calls is back whole and before the
        harness has its end -- before it runs the tools the answer calls: the files they name, looked at as they are
        (file_touches)."""
        kept = (getattr(request, "state", None) or {}).get(self.FILES)
        if kept is None or self.files is None or status != 200 or not isinstance(answer, dict) or answer.get("error"):
            return
        gatherer, channel, cwd, since = kept              # the answer's calls can't have run before it began
        self.files.started(gatherer, channel, cwd, self.answer_items(answer.get("output_items") or []),
                           getattr(request, "answer_started", None) or since)

    async def close(self) -> None:
        """Let what is under way finish -- records, counts, file checks -- then stop every gatherer's server."""
        if self.under_way:
            await asyncio.gather(*list(self.under_way), return_exceptions=True)
        counter = getattr(self, "counter", None)
        if counter is not None:
            await counter.close()
        if self.files is not None:
            await self.files.close()
        if self.sessions is not None:
            await self.sessions.close()
        await self.outbox.close()
        await self.ag_clients.close()
