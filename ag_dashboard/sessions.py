"""Sessions started from the page: a headless agent per session, run through ag, that the page
sends messages to. Each is an ordinary ag session -- a channel of its gatherer, shown like any
other actor -- and the dashboard's own table, `sessions` in <home>/dashboard.db, keeps which
ones it started:

    session_id       Claude Code's session id, which ag makes the gatherer's channel
    gatherer         the gatherer it joined (ag makes a new one on its first call)
    harness          "claude" (the only one for now)
    cwd              where the agent runs
    permission_mode  Claude Code's --permission-mode: auto (the default), acceptEdits, plan, ...
    created_at       when it was started (ISO, UTC)
    turns            how many of its turns have ended: after the first, a restart resumes it
    status           starting / running / idle / stopped / failed, as last seen
    last_error       why its last turn or process failed, if one did

The agent is one long-running process, `ag --gatherer G claude -p --input-format stream-json
--output-format stream-json ...`: each message is a line on its stdin, a turn, and each turn
ends with a `result` line on its stdout. A message sent while a turn runs waits for it. A
process that is gone (it exited, the dashboard restarted) is started again on the next message,
resuming the session (`--resume`) once it has had a turn. What the agent said is not kept here:
the page reads it from the gatherer, like every actor's history. Its stderr, and every line it
printed, go to <home>/logs/dashboard/<session_id>.log.

A new gatherer, with no session yet, is made by `ag new <name>` (`new_gatherer`).

ag is run as a command (AG_COMMAND, else `ag` on the PATH), never imported."""

import json
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional
from urllib.parse import urlsplit

from . import home

HARNESSES = ("claude",)
PERMISSION_MODES = ("auto", "acceptEdits", "plan", "bypassPermissions", "dontAsk", "manual")
GATHERER = re.compile(r"[A-Za-z0-9._-]+")      # the names ag takes
# What says the dashboard itself runs inside a Claude Code session; its agents are sessions of their own.
PARENT_SESSION = ("CLAUDECODE", "CLAUDE_PID", "CLAUDE_EFFORT", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_SESSION_ID",
                  "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN", "CLAUDE_CODE_SESSION_ATTENDED",
                  "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_EXECPATH")

SCHEMA = """CREATE TABLE IF NOT EXISTS sessions (
    session_id      TEXT PRIMARY KEY,
    gatherer        TEXT NOT NULL,
    harness         TEXT NOT NULL,
    cwd             TEXT NOT NULL,
    permission_mode TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    turns           INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL,
    last_error      TEXT
)"""
COLUMNS = ("session_id", "gatherer", "harness", "cwd", "permission_mode", "created_at", "turns", "status", "last_error")


class SessionError(ValueError):
    """A request the sessions cannot take: the page shows its text."""


def db_path() -> str:
    return os.path.join(home.HOME, "dashboard.db")


def log_path(session_id: str) -> str:
    return os.path.join(home.HOME, "logs", "dashboard", f"{session_id}.log")


def stored() -> List[dict]:
    """The sessions the table has, newest first, read-only: [] when there is no table yet."""
    if not os.path.exists(db_path()):
        return []
    conn = sqlite3.connect(f"file:{db_path()}?mode=ro", uri=True, timeout=8)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(f"SELECT {', '.join(COLUMNS)} FROM sessions ORDER BY created_at DESC")]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def ag_command() -> List[str]:
    """How ag is run: AG_COMMAND (split as a shell would), else `ag` on the PATH."""
    given = os.environ.get("AG_COMMAND")
    if given:
        return shlex.split(given)
    found = shutil.which("ag")
    if not found:
        raise SessionError("no `ag` on the PATH to run the agent with (set AG_COMMAND)")
    return [found]


def agent_env(environ: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """The environment an agent runs in: the dashboard's, less what says the dashboard runs inside
    a Claude Code session -- that session's own variables, and its API pointed at a hook server ag
    started, which ag refuses to hook again -- and with the dashboard's home as ag's."""
    env = {k: v for k, v in (os.environ if environ is None else environ).items() if k not in PARENT_SESSION}
    url = env.get("ANTHROPIC_BASE_URL")
    if url:
        parts = urlsplit(url)
        ports = {s.get("port") for s in home.hook_servers()}
        if parts.hostname in ("127.0.0.1", "localhost") and (parts.port in ports or "/h/" in parts.path):
            env.pop("ANTHROPIC_BASE_URL")
    env["AG_HOME"] = home.HOME
    return env


def new_gatherer(name: str) -> dict:
    """A new gatherer named `name`, made by `ag new` with ag's default policy and pollers: {name}.
    Refused when one has the name already."""
    name = (name or "").strip()
    if not GATHERER.fullmatch(name):
        raise SessionError("a gatherer's name may hold letters, digits, '.', '_' and '-' only")
    if os.path.isdir(home.gatherer_dir(name)):
        raise SessionError(f"there is a gatherer {name} already")
    try:
        done = subprocess.run([*ag_command(), "new", name], env=agent_env(), capture_output=True, text=True,
                              timeout=60, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        raise SessionError(f"could not run ag: {exc}") from exc
    if done.returncode != 0:
        raise SessionError((done.stderr or done.stdout).strip() or f"ag new exited {done.returncode}")
    return {"name": name}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class _Agent:
    """One session's running process and what waits for it."""

    def __init__(self, proc: subprocess.Popen, log):
        self.proc, self.log = proc, log
        self.busy = False               # a turn was sent and its result has not come back
        self.queue: List[str] = []      # messages waiting for the turn to end
        self.reader: Optional[threading.Thread] = None


class Sessions:
    """The sessions started from the page, and their agents. Thread-safe: the server's handlers
    share one. `on_change(gatherer, session_id)` is told each time a session's state changes (the
    server rings its streams with it)."""

    def __init__(self, on_change: Optional[Callable[[str, str], None]] = None):
        self.on_change = on_change
        self.lock = threading.RLock()
        self.agents: Dict[str, _Agent] = {}
        conn = self._db()               # a process from before is gone: what it was running stopped
        try:
            conn.execute("UPDATE sessions SET status = 'stopped' WHERE status IN ('starting', 'running', 'idle')")
        finally:
            conn.close()

    def _db(self) -> sqlite3.Connection:
        os.makedirs(home.HOME, exist_ok=True)
        conn = sqlite3.connect(db_path(), timeout=8, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute(SCHEMA)
        return conn

    def _row(self, session_id: str) -> Optional[dict]:
        conn = self._db()
        try:
            r = conn.execute(f"SELECT {', '.join(COLUMNS)} FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
            return dict(r) if r else None
        finally:
            conn.close()

    def _set(self, session_id: str, **values) -> None:
        conn = self._db()
        try:
            conn.execute(f"UPDATE sessions SET {', '.join(k + ' = ?' for k in values)} WHERE session_id = ?",
                         (*values.values(), session_id))
            row = conn.execute("SELECT gatherer FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        finally:
            conn.close()
        if row is not None:
            self._changed(row["gatherer"], session_id)

    def _changed(self, gatherer: str, session_id: str) -> None:
        if self.on_change is not None:
            try:
                self.on_change(gatherer, session_id)
            except Exception:  # noqa: BLE001 - a listener's trouble is not the session's
                pass

    def list(self) -> List[dict]:
        """Every session the table has, newest first, each with `queued`: its messages waiting."""
        with self.lock:
            out = []
            for s in stored():
                a = self.agents.get(s["session_id"])
                out.append({**s, "queued": list(a.queue) if a else []})
            return out

    def create(self, gatherer: str, cwd: str, permission_mode: str = "auto", harness: str = "claude") -> dict:
        """A new session in `gatherer` (a new gatherer if none has the name), to run in `cwd`. Its agent
        starts with its first message."""
        gatherer = (gatherer or "").strip()
        if not GATHERER.fullmatch(gatherer):
            raise SessionError("a gatherer's name may hold letters, digits, '.', '_' and '-' only")
        cwd = os.path.abspath(os.path.expanduser((cwd or "").strip() or "."))
        if not os.path.isdir(cwd):
            raise SessionError(f"no directory {cwd}")
        if permission_mode not in PERMISSION_MODES:
            raise SessionError(f"permission mode {permission_mode!r}: one of {', '.join(PERMISSION_MODES)}")
        if harness not in HARNESSES:
            raise SessionError(f"harness {harness!r}: only {', '.join(HARNESSES)} for now")
        session_id = str(uuid.uuid4())
        conn = self._db()
        try:
            conn.execute(f"INSERT INTO sessions ({', '.join(COLUMNS)}) VALUES (?, ?, ?, ?, ?, ?, 0, 'stopped', NULL)",
                         (session_id, gatherer, harness, cwd, permission_mode, _now()))
        finally:
            conn.close()
        self._changed(gatherer, session_id)
        return self._row(session_id)

    def send(self, session_id: str, text: str) -> dict:
        """The message to the session's agent: a turn now, or, while one runs, after it. Starts the
        agent if it is not running. The session as `list` has it."""
        text = (text or "").strip()
        if not text:
            raise SessionError("an empty message")
        with self.lock:
            s = self._row(session_id)
            if s is None:
                raise SessionError(f"no session {session_id} started from the dashboard")
            a = self.agents.get(session_id)
            if a is None or a.proc.poll() is not None:
                a = self._start(s)
            a.queue.append(text)
            if not a.busy:
                self._next(session_id, a)
            else:
                self._changed(s["gatherer"], session_id)        # it waits: shown as waiting
            return next(x for x in self.list() if x["session_id"] == session_id)

    def _start(self, s: dict) -> _Agent:
        sid = s["session_id"]
        argv = [*ag_command(), "--gatherer", s["gatherer"], s["harness"], "-p",
                "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
                "--permission-mode", s["permission_mode"], "--permission-prompts", "none",
                *(["--resume", sid] if s["turns"] else ["--session-id", sid])]
        os.makedirs(os.path.dirname(log_path(sid)), exist_ok=True)
        log = open(log_path(sid), "a", encoding="utf-8", buffering=1)
        log.write(f"--- {_now()} {shlex.join(argv)}\n")
        try:
            proc = subprocess.Popen(argv, cwd=s["cwd"], env=agent_env(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=log, text=True, bufsize=1, start_new_session=True)
        except OSError as exc:
            log.close()
            self._set(sid, status="failed", last_error=f"could not run ag: {exc}")
            raise SessionError(f"could not run ag: {exc}") from exc
        a = _Agent(proc, log)
        self.agents[sid] = a
        self._set(sid, status="starting", last_error=None)
        a.reader = threading.Thread(target=self._read, args=(sid, a), daemon=True)
        a.reader.start()
        return a

    def _next(self, session_id: str, a: _Agent) -> None:
        """The next waiting message to the agent, as a turn (the lock held)."""
        if not a.queue:
            return
        text = a.queue.pop(0)
        try:
            a.proc.stdin.write(json.dumps({"type": "user", "message": {"role": "user", "content": text}}) + "\n")
            a.proc.stdin.flush()
        except (OSError, ValueError) as exc:
            a.queue.insert(0, text)
            self._set(session_id, status="failed", last_error=f"the agent is gone: {exc}")
            return
        a.busy = True
        self._set(session_id, status="running")

    def _read(self, session_id: str, a: _Agent) -> None:
        """The agent's stdout, until it exits: each turn's end, and the next waiting message sent."""
        for line in a.proc.stdout:
            a.log.write(line)
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict) or event.get("type") != "result":
                continue
            with self.lock:
                a.busy = False
                s = self._row(session_id) or {"turns": 0}
                error = None if event.get("subtype") == "success" and not event.get("is_error") \
                    else str(event.get("result") or event.get("subtype") or "the turn failed")[:2000]
                self._set(session_id, turns=s["turns"] + 1, status="idle", last_error=error)
                self._next(session_id, a)
        code = a.proc.wait()
        for pipe in (a.proc.stdin, a.proc.stdout):
            try:
                pipe.close()
            except OSError:
                pass
        with self.lock:
            a.log.write(f"--- {_now()} exited {code}\n")
            a.log.close()
            if self.agents.get(session_id) is a:
                del self.agents[session_id]
                waiting = bool(a.queue)
                self._set(session_id, status="stopped" if code == 0 and not a.busy else "failed",
                          **({} if code == 0 and not a.busy else
                             {"last_error": f"the agent exited ({code}); see {log_path(session_id)}"}))
                if waiting:                  # messages sent while it was ending: a new process takes them
                    s = self._row(session_id)
                    try:
                        b = self._start(s)
                        b.queue = a.queue
                        self._next(session_id, b)
                    except SessionError:
                        pass

    def close(self) -> None:
        """Every agent's stdin closed, so each ends after its turn; any still running after 5 s is
        stopped. Returns once each one's end is recorded."""
        with self.lock:
            agents = list(self.agents.values())
            for a in agents:
                a.queue.clear()          # nothing more to send: not started again
        for a in agents:
            try:
                a.proc.stdin.close()
            except OSError:
                pass
        for a in agents:
            try:
                a.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                a.proc.terminate()
        for a in agents:
            if a.reader is not None:
                a.reader.join(timeout=5)
