"""The dashboard's own actions on a session, kept in its gatherer as events of the session -- put in by ag (`ag home
insert`), as naming.py keeps a name -- so what the harness then did can be checked against what the reader did:

    chat_sent        text: a message sent from Chat (typed into the session's terminal, or held for its next turn);
                     shown as pending until the harness has it (data.py's `typed`)
    answer_given     call, summary, expect: an answer to what the harness asks, typed into its terminal; what it
                     records is checked against `expect` (data.py's `answer_of`)
    terminal_input   keys typed into the session's terminal from the page: the first after QUIET_SECONDS of none --
                     what the check that nothing was typed since a question was asked needs (sessions.py's `answer`)

Each has an id of its own, made when the action is taken, and its time (`at`). Each is put in in the background: the
action is never held up for it, and a failure is a line in the dashboard's log, never in the reader's way. Only a
dashboard that serves a page keeps them (`ENABLED`, server.py's): a test's sessions keep none."""

import json
import subprocess
import sys
import threading
import time
import uuid
from typing import Dict, List, Optional, Tuple

CHAT_SENT, ANSWER_GIVEN, TERMINAL_INPUT = "chat_sent", "answer_given", "terminal_input"
ACTIONS = (CHAT_SENT, ANSWER_GIVEN, TERMINAL_INPUT)
QUIET_SECONDS = 2.0             # keys typed after this long with none: another terminal_input
ENABLED = False                 # set by the server (server.py) that runs the page

_typed: Dict[Tuple[str, str], float] = {}     # (gatherer, channel) -> when keys were last typed there
_lock = threading.Lock()


def _event(kind: str, **payload) -> dict:
    return {"type": kind, "id": f"{kind}:{uuid.uuid4().hex}", "payload": {"at": time.time(), **payload}}


def record(gatherer: Optional[str], channel: Optional[str], events: List[dict], wait: bool = False) -> None:
    """`events` put in the actor's channel by ag (`ag home insert`), in the background (`wait`: before returning)."""
    if not ENABLED or not gatherer or not channel or not events:
        return

    def put() -> None:
        from . import sessions                        # sessions.py records through here
        try:
            done = subprocess.run([*sessions.ag_command(), "home", "insert", gatherer, "--properties",
                                   json.dumps({"channel": channel}), "--events", json.dumps(events)],
                                  env=sessions.agent_env(), capture_output=True, text=True, timeout=60,
                                  stdin=subprocess.DEVNULL)
            if done.returncode:
                raise RuntimeError((done.stderr or done.stdout).strip()[-300:] or f"exited {done.returncode}")
        except Exception as exc:  # noqa: BLE001 - never in the reader's way
            print(f"dashboard: {', '.join(e['type'] for e in events)} not kept for {channel}: {exc}", file=sys.stderr,
                  flush=True)

    if wait:
        put()
    else:
        threading.Thread(target=put, name="dashboard-action", daemon=True).start()


def chat_sent(gatherer: str, channel: str, text: str) -> None:
    record(gatherer, channel, [_event(CHAT_SENT, text=text)])


def answer_given(gatherer: str, channel: str, sent: dict) -> None:
    """`sent`: the answer as sessions.py's `answer` gives it -- {call, summary, expect, at}."""
    record(gatherer, channel, [_event(ANSWER_GIVEN, **{k: sent.get(k) for k in ("call", "summary", "expect")})])


def terminal_input(gatherer: Optional[str], channel: str, now: Optional[float] = None) -> None:
    """Keys typed into the session's terminal: recorded once QUIET_SECONDS passed with none."""
    now = time.time() if now is None else now
    with _lock:
        last, _typed[(gatherer or "", channel)] = _typed.get((gatherer or "", channel)), now
    if last is None or now - last >= QUIET_SECONDS:
        record(gatherer, channel, [_event(TERMINAL_INPUT)])
