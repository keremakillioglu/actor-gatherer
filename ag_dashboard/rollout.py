"""Codex's own record of a thread, its rollout file: what codex does, written as it does it -- where ag hears of
it only with the thread's next model call, or never (an interrupted turn, a turn that gave up, a question answered
in its terminal, a subagent that ended).

    record(thread)       its file, <CODEX_HOME>/sessions/<year>/<month>/<day>/rollout-<time>-<thread>.jsonl;
                         None if none (a thread of another machine, or of another CODEX_HOME)
    read(path)           what it says now (`Record`), read on from where it was last read to
    stopped(r, since)    how its newest turn ended, if it did at or after `since`
    settled(r, call)     whether a question codex asked in its terminal (request_user_input) was answered there
    open_question(r)     the question it asked while its turn goes on (request_user_input_async), not replied to yet
    offer(r)             the plan its last turn proposed, codex asking in its terminal whether to implement it
    agents(r)            its subagents that started and have not ended
    report(r, path)      what the subagent `path` it started last answered, once it ended (its own record's)
    commands(r)          the commands it left running (background terminals) that have not ended
    result(r, call)      what codex recorded as a question's answer, or a plan's
    replies(text)        whether a user message is codex's answers to what it asked as it worked

Each line is {"timestamp", "type", "payload"}; what is read of them (codex 0.164):

    event_msg task_started       a turn begins: its id, its collaboration mode ("plan", "default")
    event_msg task_complete      it ends; with `error` {message, codex_error_info} when it stopped on a model call
                                 that failed, its tries spent
    event_msg turn_aborted       it ends, interrupted (Esc) -- a question it was asking with it
    event_msg item_completed     a Plan item: the plan a Plan-mode turn proposes (its <proposed_plan>); a
                                 SubAgentActivity: a subagent started, or ended; a CommandExecution: a command
                                 ended, its `process_id` that of one left running
    response_item function_call  request_user_input: questions asked in the terminal, the turn waiting on them;
                                 request_user_input_async: asked while the turn goes on
    response_item function_call_output  a question's answer, the moment it is picked: {"answers": {id: {"answers":
                                 [label, "user_note: ..."]}}}, or "aborted by user after ..." (Esc)
    response_item ..._output     a command left running: its output names its session ("session_id": N, or
                                 "Process running with session ID N"), what write_stdin and wait go on with
    response_item message        the user's: an async question's reply (<send_user_message_question_reply>), and
                                 the message the turn after a proposed plan opens with ("Implement the plan.", or
                                 the reader's own once they chose to stay in Plan mode)

Not in it: codex's prompts themselves as they show -- a command's approval ("Would you like to run the following
command?"), the plan's ("Implement this plan?") -- nor the plan's dismissed (Esc), which leaves no line anywhere.
Standard library only.
"""

import glob
import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

CHUNK = 1 << 22                 # a record is read this much at a time
NO_RECORD_SECONDS = 60          # a thread with no record found: not searched for again before this
ASK, ASK_ASYNC = "request_user_input", "request_user_input_async"
ABORTED = "aborted by user"     # a question's output when it was dismissed (Esc), its turn interrupted
REPLY = "<send_user_message_question_reply>"
#: A subagent's activity that says it ended (any other but "started" is not taken for an end).
AGENT_ENDS = {"completed", "interrupted", "errored", "failed", "closed", "shutdown", "cancelled", "stopped", "exited"}
#: A command codex left running, as its call's output names it (a code-mode script's, as JSON in its text).
RUNS = re.compile(r'(?:\\?"session_id\\?":\s*|Process running with session ID )(\d+)')
CMD = re.compile(r'\bcmd\\?"?\s*:\s*\\?"((?:[^"\\]|\\.)*?)\\?"')   # a call's command: {cmd: "..."}
CALLS_KEPT = 20                 # the newest command calls kept, to name a command left running by its call
#: What a line must hold to be one `_take` reads: anything else (most of it) is not parsed at all.
WANTED = (b'"task_started"', b'"task_complete"', b'"turn_aborted"', b'"SubAgentActivity"', b'"type":"Plan"',
          b'"name":"request_user_input', REPLY.encode(), b'"CommandExecution"', b'session_id', b'session ID')


class Record:
    """A rollout as read so far."""

    def __init__(self, ino):
        self.ino, self.at = ino, 0
        self.seen = None        # the file's (mtime, size) when it was last read on: what live.py compares
        self.turn = None        # the newest turn: {id, mode, started, ended, how: None (going on), "complete",
                                # "aborted" or "error"; error: its words, status: its HTTP status, plan: its Plan}
        self.asks: Dict[str, dict] = {}       # call id -> {name, questions, at, turn}: what codex asked the user
        self.results: Dict[str, tuple] = {}   # call id (a plan's, "plan:<turn>") -> (what was recorded, when)
        self.replied: Dict[str, set] = {}     # an async question's call id -> the places of the questions replied to
        self.agents: Dict[str, dict] = {}     # subagent thread -> {path, started, ended}
        self.commands: Dict[str, dict] = {}   # a command left running, by its process -> {label, started, ended}
        self.calls: Dict[str, str] = {}       # the newest command calls: call id -> their command
        self.plan = None        # {turn, at, text}: the plan the newest turn proposed, once it completed
        self.after_plan = None  # a proposed plan's turn, while the turn after it has not said what was chosen


_LOCK = threading.Lock()
_READS: Dict[str, Record] = {}
_FOUND: Dict[tuple, str] = {}           # (codex home, thread) -> its record
_NO_RECORD: Dict[tuple, float] = {}     # (codex home, thread) -> when no record of it was found


def codex_home() -> str:
    return os.environ.get("CODEX_HOME") or os.path.join(os.path.expanduser("~"), ".codex")


def record(thread: str) -> Optional[str]:
    """Codex's record of the thread: found once by a search of its sessions' folders, which is not made again for
    NO_RECORD_SECONDS once it found none; None if none."""
    if not thread:
        return None
    home = codex_home()
    key = (home, thread)
    known = _FOUND.get(key)
    if known and os.path.isfile(known):
        return known
    if time.time() - _NO_RECORD.get(key, 0) < NO_RECORD_SECONDS:
        return None
    found = sorted(glob.glob(os.path.join(glob.escape(home), "sessions", "*", "*", "*", f"rollout-*-{glob.escape(thread)}.jsonl")))
    if found:
        _FOUND[key] = found[-1]
        return found[-1]
    if len(_NO_RECORD) > 1000:
        _NO_RECORD.clear()
    _NO_RECORD[key] = time.time()
    return None


def read(path: Optional[str]) -> Optional[Record]:
    """What the record at `path` says now, read on from where it was last read to (from its start once it is a
    new file, or shorter); None when it can't be read."""
    if not path:
        return None
    try:
        st = os.stat(path)
    except OSError:
        return None
    with _LOCK:
        r = _READS.get(path)
        if r is None or r.ino != st.st_ino or st.st_size < r.at:
            r = _READS[path] = Record(st.st_ino)
        r.seen = (st.st_mtime_ns, st.st_size)
        try:
            with open(path, "rb") as fh:
                fh.seek(r.at)
                while r.at < st.st_size:
                    chunk = fh.read(min(CHUNK, st.st_size - r.at))
                    end = chunk.rfind(b"\n") + 1               # a line still being written: read with the next
                    if not end:
                        if len(chunk) < CHUNK:
                            break
                        end = len(chunk)                       # a line longer than CHUNK: not one read here
                    for line in chunk[:end].split(b"\n"):
                        if _wanted(r, line):
                            _take(r, line)
                    r.at += end
                    fh.seek(r.at)
        except OSError:
            pass
        return r


def _wanted(r: Record, line: bytes) -> bool:
    if any(k in line for k in WANTED):
        return True
    if b'"exec' in line and (b'"custom_tool_call"' in line or b'"function_call"' in line):
        return True                                            # a command's call: what names one left running
    if b'"function_call_output"' in line:                      # the answer to a question asked in the terminal
        return any(c.encode() in line for c, a in r.asks.items() if a["name"] == ASK and c not in r.results)
    return r.after_plan is not None and b'"role":"user"' in line   # what was chosen of a plan


def _take(r: Record, line: bytes) -> None:
    try:
        o = json.loads(line)
    except ValueError:
        return
    p = o.get("payload") if isinstance(o, dict) else None
    if not isinstance(p, dict):
        return
    at, kind = _seconds(o.get("timestamp")), p.get("type")
    if o.get("type") == "event_msg":
        if kind == "task_started":
            if r.plan is not None:                             # the turn after a proposed plan: what it opens with
                r.after_plan = r.plan["turn"]
            r.turn = {"id": p.get("turn_id"), "mode": p.get("collaboration_mode_kind"), "started": at, "ended": None,
                      "how": None, "error": None, "status": None, "plan": None, "said": None}
            r.plan = None
        elif kind in ("task_complete", "turn_aborted") and r.turn is not None and p.get("turn_id") in (r.turn["id"], None):
            error = p.get("error") if isinstance(p.get("error"), dict) else None
            r.turn.update(ended=at, how="aborted" if kind == "turn_aborted" else "error" if error else "complete",
                          error=str(error.get("message") or "") or None if error else None, status=_status(error),
                          said=p.get("last_agent_message") if isinstance(p.get("last_agent_message"), str) else None)
            if r.turn["how"] == "complete" and r.turn["plan"] is not None:
                r.plan = {"turn": r.turn["id"], "at": at, "text": r.turn["plan"]}
        elif kind == "item_completed" and isinstance(p.get("item"), dict):
            item = p["item"]
            if item.get("type") == "Plan" and r.turn is not None and p.get("turn_id") == r.turn["id"]:
                r.turn["plan"] = str(item.get("text") or "")
            elif item.get("type") == "CommandExecution" and str(item.get("process_id") or "") in r.commands:
                if item.get("status") != "in_progress":
                    r.commands[str(item["process_id"])]["ended"] = at
            elif item.get("type") == "SubAgentActivity" and item.get("agent_thread_id"):
                agent = r.agents.setdefault(item["agent_thread_id"], {"path": item.get("agent_path"), "started": at, "ended": None})
                if item.get("kind") == "started":
                    agent.update(started=at, ended=None, path=item.get("agent_path") or agent["path"])
                elif item.get("kind") in AGENT_ENDS:
                    agent["ended"] = at
        return
    if o.get("type") != "response_item":
        return
    if kind in ("function_call", "custom_tool_call") and str(p.get("name") or "").startswith("exec") and p.get("call_id"):
        m = CMD.search(str(p.get("arguments") or p.get("input") or ""))
        r.calls[p["call_id"]] = m.group(1).encode().decode("unicode_escape", "replace") if m else ""
        while len(r.calls) > CALLS_KEPT:
            r.calls.pop(next(iter(r.calls)))
        return
    if kind in ("function_call_output", "custom_tool_call_output") and p.get("call_id") in r.calls:
        text = json.dumps(p.get("output"), ensure_ascii=False)
        if "exit_code" not in text and "Process exited with code" not in text:
            for m in RUNS.finditer(text):
                r.commands.setdefault(m.group(1), {"label": r.calls[p["call_id"]] or None, "started": at, "ended": None})
    if kind == "function_call" and p.get("name") in (ASK, ASK_ASYNC) and p.get("call_id"):
        try:
            args = json.loads(p.get("arguments") or "{}")
        except ValueError:
            args = {}
        questions = args.get("questions") if isinstance(args, dict) else None
        r.asks[p["call_id"]] = {"name": p["name"], "questions": questions if isinstance(questions, list) else [],
                                "at": at, "turn": r.turn["id"] if r.turn else None}
    elif kind == "function_call_output" and r.asks.get(p.get("call_id"), {}).get("name") == ASK:
        out = p.get("output")
        r.results[p["call_id"]] = (out if isinstance(out, str) else json.dumps(out, ensure_ascii=False), at)
    elif kind == "message" and p.get("role") == "user":
        text = "\n".join(c.get("text") or "" for c in p.get("content") or [] if isinstance(c, dict)).strip()
        if text.startswith(REPLY):
            _reply(r, text, at)
        elif r.after_plan is not None and text and not text.startswith("<"):   # not codex's own context
            r.results[f"plan:{r.after_plan}"] = (text, at)
            r.after_plan = None


def replies(text) -> bool:
    """Whether a user message is codex's wrapper of answers to what it asked as it worked (REPLY): the user's words,
    sent while the turn that asked runs -- part of that turn, not one of its own."""
    return isinstance(text, str) and text.lstrip().startswith(REPLY)


def _reply(r: Record, text: str, at: Optional[float]) -> None:
    """An async question's reply: [{answer, question, questionItemId: '["request_user_input_async", call, place]'}]."""
    body = text[len(REPLY):].split("</send_user_message_question_reply>")[0].strip()
    try:
        replies = json.loads(body)
    except ValueError:
        return
    for one in replies if isinstance(replies, list) else []:
        try:
            _, call, place = json.loads(one.get("questionItemId") or "")
        except (ValueError, TypeError, AttributeError):
            continue
        r.replied.setdefault(call, set()).add(place)
        before = r.results.get(call, ("", at))[0]
        r.results[call] = ((before + "\n" if before else "") + json.dumps(one, ensure_ascii=False, separators=(",", ":")), at)


def _status(error: Optional[dict]) -> Optional[int]:
    """The HTTP status a turn's error names ({codex_error_info: {<kind>: {http_status_code}}}), if it names one."""
    info = error.get("codex_error_info") if error else None
    for v in info.values() if isinstance(info, dict) else []:
        if isinstance(v, dict) and isinstance(v.get("http_status_code"), int):
            return v["http_status_code"]
    return None


def _seconds(stamp) -> Optional[float]:
    try:
        got = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (got if got.tzinfo else got.replace(tzinfo=timezone.utc)).timestamp()


def stopped(r: Optional[Record], since: Optional[float]) -> Optional[dict]:
    """How the thread's newest turn ended, if it did at or after `since` (when ag last heard of it):
    {kind: "over" (it completed), "interrupted" (Esc) or "error" (a model call failed, its tries spent), at,
    text: the error's words, status: its HTTP status}. None: it goes on, or ended before, or no record."""
    t = r.turn if r else None
    if not t or t["ended"] is None or (since is not None and t["ended"] < since):
        return None
    return {"kind": {"complete": "over", "aborted": "interrupted"}.get(t["how"], "error"), "at": t["ended"],
            "text": t["error"], "status": t["status"]}


def settled(r: Optional[Record], call: Optional[str]) -> Optional[str]:
    """How a question codex asked in its terminal ended: "answered", "dismissed" (Esc: its turn interrupted), or
    None -- not yet, or not known."""
    if r is None or not call:
        return None
    got = r.results.get(call)
    if got is not None:
        return "dismissed" if got[0].startswith(ABORTED) else "answered"
    ask, t = r.asks.get(call), r.turn
    if ask and t and (t["id"] != ask["turn"] or t["ended"] is not None):
        return "dismissed"                                 # its turn ended without an answer
    return None


def open_question(r: Optional[Record]) -> Optional[dict]:
    """The oldest question codex asked while its turn goes on (request_user_input_async) that has questions not
    replied to, while that turn runs -- once it ends, they can no longer be answered as such:
    {call, at, questions: [{title, options: [label]}]}; None if none."""
    t = r.turn if r else None
    if not t or t["ended"] is not None:
        return None
    for call, ask in sorted(r.asks.items(), key=lambda kv: kv[1]["at"] or 0):
        if ask["name"] == ASK_ASYNC and ask["turn"] == t["id"] and len(r.replied.get(call, ())) < len(ask["questions"]):
            return {"call": call, "at": ask["at"], "questions": ask["questions"]}
    return None


def offer(r: Optional[Record]) -> Optional[dict]:
    """The plan the thread's last turn proposed in Plan mode -- which codex's terminal then asks whether to implement
    -- while no turn has begun since: {turn, at: when its turn completed, text}; None if none."""
    return dict(r.plan) if r and r.plan else None


def agents(r: Optional[Record]) -> List[dict]:
    """Its subagents that started and have not ended: [{id: its thread, path, started}]."""
    return [{"id": k, "path": a["path"], "started": a["started"]} for k, a in (r.agents.items() if r else ())
            if a["ended"] is None]


def report(r: Optional[Record], path: str) -> Optional[str]:
    """What the subagent at `path` (its agent path, "/root/count_a") that the thread started last answered, as its
    own record has it: its turn's last message, once the thread's record says it ended and its own that its turn did
    -- the report codex hands the thread with its next call (an `agent_message`), which may not come for a while.
    None: running, not known, or ended with nothing to say."""
    found = [(a["started"] or 0, k, a) for k, a in (r.agents.items() if r else ()) if a["path"] == path]
    if not found:
        return None
    _, thread, agent = max(found, key=lambda x: x[0])
    own = read(record(thread)) if agent["ended"] is not None else None
    t = own.turn if own else None
    return t["said"] if t and t["ended"] is not None and t["how"] == "complete" else None


def commands(r: Optional[Record]) -> List[dict]:
    """The commands it left running that have not ended: [{id: their process, label: the command, started}]."""
    return [{"id": k, "label": c["label"], "started": c["started"]} for k, c in (r.commands.items() if r else ())
            if c["ended"] is None]


def result(r: Optional[Record], call: Optional[str]) -> Optional[str]:
    """What codex recorded as the answer to `call` -- a question's output, an async question's replies, or the
    message the turn after a plan ("plan:<turn>") opened with -- None before it has."""
    got = r.results.get(call) if r and call else None
    return got[0] if got else None
