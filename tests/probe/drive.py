"""Driving a harness session through a dashboard as its page does (probe.py): its HTTP API, the session's terminal as
it streams (its text, escape sequences taken out), and what its gatherer then holds (read only)."""

import base64
import json
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Optional

COLS, ROWS = 150, 48
ESCAPES = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]|\x1b[@-Z\\-_]|[\x00-\x08\x0b-\x1f]")
FORWARD = re.compile(r"\x1b\[(\d*)C")
BUSY = ("running", "retrying", "asking")


def plain(raw: str) -> str:
    """A terminal's output as text: the cursor moved forward as spaces, every other escape sequence taken out."""
    return ESCAPES.sub("", FORWARD.sub(lambda m: " " * int(m.group(1) or 1), raw))


class Dashboard:
    def __init__(self, url: str, home: str, gatherer: str, log: Callable[[str], None] = print):
        self.url, self.home, self.gatherer, self.log = url, home, gatherer, log

    # ---- its API

    def post(self, path: str, body: dict) -> dict:
        req = urllib.request.Request(self.url + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "Origin": self.url})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            return {"http_error": e.code, "body": e.read().decode()[:500]}

    def get(self, path: str, **q):
        with urllib.request.urlopen(self.url + path + ("?" + urllib.parse.urlencode(q) if q else ""), timeout=60) as r:
            return json.load(r)

    def create(self, cwd: str, harness: str, permission_mode: str = "auto", model: Optional[str] = None) -> str:
        got = self.post("/api/sessions", {"gatherer": self.gatherer, "cwd": cwd, "harness": harness,
                                          "permission_mode": permission_mode, **({"model": model} if model else {})})
        if "session_id" not in got:
            raise RuntimeError(f"no session: {got}")
        return got["session_id"]

    def send(self, sid: str, text: str) -> dict:
        got = self.post("/api/send", {"session_id": sid, "text": text, "cols": COLS, "rows": ROWS, "fullscreen": True})
        if got.get("http_error"):
            self.log(f"send failed: {got}")
        return got

    def answer(self, sid: str, call: str, choice: dict) -> dict:
        got = self.post("/api/answer", {"session_id": sid, "call": call, "choice": choice})
        self.log(f"answer {json.dumps(choice)} -> {json.dumps(got)[:200]}")
        return got

    def stop(self, sid: str) -> dict:
        return self.post("/api/stop", {"session_id": sid})

    def sessions(self) -> list:
        return self.get("/api/sessions")

    def row(self, sid: str) -> dict:
        for g in self.get("/api/home")["gatherers"]:
            for a in g["agents"]:
                if a["channel"] == sid:
                    return a
        return {}

    def status(self, sid: str) -> Optional[str]:
        return self.row(sid).get("status")

    # ---- waiting on it

    def until(self, test: Callable[[], object], timeout: float, every: float = 0.4):
        end = time.time() + timeout
        while time.time() < end:
            began = time.time()
            got = test()
            if time.time() - began > 10:
                self.log(f"slow: one look took {time.time() - began:.0f} s")
            if got:
                return got
            time.sleep(every)
        return None

    def wait_status(self, sid: str, want, timeout: float = 120, quiet: float = 0.0) -> Optional[str]:
        want = (want,) if isinstance(want, str) else tuple(want)
        since = [None]

        def ok():
            if self.status(sid) in want:
                since[0] = since[0] or time.time()
                return time.time() - since[0] >= quiet
            since[0] = None
            return False
        self.until(ok, timeout)
        return self.status(sid)

    def wait_turn(self, sid: str, term: Optional["Term"] = None, timeout: float = 240, start: float = 30) -> Optional[str]:
        """A turn started and over (no longer running, retrying or asking for 3 s), its permission prompts allowed."""
        self.until(lambda: self.status(sid) in BUSY, start, 0.3)
        end, quiet = time.time() + timeout, None
        while time.time() < end:
            began = time.time()
            if term is not None:
                term.allow()
            if time.time() - began > 10:
                self.log(f"slow: reading the terminal took {time.time() - began:.0f} s")
            if self.status(sid) in BUSY:
                quiet = None
            else:
                quiet = quiet or time.time()
                if time.time() - quiet >= 3:
                    break
            time.sleep(0.5)
        return self.status(sid)

    def wait_asking(self, sid: str, kind: Optional[str] = None, timeout: float = 180, not_call: Optional[str] = None,
                    offer: bool = False) -> Optional[dict]:
        """What the actor asks (its `asking`; with `offer`, a plan codex offers too), of `kind`, not `not_call`."""
        def got():
            a = self.row(sid)
            for ask in (a.get("asking"), a.get("offer") if offer else None):
                if ask and (kind is None or ask.get("kind") == kind) and ask.get("call") != not_call:
                    return ask
            return None
        return self.until(got, timeout)

    # ---- its gatherer, read only

    def events(self, sid: str, types=None, after: int = 0) -> list:
        """[(row_id, type, payload)] of the session's channel."""
        try:
            conn = sqlite3.connect(f"file:{self.home}/gatherers/{self.gatherer}/context.db?mode=ro", uri=True, timeout=10)
        except sqlite3.Error:
            return []
        try:
            rows = conn.execute("SELECT e.row_id, t.name, e.payload_json FROM events e JOIN event_types t "
                                "USING (event_type_id) WHERE ifnull(e.p_channel, '') = ? AND e.row_id > ? ORDER BY e.row_id",
                                (sid, after)).fetchall()
        except sqlite3.Error:
            return []
        finally:
            conn.close()
        return [(r, t, json.loads(p)) for r, t, p in rows if types is None or t in types]

    def wait_event(self, sid: str, typ: str, test=lambda p: True, timeout: float = 60, after: int = 0):
        return self.until(lambda: next((p for _, t, p in self.events(sid, (typ,), after) if test(p)), None), timeout, 0.3)

    def last_row(self, sid: str) -> int:
        got = self.events(sid)
        return got[-1][0] if got else 0


class Term:
    """A session's terminal as the dashboard streams it (/api/terminal), kept as text: its output in chunks, each read
    only where it is needed -- a full screen's UI prints a great deal (its spinner redrawn several times a second)."""

    def __init__(self, dash: Dashboard, sid: str):
        self.dash, self.sid, self.lock = dash, sid, threading.Lock()
        self.raw: list = []            # its output, in the chunks it came in
        self.ends: list = []           # where each chunk ends, in characters of all of it
        self.at = -1                   # the end of what was had, as the dashboard counts it (its `at`)
        self.scanned = self.allowed = 0
        self.closed = False
        threading.Thread(target=self._listen, daemon=True).start()

    def _listen(self) -> None:
        while not self.closed:
            try:
                with urllib.request.urlopen(f"{self.dash.url}/api/terminal?session_id={self.sid}", timeout=120) as s:
                    for line in s:
                        if self.closed:
                            return
                        if line.startswith(b"data: "):
                            d = json.loads(line[6:])
                            if "data" in d:
                                self._add(base64.b64decode(d["data"]), d.get("at"), bool(d.get("reset")))
            except Exception:  # noqa: BLE001 - its terminal not open yet, or closed: tried again
                pass
            time.sleep(1)

    def _add(self, out: bytes, end, reset: bool) -> None:
        """A chunk of output: on a stream opened again, only what is new of it (all that is kept comes first)."""
        if isinstance(end, int) and self.at >= 0 and not reset:
            if end <= self.at:
                return
            out = out[-(end - self.at):]
        if isinstance(end, int):
            self.at = end
        text = out.decode("utf-8", "replace")
        with self.lock:
            self.raw.append(text)
            self.ends.append((self.ends[-1] if self.ends else 0) + len(text))

    def _from(self, mark: int) -> str:
        """Its raw output from `mark` (characters) on."""
        with self.lock:
            i = len(self.ends)
            while i > 0 and self.ends[i - 1] > mark:
                i -= 1
            got = "".join(self.raw[i:])
            start = self.ends[i - 1] if i else 0
        return got[max(0, mark - start):]

    def mark(self) -> int:
        with self.lock:
            return self.ends[-1] if self.ends else 0

    def text(self, tail: int = 20000) -> str:
        """Its last `tail` characters of text."""
        return plain(self._from(max(0, self.mark() - tail * 3)))[-tail:]

    def since(self, mark: int) -> str:
        """The text printed after `mark` (`mark()`)."""
        return plain(self._from(mark))

    def key(self, data: str, pause: float = 0.4) -> None:
        self.dash.post("/api/terminal/input", {"session_id": self.sid, "data": data})
        time.sleep(pause)

    def type(self, words: str, enter: bool = True) -> None:
        self.key(words[:1], 0.7)                      # a leading "!" or "/" switches the prompt's mode first
        if words[1:]:
            self.key(words[1:], 0.7)
        if enter:
            self.key("\r", 0.5)

    def squashed(self, tail: int = 4000) -> str:
        """Its text without its spaces: a terminal UI may move the cursor over them rather than print them."""
        return re.sub(r"\s+", "", self.text(tail))

    def wait(self, pattern: str, timeout: float = 30, tail: int = 4000) -> bool:
        """Until `pattern` (no spaces in it) matches its text without its spaces."""
        return bool(self.dash.until(lambda: re.search(pattern, self.squashed(tail)), timeout, 0.5))

    def allow(self) -> None:
        """A permission prompt printed since the last one answered, answered yes (Claude Code's "Do you want to ...",
        "1. Yes"): what came since it last looked read, a little before it too (a prompt may come in two chunks)."""
        end = self.mark()
        text = re.sub(r"\s+", "", self.since(max(self.allowed, self.scanned - 4000)))
        self.scanned = end
        if "Doyouwantto" in text and "1.Yes" in text:
            self.dash.log("permission prompt: yes")
            self.allowed = self.mark()
            self.key("\r", 1.5)

    def close(self) -> None:
        self.closed = True
