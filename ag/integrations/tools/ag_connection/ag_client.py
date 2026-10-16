"""The harness side's client of the context manager's server, for hooks in
Python (ag_client.ts is the same for plugins in Node or Bun).

    client = AgClient(harness)                       # python -m ag.ag_harness.server
    answer = await client.request("rewrite", {"gatherer": ..., "messages": [...]})

Starts the server on first use, again if it has exited; sends one JSON line
per request on its stdin and matches each answer line on its stdout to its
request by id. The protocol is ag/ag_harness/server/__init__.py's; nothing
of the context manager is imported here. `harness` only names the server's log.

A request never raises: it returns the answer, or `{"error"}` when the server
exits, cannot start, keeps exiting (three starts in a minute), or does not
answer in time -- so a broken server never blocks a model call.

Environment: AG_PYTHON (default: this Python), AG_HOME (default ~/.ag). The
server's stderr goes to <home>/logs/<harness>_server.log.
"""

import asyncio
import itertools
import json
import os
import sys
import time
from typing import Dict, List, Optional

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))   # <root>/ag/integrations/tools/ag_connection/this file


def home() -> str:
    """The context manager's home, as the server will see it: AG_HOME, or ~/.ag."""
    return os.path.abspath(os.path.expanduser(os.environ.get("AG_HOME") or "~/.ag"))

TIMEOUT = 300.0
LIMIT = 1 << 30                                   # the longest line: a whole history, as JSON


class AgClient:
    """The server process for one harness, started on first use."""

    def __init__(self, harness: str, timeout: float = TIMEOUT, args: List[str] = ()):
        self.harness, self.timeout, self.args = harness, timeout, list(args)
        self.proc: Optional[asyncio.subprocess.Process] = None
        self.pending: Dict[int, asyncio.Future] = {}
        self.ids = itertools.count(1)
        self.starts: List[float] = []
        self.reader: Optional[asyncio.Task] = None

    @property
    def log(self) -> str:
        return os.path.join(home(), "logs", f"{self.harness}_server.log")

    def command(self) -> List[str]:
        python = os.environ.get("AG_PYTHON") or sys.executable
        return [python, "-m", "ag.ag_harness.server"] + self.args

    async def start(self) -> Optional[asyncio.subprocess.Process]:
        now = time.monotonic()
        self.starts = [t for t in self.starts if now - t < 60]
        if len(self.starts) >= 3:
            return None                           # exits at once, over and over: give up
        self.starts.append(now)
        os.makedirs(os.path.dirname(self.log), exist_ok=True)
        env = dict(os.environ, PYTHONPATH=os.pathsep.join(p for p in (REPO, os.environ.get("PYTHONPATH")) if p))
        with open(self.log, "ab") as log:
            try:
                proc = await asyncio.create_subprocess_exec(
                    *self.command(), cwd=REPO, env=env, stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE, stderr=log, limit=LIMIT)
            except OSError as exc:
                self.fail(f"server failed to start: {exc}")
                return None
        self.reader = asyncio.get_running_loop().create_task(self.read(proc))
        return proc

    async def read(self, proc) -> None:
        """Hand each answer line to the request waiting for its id; when the
        server's stdout ends, answer every request still waiting."""
        while True:
            try:
                line = await proc.stdout.readline()
            except (ValueError, asyncio.LimitOverrunError):
                continue
            if not line:
                break
            try:
                answer = json.loads(line)
            except ValueError:
                continue
            waiting = self.pending.pop(answer.get("id"), None) if isinstance(answer, dict) else None
            if waiting is not None and not waiting.done():
                waiting.set_result(answer)            # else: answered after its request timed out
        code = await proc.wait()
        if self.proc is proc:
            self.proc = None
        self.fail(f"server exited ({code}); see {self.log}")

    def fail(self, why: str) -> None:
        for rid, waiting in list(self.pending.items()):
            if not waiting.done():
                waiting.set_result({"id": rid, "error": why})
        self.pending.clear()

    async def request(self, op: str, body: Optional[dict] = None, timeout: Optional[float] = None) -> dict:
        """One request; the answer, or `{"error"}` -- never raises."""
        if self.proc is None or self.proc.returncode is not None:
            self.proc = await self.start()
        proc = self.proc
        if proc is None:
            return {"error": "the server keeps exiting; not restarted"}
        rid = next(self.ids)
        waiting = asyncio.get_running_loop().create_future()
        self.pending[rid] = waiting
        try:
            proc.stdin.write((json.dumps(dict(body or {}, id=rid, op=op), ensure_ascii=False) + "\n").encode("utf-8"))
            await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as exc:
            self.pending.pop(rid, None)
            return {"id": rid, "error": f"server gone: {exc}"}
        try:
            return await asyncio.wait_for(asyncio.shield(waiting), timeout or self.timeout)
        except asyncio.TimeoutError:
            self.pending.pop(rid, None)
            return {"id": rid, "error": f"no answer in {timeout or self.timeout:.0f} s"}

    async def stop(self) -> None:
        """Close the server's stdin: it finishes what it is answering and exits."""
        proc, self.proc = self.proc, None
        if proc is not None and proc.returncode is None:
            try:
                proc.stdin.close()
                await asyncio.wait_for(proc.wait(), 10)
            except (asyncio.TimeoutError, OSError):
                proc.kill()
