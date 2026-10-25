"""What each tool call of a session did to files, found on disk as the calls run -- not told from
what the calls say alone -- and kept in the gatherer's database (`_touches`) for the dashboard's
Files view. Run by the proxy hooks (the Claude Code and codex hooks), which see each answer end
before the harness runs its calls, and the results come back in the next call:

    an answer of the session's ends,            `Files.started`: the files its calls name, looked at
    before the harness has it                   as they are (check.py's `before`); the session's
                                                directory watched (watch.py), the changes it reports
                                                taken from when the answer began to come back -- a
                                                harness may run a call as soon as it has streamed
                                                in, before the answer ends
    the session's next call, the results        `Files.arrived`: in the background, a moment later,
    of those calls in it                        each call checked (check.py's `check`): what it read
                                                and changed, where the files say so -- and sent to
                                                the gatherer's server (its `touches`)

    commands.py   a call read: the files a shell command reads and changes, as it says
    check.py      the same, against the disk: what is kept, what changed, at which lines
    watch.py      the files that change under a directory, as the operating system reports them
    calls.py      the tool calls and results in either harness's messages

Nothing here holds up a model call: the files a finished answer names are looked at before the
harness is given its end (a few files, each read once, at most check.MAX_BYTES), and everything else
runs after the call has gone on. Nothing raises into the hook: a failure is a line in its log."""
import asyncio
import time
from collections import OrderedDict
from typing import Callable, Dict, List, Optional, Tuple

from . import check
from .calls import calls_in, last_results, results_in
from .watch import LAG, Watcher

SETTLE = 0.3                # seconds after a call's results arrive before they are checked: the watcher's
                            # last reports of what the calls changed, to come in (macOS's come in ~20 ms)
SEEN_FILES = 256            # the files whose lines, as last seen, are kept: a change to one no call names
SEEN_BYTES = 32 << 20       # is shown at its lines


class Files:
    """The hook's: `started` as an answer ends, `arrived` as the session's next call comes in.

    Args:
        ag_clients: the server client per gatherer (the hook's own).
        log: (gatherer, line) -> None.
        watcher: what reports the files changed (watch.Watcher by default; None: none watched).
    """

    def __init__(self, ag_clients, log: Callable[[str, str], None], watcher: Optional[Watcher] = ...):
        self.ag_clients, self.log = ag_clients, log
        self.watcher = Watcher(log=lambda line: log("files", line)) if watcher is ... else watcher
        self.open: Dict[Tuple[str, str], dict] = {}     # (gatherer, channel) -> the answer whose calls run
        self.seen: "OrderedDict[str, List[str]]" = OrderedDict()
        self.tasks = set()

    def started(self, gatherer: str, channel: str, cwd: Optional[str], items, since: Optional[float] = None) -> None:
        """An answer of the session's has come back whole, the harness not given its end yet: the files
        its calls name, as they are before the calls run; `since`, when the answer began to come back
        (None: now) -- the changes reported from then on are its calls'."""
        try:
            calls = calls_in(items)
            if not calls:
                self.open.pop((gatherer, channel), None)
                return
            self.open[(gatherer, channel)] = {"at": since or time.time(), "calls": calls, "cwd": cwd,
                                              "was": check.before(calls, cwd)}
            if self.watcher is not None:
                self.watcher.watch(cwd)
        except Exception as exc:  # noqa: BLE001 - never in the way of the answer
            self.log(gatherer, f"[{channel}] files: not looked at before the calls ran: {exc!r}")

    def arrived(self, gatherer: str, channel: str, cwd: Optional[str], messages) -> None:
        """A call of the session's has come in: the results of its last answer's calls are in it, and
        are checked in the background. With no answer seen end (the hook began since), the results
        the messages end with are checked -- what they read, not what they changed."""
        try:
            opened = self.open.pop((gatherer, channel), None)
            results = results_in(messages)
            if opened:
                calls = opened["calls"]
                ids = [i for i in calls if i in results]
                cwd = opened["cwd"] or cwd
            else:
                calls = calls_in(messages)
                ids = [i for i in last_results(messages) if i in calls]
            if not ids:
                return
            entries = [(i, calls[i][0], calls[i][1], results[i][0], results[i][1]) for i in ids]
            task = asyncio.ensure_future(self._check(gatherer, channel, cwd, entries, opened, time.time()))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
        except Exception as exc:  # noqa: BLE001
            self.log(gatherer, f"[{channel}] files: not checked: {exc!r}")

    async def _check(self, gatherer: str, channel: str, cwd: Optional[str], entries: list, opened: Optional[dict],
                     arrived: float) -> None:
        try:
            await asyncio.sleep(SETTLE)
            touches = await asyncio.to_thread(self.touches, cwd, entries, opened, arrived + SETTLE)
            got = await self.ag_clients.client(gatherer).request(
                "touches", {"gatherer": gatherer, "session": channel, "touches": touches})
            files = len({t["path"] for t in touches if t.get("path")})
            self.log(gatherer, f"[{channel}] files: {len(entries)} calls checked, {files} files: "
                               + (f"{got.get('kept')} kept" if isinstance(got, dict) and "kept" in got else f"{got}"))
        except Exception as exc:  # noqa: BLE001
            self.log(gatherer, f"[{channel}] files: not checked: {exc!r}")

    def touches(self, cwd: Optional[str], entries: list, opened: Optional[dict], until: float) -> List[dict]:
        """What the calls did to files (check.check), the changes the watcher saw from when the answer
        began to `until` among them; the lines of each file they touched kept, as now seen.
        A file looked at as the answer ended may have been changed already, since it began: Claude Code
        runs a call as soon as it has streamed in. Its look is then not what it was before the calls
        (its modification time says so): the lines it had when last seen are taken in its place (the
        result of an earlier call), or none -- changed, at lines not known."""
        watched = self.watcher.between(opened["at"], until) if opened and self.watcher is not None else {}
        was = dict(opened["was"]) if opened else {}
        for path, look in list(was.items()):
            if look is None or look.mtime < opened["at"] - LAG:
                continue
            del was[path]                                  # changed by a call run as it streamed in
            if look.birth is not None and look.birth >= opened["at"] - LAG:
                watched[path] = "created"
            else:
                watched.setdefault(path, "modified")
        out = check.check(entries, cwd, was, watched, self.seen)
        for path in {t["path"] for t in out if t.get("path")}:
            now = check.look(path)
            self.seen.pop(path, None)
            if now is not None and now.lines is not None:
                self.seen[path] = now.lines
        size = sum(len(t) + 1 for lines in self.seen.values() for t in lines)
        while self.seen and (size > SEEN_BYTES or len(self.seen) > SEEN_FILES):   # the newest kept
            _, lines = self.seen.popitem(last=False)
            size -= sum(len(t) + 1 for t in lines)
        return out

    async def close(self) -> None:
        """Let checks under way finish; stop watching."""
        if self.tasks:
            await asyncio.gather(*list(self.tasks), return_exceptions=True)
        if self.watcher is not None:
            self.watcher.close()

