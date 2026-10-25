"""Telling whoever watches a gatherer that its database changed: a doorbell,
rung after each write commits, so a reader (the dashboard) can show the change
as it happens instead of polling the file.

A listener binds a Unix datagram socket in the home's `listeners/` folder
(`~/.ag/listeners/`, under AG_HOME), named `<anything>.sock`, and removes it
when it stops. Every write sends each socket there one datagram, a JSON object:

    {"v": 1, "gatherer": "making_ag", "what": "events", "properties": {"channel": "7bd5..."},
     "row": 1234, "at": 1761264000.123}

    what        what was written:
                  events    rows in `events` (an insert, a poll, a bulk load); `row`: the last one
                  pending   `_pending` rows kept or cleared
                  recap     a recap of a session kept in `_recaps`; `row`: its recap_id
                  read      a read logged in `_reads` (its made items with it); `row`: its read_id
                  counts    sizes recorded after a call (`record_counts`, `record_real_tokens`)
                  failed    a read's model call failed (`record_failed`); `row`: its read_id
                  build     a row of the policy's `_builds` claimed or settled; `row`: its build_id
                  tasks     the policy's tasks (and cleaned messages) saved
                  boundary  a task-boundary check claimed or decided; `row`: the message's row_id
                  llm       a Gatherer model call logged (logs/llm/); `row` absent
                a policy may name its own
    properties  the identifying properties of what was written (a channel's
                `channel`), as far as the writer knows them; {}: unknown, or the
                gatherer's (a poller's events), so check every channel
    row         a row id, as above; absent: none

It says only that something changed, never what: the listener reads that from
the database, which the write has committed before the datagram is sent. So a
lost datagram (a full socket buffer, a listener that started a moment later)
delays an update and never makes one wrong; a listener that must not miss one
also checks the file now and then.

Unix only: it needs AF_UNIX datagram sockets, which Windows does not have; there
it sends nothing, and a listener falls back to checking the file.

Sending never blocks and never raises. With no listeners it costs a listing of
an absent or empty folder. A socket nobody is bound to any more (its listener
died without removing it) is deleted.

This module knows no home: its caller names the folder (the harness's
ag_harness/store/notify.py, the model clients' call log).
"""

import errno
import json
import os
import socket
import threading
import time
from typing import Any, Dict, Optional

VERSION = 1
LISTENERS = "listeners"         # the folder in the home

_sock = None
_lock = threading.Lock()


def _socket() -> socket.socket:
    global _sock
    with _lock:
        if _sock is None:
            _sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            _sock.setblocking(False)
        return _sock


def message(gatherer_id: Optional[str], what: str, properties: Optional[Dict[str, Any]] = None,
            row: Optional[int] = None) -> dict:
    """The datagram's object (module doc)."""
    msg = {"v": VERSION, "gatherer": gatherer_id, "what": what,
           "properties": {k: v for k, v in (properties or {}).items() if v is not None}, "at": time.time()}
    if row is not None:
        msg["row"] = row
    return msg


def notify(listeners: str, gatherer_id: Optional[str], what: str, properties: Optional[Dict[str, Any]] = None,
           row: Optional[int] = None) -> int:
    """Send every listener in the folder `listeners` that `what` of `gatherer_id`
    (None: not known) was written (module doc). Call it after the write commits.
    How many listeners it reached."""
    if not listeners:
        return 0
    try:
        names = [e.name for e in os.scandir(listeners) if e.name.endswith(".sock")]
    except OSError:
        return 0
    if not names:
        return 0
    try:
        data = json.dumps(message(gatherer_id, what, properties, row), default=str).encode()
        sock = _socket()
    except (OSError, TypeError, ValueError, AttributeError):    # AttributeError: no AF_UNIX (Windows' Python)
        return 0
    sent = 0
    for name in names:
        path = os.path.join(listeners, name)
        try:
            sock.sendto(data, path)
            sent += 1
        except OSError as exc:
            if exc.errno == errno.ECONNREFUSED:          # nobody bound: its listener is gone
                try:
                    os.unlink(path)
                except OSError:
                    pass
            # anything else (ENOENT: removed meanwhile; EAGAIN: its buffer is full) is skipped
    return sent
