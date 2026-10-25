"""Which files change under the directories sessions work in, as the operating system reports them:
FSEvents on macOS (through watchdog), inotify on Linux (through the C library) -- neither needs
root. Each change is kept with when it was reported, for check.py to take those reported while an
answer's calls ran: a file a call changed without naming it (a script's output, a formatter's).

Left out: anything under a hidden directory (`.git`, `.venv`), `__pycache__` or `node_modules`, and
`~/Library` on macOS (its caches change all the time); directories themselves.

macOS watches a directory and everything under it as one, at no cost to set up, whatever its size.
inotify watches each directory by itself: setting up walks the tree once, in the background, and
gives up past MAX_DIRS directories or MAX_WALK_SECONDS (a home directory, a disk), or when the
system's limit on watches (fs.inotify.max_user_watches) is reached. That directory is then not
watched (`status` says why): the files the calls name are still compared before and after they run
(check.py). Elsewhere (no watchdog on macOS, another system) nothing is watched."""
import ctypes
import ctypes.util
import errno
import os
import select
import struct
import sys
import threading
import time
from collections import deque
from typing import Callable, Dict, Optional

KEEP_SECONDS = 600          # how long a change is kept: longer than any answer's calls take to run
KEEP_CHANGES = 200_000      # and at most this many
LAG = 0.02                  # how far a file's modification time may lag the clock (the kernel's coarse clock)
MAX_DIRS = 50_000           # inotify: the most directories one tree may have to be watched
MAX_WALK_SECONDS = 5.0      # inotify: the longest its walk may take
SKIP = {"__pycache__", "node_modules"}
LIBRARY = os.path.join(os.path.expanduser("~"), "Library")

Report = Callable[[str, str], None]          # (path, created/modified/deleted)


def skipped(path: str) -> bool:
    """Whether a change to `path` is left out: under a hidden directory, one of SKIP, or ~/Library."""
    if sys.platform == "darwin" and (path == LIBRARY or path.startswith(LIBRARY + os.sep)):
        return True
    return any(p.startswith(".") or p in SKIP for p in path.split(os.sep)[1:-1])


class Watcher:
    """The changes under every directory it was asked to watch, as reported, kept KEEP_SECONDS."""

    def __init__(self, log: Callable[[str], None] = lambda line: None):
        self.log = log
        self.lock = threading.Lock()
        self.changes: deque = deque()                  # (when, path, how)
        self.status: Dict[str, str] = {}               # root -> watched / too big / not watched: why
        self.given: Dict[str, str] = {}                # root, resolved -> as it was given: paths are reported
                                                       # as under it (macOS's /var is /private/var)
        self.backend = None
        self.tried = False

    def _backend(self):
        if not self.tried:
            self.tried = True
            try:
                self.backend = _FSEvents(self.report) if sys.platform == "darwin" else \
                    _Inotify(self.report, self.log) if sys.platform.startswith("linux") else None
            except Exception as exc:  # noqa: BLE001 - no watcher: the named files are still compared
                self.log(f"file changes are not watched: {exc!r}")
        return self.backend

    def watch(self, root: Optional[str]) -> None:
        """Watch `root` and everything under it, from now on (a root already watched, or under one: as
        it is). Never blocks long: inotify's walk runs in the background."""
        if not root or not os.path.isabs(root) or not os.path.isdir(root):
            return
        given, root = os.path.normpath(root), os.path.realpath(root)
        with self.lock:
            if any(root == r or root.startswith(r.rstrip(os.sep) + os.sep) for r in self.status):
                return
            self.status[root] = "starting"
            if given != root:
                self.given[root] = given
        backend = self._backend()
        if backend is None:
            self.status[root] = "not watched: no watcher on this system"
            return
        backend.add(root, lambda status: self.status.__setitem__(root, status))

    def report(self, path: str, how: str) -> None:
        if skipped(path):
            return
        for real, given in self.given.items():
            if path.startswith(real + os.sep):
                path = given + path[len(real):]
                break
        now = time.time()
        with self.lock:
            self.changes.append((now, path, how))
            while self.changes and (self.changes[0][0] < now - KEEP_SECONDS or len(self.changes) > KEEP_CHANGES):
                self.changes.popleft()

    def between(self, t0: float, t1: float) -> Dict[str, str]:
        """The files reported changed from `t0` to `t1` and there now, each as it came out: {path: created
        or modified}. What the system says of each is taken as no more than that it changed: FSEvents
        folds earlier flags into later events (a file appended to may come as created). So a file is
        created if it came to be since `t0` -- by its birth time where the system keeps one (macOS),
        else by inotify's report, which is exact -- and modified otherwise. Left out: a file not there
        now (a temporary file, mostly: a deletion a call names is found by comparing its files before
        and after it), and one that last changed before `t0` (by its modification time or its status's:
        a file moved keeps its modification time) -- a change from before, reported late (FSEvents may
        report one from just before its stream began)."""
        with self.lock:
            got = [(path, how) for when, path, how in self.changes if t0 <= when <= t1]
        reported: Dict[str, list] = {}
        for path, how in got:
            reported.setdefault(path, []).append(how)
        out: Dict[str, str] = {}
        for path, hows in reported.items():
            try:
                st = os.lstat(path)
            except OSError:
                continue
            if not os.path.isfile(path) or os.path.islink(path) or max(st.st_mtime, st.st_ctime) < t0 - LAG:
                continue
            born = getattr(st, "st_birthtime", None)
            new = born >= t0 - LAG if born is not None else hows[0] == "created"
            out[path] = "created" if new else "modified"
        return out

    def close(self) -> None:
        if self.backend is not None:
            self.backend.close()


class _FSEvents:
    """macOS: one FSEvents stream per root, through watchdog."""

    def __init__(self, report: Report):
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers.fsevents import FSEventsObserver

        class Handler(FileSystemEventHandler):
            def on_any_event(self, event):
                if event.is_directory:
                    return
                src = os.fsdecode(event.src_path)
                kind = event.event_type
                if kind == "moved":
                    report(src, "deleted")
                    report(os.fsdecode(event.dest_path), "created")
                elif kind in ("created", "modified", "deleted"):
                    report(src, kind)

        self.handler = Handler()
        self.observer = FSEventsObserver()
        self.observer.daemon = True
        self.observer.start()

    def add(self, root: str, done: Callable[[str], None]) -> None:
        try:
            self.observer.schedule(self.handler, root, recursive=True)
            done("watched")
        except Exception as exc:  # noqa: BLE001
            done(f"not watched: {exc!r}")

    def close(self) -> None:
        self.observer.stop()


IN_MODIFY, IN_CLOSE_WRITE, IN_MOVED_FROM, IN_MOVED_TO = 0x2, 0x8, 0x40, 0x80
IN_CREATE, IN_DELETE, IN_Q_OVERFLOW, IN_IGNORED, IN_ISDIR = 0x100, 0x200, 0x4000, 0x8000, 0x40000000
IN_NONBLOCK, IN_CLOEXEC = 0o4000, 0o2000000
MASK = IN_MODIFY | IN_CLOSE_WRITE | IN_MOVED_FROM | IN_MOVED_TO | IN_CREATE | IN_DELETE
EVENT = struct.Struct("iIII")                     # wd, mask, cookie, len; then the name, len bytes


class TooBig(Exception):
    pass


class _Inotify:
    """Linux: one inotify instance, a watch on each directory of each root, read by a thread."""

    def __init__(self, report: Report, log: Callable[[str], None]):
        self.report, self.log = report, log
        libc = ctypes.CDLL(ctypes.util.find_library("c") or None, use_errno=True)
        self._add, self._rm = libc.inotify_add_watch, libc.inotify_rm_watch
        self._add.argtypes, self._add.restype = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32], ctypes.c_int
        self._rm.argtypes, self._rm.restype = [ctypes.c_int, ctypes.c_int], ctypes.c_int
        self.fd = libc.inotify_init1(IN_NONBLOCK | IN_CLOEXEC)
        if self.fd < 0:
            raise OSError(ctypes.get_errno(), "inotify_init1")
        self.lock = threading.Lock()
        self.dirs: Dict[int, str] = {}               # watch -> its directory
        self.closed = False
        threading.Thread(target=self._read, name="ag-inotify", daemon=True).start()

    def add(self, root: str, done: Callable[[str], None]) -> None:
        def walk():
            added = []
            try:
                self._tree(root, added, time.monotonic() + MAX_WALK_SECONDS)
                done("watched")
            except TooBig as why:
                for wd in added:
                    self._rm(self.fd, wd)
                with self.lock:
                    for wd in added:
                        self.dirs.pop(wd, None)
                done(f"too big: {why}")
                self.log(f"{root}: not watched ({why}); the files the calls name are still compared")
        threading.Thread(target=walk, name="ag-inotify-walk", daemon=True).start()

    def _tree(self, top: str, added: list, deadline: float, created: bool = False) -> None:
        """Watch `top` and every directory under it (not under one left out); `created`: a directory
        made while watched, whose files, made before its watch, are reported as created."""
        stack = [top]
        while stack:
            d = stack.pop()
            if len(added) >= MAX_DIRS:
                raise TooBig(f"over {MAX_DIRS} directories")
            if time.monotonic() > deadline:
                raise TooBig(f"over {MAX_WALK_SECONDS:.0f} s to walk")
            wd = self._add(self.fd, os.fsencode(d), MASK)
            if wd < 0:
                err = ctypes.get_errno()
                if err == errno.ENOSPC:
                    raise TooBig("the system's limit on watches reached (fs.inotify.max_user_watches)")
                continue                                  # gone, or not readable: skipped
            added.append(wd)
            with self.lock:
                self.dirs[wd] = d
            try:
                with os.scandir(d) as it:
                    for e in it:
                        if e.is_dir(follow_symlinks=False):
                            if not (e.name.startswith(".") or e.name in SKIP):
                                stack.append(e.path)
                        elif created and e.is_file(follow_symlinks=False):
                            self.report(e.path, "created")
            except OSError:
                pass

    def _read(self) -> None:
        while not self.closed:
            try:
                ready, _, _ = select.select([self.fd], [], [], 1.0)
                if not ready:
                    continue
                data = os.read(self.fd, 1 << 16)
            except (OSError, ValueError):
                return
            at = 0
            while at + EVENT.size <= len(data):
                wd, mask, _, size = EVENT.unpack_from(data, at)
                name = data[at + EVENT.size:at + EVENT.size + size].rstrip(b"\0")
                at += EVENT.size + size
                if mask & IN_Q_OVERFLOW:
                    self.log("inotify's queue overflowed: changes were lost")
                    continue
                with self.lock:
                    d = self.dirs.pop(wd, None) if mask & IN_IGNORED else self.dirs.get(wd)
                if d is None or not name:
                    continue
                path = os.path.join(d, os.fsdecode(name))
                if mask & IN_ISDIR:
                    if mask & (IN_CREATE | IN_MOVED_TO) and not (os.path.basename(path).startswith(".")
                                                                or os.path.basename(path) in SKIP):
                        try:
                            self._tree(path, [], time.monotonic() + MAX_WALK_SECONDS, created=True)
                        except TooBig:
                            pass
                    continue
                if mask & (IN_CREATE | IN_MOVED_TO):
                    self.report(path, "created")
                elif mask & (IN_DELETE | IN_MOVED_FROM):
                    self.report(path, "deleted")
                elif mask & (IN_MODIFY | IN_CLOSE_WRITE):
                    self.report(path, "modified")

    def close(self) -> None:
        self.closed = True
        try:
            os.close(self.fd)
        except OSError:
            pass
