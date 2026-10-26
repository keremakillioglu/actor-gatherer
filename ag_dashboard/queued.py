"""What the user writes to Claude Code while it works: the messages it has not yet sent the model, and
the ones it sent in the middle of a turn.

Claude Code keeps a message written during a turn in a queue, and writes each change of the queue to
its own record of the session (<its config dir>/projects/<the session's directory, each character but
a letter or a digit made '-'>/<session>.jsonl) the moment it happens, a line
{"type": "queue-operation", "operation", "timestamp", "content"}: "enqueue" when the message is
written; "remove", with reason "absorbed_mid_turn", when it goes to the model with the turn's next
call (wrapped: MID_TURN), or "dequeue" when the turn ended first and it opens the next. ag hears of it
only with that call, which can be minutes later, after a long command; and its notes (a background
task's end, a subagent's report as it hands back: NOTES) are queued too, in the user's name.

A message written between turns is not queued: Claude Code sends it at once, as the next turn's first,
and records it then as a line {"type": "user", "origin": {"kind": "human"}, "timestamp", "message"} (a
note's origin is of another kind; a "!" command's line has none, and calls no model). ag stores it only
once the gatherer's server takes up its call, which can be seconds later, behind other sessions' calls.

    typed(session)   the queue as it stands: [{text, at, sent, joins}] -- the messages not sent yet (`sent`
                     None), and the ones sent in the last SENT_SECONDS (`sent`: when), which ag may not
                     have stored yet; `joins`: sent as part of the turn it was written in (mid-turn, or held
                     until it ended), not as the next turn's first -- and the messages sent between turns in
                     the last PROMPT_SECONDS, each the next turn's first (`sent` its `at`)
    meanwhile(session)  the messages written while a turn ran that Claude Code held until it ended, and
                     sent then, unwrapped, as the next request's: [{text, sent}] -- part of that turn too
    mid_turn(text)   the message a user message is, if it is one sent mid-turn (else None)
    Watcher          every POLL_SECONDS, the queue of each session a page shows: its streams rung on a change

A record is read from where it was last read, so a long one costs only its new lines. Claude Code's wording is
harness_kit.claude's; each message is given as the user typed it (`words_of`)."""
import glob
import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from harness_kit import claude as claude_rules

SENT_SECONDS = 30.0
PROMPT_SECONDS = 120.0          # a message sent between turns, until ag stores it (data.py's `typed` drops it then)
POLL_SECONDS = 0.25
PROMPTS_KEPT = 20
BUSY_SECONDS = 1.0              # held longer than this: written while a turn ran (one written between turns goes at once)
CHUNK = 1 << 22                 # a record is read this much at a time
NOTES = claude_rules.QUEUED_NOTES          # its own notes, queued in the user's name (harness_kit.claude's)
MID_TURN = claude_rules.MID_TURN           # a message sent mid-turn, as Claude Code wraps it for the model
mid_turn = claude_rules.mid_turn           # the user's message, if a text is one Claude Code sent mid-turn; else None


class _Read:
    """A record as read so far: where it was read to, and its queue then."""

    def __init__(self, ino):
        self.ino, self.at, self.queue = ino, 0, []      # [{text, at, sent, how, note}], in the order queued
        self.prompts: List[dict] = []                   # [{text, at}], the latest PROMPTS_KEPT sent between turns


_LOCK = threading.Lock()
_READS: Dict[str, _Read] = {}
_FOUND: Dict[tuple, str] = {}                      # (config dir, session) -> its record, found without its directory
_NO_RECORD: Dict[tuple, float] = {}                # (config dir, session) -> when no record of it was found anywhere
NO_RECORD_SECONDS = 60


def record(session: str, cwd: Optional[str] = None) -> Optional[str]:
    """Claude Code's record of the session: under its directory's folder, else wherever it is -- a search of every
    folder, not made again for NO_RECORD_SECONDS once it found none (asked on every update of the page for each
    agent shown: one of another machine has none); None if none."""
    config = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    if cwd:
        path = os.path.join(config, "projects", re.sub(r"[^A-Za-z0-9]", "-", cwd), f"{session}.jsonl")
        if os.path.isfile(path):
            return path
    key = (config, session)
    known = _FOUND.get(key)
    if known and os.path.isfile(known):
        return known
    if time.time() - _NO_RECORD.get(key, 0) < NO_RECORD_SECONDS:
        return None
    found = glob.glob(os.path.join(glob.escape(config), "projects", "*", glob.escape(session) + ".jsonl"))
    if found:
        _FOUND[key] = found[0]
    else:
        if len(_NO_RECORD) > 1000:
            _NO_RECORD.clear()
        _NO_RECORD[key] = time.time()
    return found[0] if found else None


def _seconds(stamp) -> Optional[float]:
    try:
        got = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (got if got.tzinfo else got.replace(tzinfo=timezone.utc)).timestamp()


def _text(content) -> Optional[str]:
    if isinstance(content, str):
        return content
    if isinstance(content, list):                  # a message with an image: its words
        return "\n".join(b["text"] for b in content if isinstance(b, dict) and isinstance(b.get("text"), str)) or None
    return None


def _take(r: _Read, line: bytes) -> None:
    """One line of a record, if it changes the queue or is a message sent between turns: `r` changed by it."""
    try:
        op = json.loads(line)
    except ValueError:
        return
    if not isinstance(op, dict):
        return
    if op.get("type") == "user":
        return _prompt(r, op)
    if op.get("type") != "queue-operation":
        return
    queue = r.queue
    kind, text, at = op.get("operation"), _text(op.get("content")), _seconds(op.get("timestamp"))
    waiting = [q for q in queue if q["sent"] is None]
    if kind == "enqueue" and text is not None:
        queue.append({"text": text, "at": at, "sent": None, "how": None, "note": text.lstrip().startswith(NOTES)})
    elif kind == "dequeue" and waiting:            # the first in: it opens the next turn
        waiting[0].update(sent=at, how="next")
    elif kind == "remove":
        q = next((q for q in waiting if q["text"] == text), None)
        if q is not None and op.get("reason") == "absorbed_mid_turn":
            q.update(sent=at, how="mid_turn")
        elif q is not None:                        # taken back, or delivered as Claude Code's own
            queue.remove(q)


def _prompt(r: _Read, line: dict) -> None:
    """A user line: kept, if it is a message the user sent between turns (module doc) -- not one the queue
    has already as dequeued, which Claude Code records again as it sends it."""
    origin = line.get("origin")
    if not isinstance(origin, dict) or origin.get("kind") != "human" or line.get("isMeta") or line.get("isSidechain"):
        return
    message = line.get("message")
    text, at = _text(message.get("content") if isinstance(message, dict) else None), _seconds(line.get("timestamp"))
    if text is None or at is None:
        return
    if any(q["how"] == "next" and q["text"] == text and q["sent"] is not None and abs(at - q["sent"]) <= BUSY_SECONDS
           for q in r.queue):
        return
    r.prompts.append({"text": text, "at": at})
    del r.prompts[:-PROMPTS_KEPT]


def _read(path: str) -> Tuple[List[dict], List[dict]]:
    """The record's queue, and the messages sent between turns, read on from where it was read to."""
    try:
        st = os.stat(path)
    except OSError:
        return [], []
    with _LOCK:
        r = _READS.get(path)
        if r is None or r.ino != st.st_ino or st.st_size < r.at:      # new, or written anew: from its start
            r = _READS[path] = _Read(st.st_ino)
        try:
            with open(path, "rb") as fh:
                fh.seek(r.at)
                while r.at < st.st_size:
                    chunk = fh.read(min(CHUNK, st.st_size - r.at))
                    end = chunk.rfind(b"\n") + 1               # a line still being written: read with the next
                    if not end:
                        if len(chunk) < CHUNK:
                            break
                        end = len(chunk)                       # a line longer than CHUNK: not one of the queue's
                    for line in chunk[:end].split(b"\n"):
                        if b'"queue-operation"' in line or b'"human"' in line:
                            _take(r, line)
                    r.at += end
                    fh.seek(r.at)
        except OSError:
            pass
        return [dict(q) for q in r.queue], [dict(p) for p in r.prompts]


def typed(session: str, cwd: Optional[str] = None, now: Optional[float] = None) -> List[dict]:
    """What the user wrote to the session while it worked, and sent between turns (module doc): [{text, at, sent,
    joins}], oldest first."""
    path = record(session, cwd)
    if path is None:
        return []
    now = time.time() if now is None else now
    queue, prompts = _read(path)
    said = lambda text: claude_rules.words_of(text)[1]          # noqa: E731 - as the user typed it
    got = [{"text": said(q["text"]), "at": q["at"], "sent": q["sent"], "joins": _joins(q)} for q in queue
           if not q["note"] and (q["sent"] is None or now - q["sent"] <= SENT_SECONDS)]
    got += [{"text": said(p["text"]), "at": p["at"], "sent": p["at"], "joins": False} for p in prompts
            if now - p["at"] <= PROMPT_SECONDS]
    return sorted(got, key=lambda q: q["at"] or 0)


def _held(q: dict) -> bool:
    """Whether a message sent when a turn ended was written while it ran: held, not sent at once."""
    return q["how"] == "next" and q["at"] is not None and q["sent"] is not None and q["sent"] - q["at"] > BUSY_SECONDS


def _joins(q: dict) -> bool:
    return q["how"] == "mid_turn" or _held(q)


def meanwhile(session: str, cwd: Optional[str] = None) -> List[dict]:
    """The messages written while a turn ran that Claude Code sent when it ended (module doc): [{text, sent}], in order."""
    path = record(session, cwd)
    return [{"text": q["text"], "sent": q["sent"]} for q in (_read(path)[0] if path else []) if _held(q) and not q["note"]]


class Watcher:
    """Every `seconds`, what was written to each session the hub's streams show (`hub.shown()`, live.py's):
    each stream showing one whose queue changed, rung."""

    def __init__(self, hub, seconds: float = POLL_SECONDS):
        self.hub, self.seconds = hub, seconds
        self.last: Dict[tuple, list] = {}
        self.stop = threading.Event()
        threading.Thread(target=self._run, name="ag-queued", daemon=True).start()

    def check(self) -> None:
        now, seen = time.time(), {}
        for gatherer, channel in self.hub.shown():
            got = [(q["text"], q["sent"] is None) for q in typed(channel, now=now)]
            seen[(gatherer, channel)] = got
            if got != self.last.get((gatherer, channel), []):
                self.hub.ring(gatherer, channel)
        self.last = seen

    def _run(self) -> None:
        while not self.stop.wait(self.seconds):
            try:
                self.check()
            except Exception:  # noqa: BLE001 - never stop watching
                pass

    def close(self) -> None:
        self.stop.set()
