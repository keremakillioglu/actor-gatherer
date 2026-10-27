"""The events a proxy hook records of what it sees of a session besides its conversation -- HARNESS events, in the
gatherer beside the conversation's, which no policy groups, so they never reach a context. A reader of the gatherer
(the dashboard) reads them in place of asking the harness, or a table of ag's own:

    model_call    every call the hook sees, side calls included: what it is (`kind`: harness_kit's CallKind), the
                  harness and its version as it says; `read_id`, the read a turn's context came from
    reply_part    one complete part of an answer, as the conversation event it will be once a call carries it back
                  (`answer_id`: the provider's id for the answer); the same part is stored once
    reply_end     the answer is whole: why it stopped (`stop`: end_turn, tool_use, ...); `answer_id`, `read_id`
    call_failed   a call failed: its endpoint's HTTP status (None: no answer came), and why; `read_id`
    recap         a recap of the session the harness made, in its words: what it did, and what comes next
    name          a name for the session, as `by` gave it (codex's title for its thread)

and, from the harness's own record of the session as it grows (session_files.py), what no model call carries:

    session_file  the record followed: the harness, and the file's path
    message_queued, message_sent, message_withdrawn, asked, ask_settled, turn_stopped, task_started, task_ended,
    task_activity each a fact the record says (harness_kit's Facts), its data the payload with `at`, when it happened

and, from a call's or an answer's pieces (harness_kit's `derived`; proxy_hook.py's `derive`): what the harness asks
the user (asked), an asking call's result (ask_settled), the background tasks its tools' results start and stop and
their notices (task_started, task_ended, task_activity) -- and a task's output growing, as the hook sees its file
(task_activity, session_files.py).

Each is `{"type", "id", "payload", "properties"?}`, as the server's `insert` takes it, its own properties declared
on its type the first time it is seen. An id says what makes it the same: a reply part by its answer and its place in
it, a reply's end by its answer, a failure by its read, a fact of the record by its place in the file, a derived one by
the harness's own ids (`derived`); any other is new each time (`uuid4`). Sent by `record`, which
never raises: a lost record never holds up a call.
"""

import os
import uuid
from typing import Any, Callable, Dict, List, Optional

from harness_kit.base import Fact, Facts

from .adaptor import CHANNEL

MODEL_CALL, REPLY_PART, REPLY_END, CALL_FAILED, RECAP, NAME, SESSION_FILE = (
    "model_call", "reply_part", "reply_end", "call_failed", "recap", "name", "session_file")
#: Every harness event type a proxy hook records.
RECORDS = (MODEL_CALL, REPLY_PART, REPLY_END, CALL_FAILED, RECAP, NAME, SESSION_FILE) + Facts.ALL
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


def call_failed(read_id: Optional[int], status: Optional[int], error: str) -> dict:
    """A model call that failed: its endpoint's status (None: no answer came), and why."""
    return {"type": CALL_FAILED, "id": f"failed:{read_id}" if read_id is not None else f"failed:{uuid.uuid4().hex}",
            "payload": {"status": status, "error": error}, "properties": _own(read_id=read_id)}


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
    request = {"gatherer": gatherer, "properties": {CHANNEL: channel}, "events": events}
    try:
        got = await client.request("insert", {**request, "lane": RECORDS_LANE} if beside else request)
    except Exception as exc:  # noqa: BLE001 - a lost record never holds up a call
        got = {"error": repr(exc)}
    if not isinstance(got, dict) or got.get("error"):
        if log is not None:
            log(gatherer, f"[{channel}] {', '.join(sorted({e['type'] for e in events}))} not recorded: "
                          f"{got.get('error') if isinstance(got, dict) else got!r}")
        return None
    return got
