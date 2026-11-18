"""The events a proxy hook records of what it sees of a session besides its conversation -- HARNESS events, in the
gatherer beside the conversation's, which no policy groups, so they never reach a context. A reader of the gatherer
(the dashboard) reads them in place of asking the harness, or a table of ag's own:

    model_call    every call the hook sees, side calls included: what it is (`kind`: harness_kit's CallKind), the
                  harness and its version as it says; a turn's recorded as it comes in, before ag reads for it, with
                  `run`, the harness's run it came from as its launcher named it (the URL's /r/: the process a
                  dashboard's terminal started), where known; `read_id`, the read a call's context came from, where given
    reply_part    one complete part of an answer, as the conversation event it will be once a call carries it back
                  (`answer_id`: the provider's id for the answer); the same part is stored once
    reply_end     the answer is whole: why it stopped (`stop`: end_turn, tool_use, ...); `answer_id`, `read_id`
    call_failed   a call failed: its endpoint's HTTP status (None: no answer came), and why; `read_id`
    recap         a recap of the session the harness made, in its words: what it did, and what comes next
    name          a name for the session, as `by` gave it (codex's title for its thread; Claude Code's, from its record)
    harness       the harness a session from before `model_call` ran on, as its pieces' shapes told when its gatherer's
                  old tables were copied into records (migrate.py)

and, from the harness's own record of the session as it grows (session_files.py), what no model call carries:

    session_file  the record followed: the harness, and the file's path
    message_queued, message_sent, message_withdrawn, asked, ask_settled, turn_stopped, task_started, task_ended,
    task_activity, name each a fact the record says (harness_kit's Facts), its data the payload with `at`, when it
                  happened

and, from a call's or an answer's pieces (harness_kit's `derived`; proxy_hook.py's `derive`): what the harness asks
the user (asked), an asking call's result (ask_settled), the background tasks its tools' results start and stop and
their notices (task_started, task_ended, task_activity) -- and a task's output growing, as the hook sees its file
(task_activity, session_files.py); and what each tool call did to files, found on disk as it ran (file_touched,
file_touches/'s `touched`).

Each is `{"type", "id", "payload", "properties"?}`, as the server's `insert` takes it, its own properties declared
on its type the first time it is seen. An id says what makes it the same: a reply part by its answer and its place in
it, a reply's end by its answer, a failure by its read, a fact of the record by its place in the file, a derived one by
the harness's own ids (`derived`); any other is new each time (`uuid4`). Sent by `record`, which
never raises: a lost record never holds up a call -- or, by a hook, through its `Outbox`, which keeps a channel's
events in order and sends again what failed in a way that may pass (the database locked), so none is lost to it.
"""

import asyncio
import os
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

from harness_kit.base import Fact, Facts

from .adaptor import CHANNEL

MODEL_CALL, REPLY_PART, REPLY_END, CALL_FAILED, RECAP, NAME, SESSION_FILE, FILE_TOUCHED, HARNESS = (
    "model_call", "reply_part", "reply_end", "call_failed", "recap", "name", "session_file", "file_touched", "harness")
#: Every harness event type a proxy hook records.
RECORDS = (MODEL_CALL, REPLY_PART, REPLY_END, CALL_FAILED, RECAP, NAME, SESSION_FILE, FILE_TOUCHED, HARNESS) + \
    tuple(t for t in Facts.ALL if t != NAME)
READ_ID, ANSWER_ID = "read_id", "answer_id"
RECORDS_LANE = "records"    # ag's server's lane for records, beside a session's (its server's RECORDS_LANE)
STREAMING = "streaming"     # a reply_part's stop while the answer still streams (no reply_end yet)


def _own(**values) -> Dict[str, Any]:
    return {k: v for k, v in values.items() if v is not None}


def model_call(kind: str, harness: str, version: Optional[str] = None, read_id: Optional[int] = None,
               detail: Optional[dict] = None) -> dict:
    """A model call the hook saw: its kind (a CallKind), the harness, the version it says it is."""
    payload = _own(kind=kind, harness=harness, version=version, **(detail or {}))
    return {"type": MODEL_CALL, "id": f"call:{uuid.uuid4().hex}", "payload": payload, "properties": _own(read_id=read_id)}


def reply_parts(answer_id: str, events: List[dict]) -> List[dict]:
    """The parts of an answer complete so far, each as the conversation event it will be ({type, payload, text}, its
    properties), stored once each by its place in the answer."""
    return [{"type": REPLY_PART, "id": f"{answer_id}:{i}",
             "payload": {k: e[k] for k in ("type", "payload", "text", "properties") if k in e},
             "properties": {ANSWER_ID: answer_id}} for i, e in enumerate(events) if isinstance(e, dict)]


def reply_end(answer_id: str, stop: Optional[str], read_id: Optional[int] = None) -> dict:
    """An answer whole: why it stopped."""
    return {"type": REPLY_END, "id": f"{answer_id}:end", "payload": _own(stop=stop),
            "properties": _own(answer_id=answer_id, read_id=read_id)}


def call_failed(read_id: Optional[int], status: Optional[int], error: str, reached: Optional[str] = None,
                withdrawn: Optional[bool] = None) -> dict:
    """A model call that failed: its endpoint's status (None: no answer came), and why. Hung up on by the harness (499),
    `reached`: what of its answer the harness had in words (hook_server's `answer_reached`: "text", "tool", "nothing");
    `withdrawn`: whether the hook had ag withdraw what the call stored, as for a harness that takes its message back
    (None: a hook that does not say)."""
    return {"type": CALL_FAILED, "id": f"failed:{read_id}" if read_id is not None else f"failed:{uuid.uuid4().hex}",
            "payload": _own(status=status, error=error, reached=reached, withdrawn=withdrawn) | {"status": status},
            "properties": _own(read_id=read_id)}


def recap(text: str) -> dict:
    """A recap of the session, in the harness's words."""
    return {"type": RECAP, "id": f"recap:{uuid.uuid4().hex}", "payload": {"text": text}}


def name(text: str, by: str) -> dict:
    """A name for the session, as `by` gave it."""
    return {"type": NAME, "id": f"name:{uuid.uuid4().hex}", "payload": {"text": text, "by": by}}


def session_file(harness: str, path: str) -> dict:
    """The harness's record of the session, followed from now on."""
    return {"type": SESSION_FILE, "id": f"file:{path}", "payload": {"harness": harness, "path": path}}


def fact(f: Fact, path: str) -> dict:
    """A fact the harness's record at `path` says, the same each time the record is read: by its line's place there."""
    return {"type": f.type, "id": f"{f.type}:{os.path.basename(path)}:{f.key}", "payload": {"at": f.at, **f.data}}


def derived(f: Fact) -> dict:
    """A fact a call's or an answer's pieces say (harness_kit's `derived`), the same each time they are read: by the
    harness's own ids (an asking call's, a task's) its key holds."""
    return {"type": f.type, "id": f"{f.type}:{f.key}", "payload": {"at": f.at, **f.data}}


async def record(client, gatherer: str, channel: str, events: List[dict],
                 log: Optional[Callable[[str, str], None]] = None, beside: bool = False) -> Optional[dict]:
    """The events inserted into the channel (the server's `insert`); the answer, or None when it failed -- said in the
    log, never raised. `beside`: in the server's lane for records, beside the session's own (its RECORDS_LANE), so
    they are not held up behind a read that waits for its build -- for events no read depends on."""
    if not events:
        return None
    got, error = await _insert(client, gatherer, channel, events, beside)
    if error is not None:
        if log is not None:
            log(gatherer, f"[{channel}] {_types(events)} not recorded: {error}")
        return None
    return got


async def _insert(client, gatherer: str, channel: str, events: List[dict], beside: bool) -> Tuple[Optional[dict], Optional[str]]:
    """(the server's answer, None) -- or (None, why it failed); never raises."""
    request = {"gatherer": gatherer, "properties": {CHANNEL: channel}, "events": events}
    try:
        got = await client.request("insert", {**request, "lane": RECORDS_LANE} if beside else request)
    except Exception as exc:  # noqa: BLE001 - a lost record never holds up a call
        got = {"error": repr(exc)}
    if not isinstance(got, dict) or got.get("error"):
        return None, str(got.get("error") if isinstance(got, dict) else got)
    return got, None


def _types(events: List[dict]) -> str:
    return ", ".join(sorted({str(e.get("type")) for e in events}))


#: What an insert's error says when it may pass if tried again: the database locked past the server's wait (another
#: writer held it), or the server gone, not answering, or starting again (ag_client.py's). A request the server
#: refuses (no events, no gatherer) fails the same each time.
PASSING = ("database is locked", "database is busy", "server gone", "no answer in", "server exited",
           "server failed to start")
RETRY_SECONDS = 1.0         # an insert failed: tried again no sooner
GIVE_UP_SECONDS = 600.0     # failing this long: what waits dropped, said in the log


def passing(error: Optional[str]) -> bool:
    """Whether an insert that failed with `error` may pass if tried again (PASSING)."""
    return bool(error) and any(p in error for p in PASSING)


class _Line:
    """A channel's events in one of the server's lanes, sent in order."""

    def __init__(self):
        self.lock = asyncio.Lock()             # one insert at a time, so none passes one before it
        self.waiting: List[dict] = []          # an insert that failed, and every event after it, in order
        self.since = 0.0                       # when it failed
        self.error: Optional[str] = None       # why, as last tried
        self.task: Optional[asyncio.Task] = None


class Outbox:
    """Events recorded in the order sent, per channel and lane -- kept and sent again when an insert fails in a way that
    may pass (`passing`: the database locked, the server starting again), never lost to it: the events after it wait
    behind it, so none is stored before one sent before it (a reader goes by the rows' order: a turn's end before the
    next call, say). Sent again every RETRY_SECONDS in the background, in batches of BATCH, until stored -- or, after
    GIVE_UP_SECONDS, dropped. Nothing waits on that: a caller's insert that fails, or comes while some wait, is
    answered None at once. A failure that would fail again (a request refused) is lost as `record`'s, said in the log.
    Each event is stored once however often it is sent: by its id.

    Args:
        ag_clients: the server client per gatherer.
        log: (gatherer, line) -> None.
    """

    BATCH = 200

    def __init__(self, ag_clients, log: Optional[Callable[[str, str], None]] = None):
        self.ag_clients, self.log = ag_clients, log
        self.lines: Dict[Tuple[str, str, bool], _Line] = {}

    async def record(self, gatherer: str, channel: str, events: List[dict], beside: bool = False) -> Optional[dict]:
        """`events` inserted into the channel after those sent before them (`record`'s, `beside` as there): the
        server's answer, or None -- not stored now, and kept to be sent again if it may pass."""
        if not events:
            return None
        line = self.lines.setdefault((gatherer, channel, beside), _Line())
        if line.waiting:
            line.waiting += events                 # behind those that wait
            return None
        async with line.lock:
            if line.waiting:                       # one before it failed as it waited its turn
                line.waiting += events
                return None
            got, error = await _insert(self.ag_clients.client(gatherer), gatherer, channel, events, beside)
            if error is None:
                return got
            if not passing(error):
                self._log(gatherer, f"[{channel}] {_types(events)} not recorded: {error}")
                return None
            line.waiting, line.since, line.error = list(events), time.time(), error
            self._log(gatherer, f"[{channel}] {_types(events)} not recorded yet: {error}; sent again every "
                                f"{RETRY_SECONDS:g}s, the channel's later events after them")
            line.task = asyncio.ensure_future(self._again(gatherer, channel, beside, line))
            return None

    async def _again(self, gatherer: str, channel: str, beside: bool, line: _Line) -> None:
        """What waits on the line sent again until it is stored, or dropped once it has failed GIVE_UP_SECONDS."""
        sent = 0
        while line.waiting:
            await asyncio.sleep(RETRY_SECONDS)
            if time.time() - line.since > GIVE_UP_SECONDS:
                self._log(gatherer, f"[{channel}] {len(line.waiting)} events ({_types(line.waiting)}) not recorded for "
                                    f"{GIVE_UP_SECONDS:.0f}s ({line.error}): dropped")
                line.waiting = []
                return
            while line.waiting:
                batch = line.waiting[:self.BATCH]
                async with line.lock:
                    _, error = await _insert(self.ag_clients.client(gatherer), gatherer, channel, batch, beside)
                if error is not None and passing(error):
                    line.error = error
                    break                          # tried again later
                if error is not None:
                    self._log(gatherer, f"[{channel}] {_types(batch)} not recorded: {error}")
                else:
                    sent += len(batch)
                del line.waiting[:len(batch)]
        self._log(gatherer, f"[{channel}] recorded {sent} events after {time.time() - line.since:.1f}s")

    def _log(self, gatherer: str, text: str) -> None:
        if self.log is not None:
            self.log(gatherer, text)

    async def close(self) -> None:
        """Sent again no more: what waits dropped, said in the log (sending it now could wait on a server gone)."""
        tasks = [line.task for line in self.lines.values() if line.task is not None and not line.task.done()]
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for (gatherer, channel, _), line in self.lines.items():
            if line.waiting:
                self._log(gatherer, f"[{channel}] {len(line.waiting)} events ({_types(line.waiting)}) not recorded as "
                                    f"the hook closed ({line.error}): dropped")
                line.waiting = []
