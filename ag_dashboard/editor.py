"""Files edited in the page's Editor panel, shared as they are edited: each file open there is one document of a
CRDT -- Yjs's, kept here by pycrdt (the Python binding of its Rust port) -- of which every page editing it holds
a copy; and what an actor (or anything else) writes to the file is merged in as it lands, three ways, as version
control merges: the lines only the file changed take its change, and the lines it changed in the conflict zone -- those
the pages edited since the file was opened -- or that the pages changed too, differently, are a conflict: the pages'
kept, the file's shown beside them, for a page to take or not.

    a page opens a file        `Editors.join`: the file's document (made from the file the first time it is
                               opened), every other page's cursor, and then -- through its stream (`Conn.queue`) --
                               the others' edits and cursors, and the disk's changes, as they come
    a page edits               `Room.edit`: its update applied here, and sent on to the other pages; what it changed,
                               put in the conflict zone (`zone`: ranges of the document, moved with each edit, until
                               a page clears it, or the last page goes -- ZONE_GRACE seconds after, a page's stream
                               may come back)
    a page's cursor moves      `Room.aware`: kept (a page that opens the file later is sent it), and sent on
                               (y-protocols' awareness updates, passed through unread)
    the file changes on disk   `Room.check`, every POLL seconds while the file is open: `merge` of the file as last
                               read or written here (`disk`), the document, and the file now; the merged text made
                               the document's (an edit here, sent to every page), and each conflict kept (`Conflict`:
                               where the pages' lines are, moved with each edit, and the file's)
    a page settles a conflict  `Room.settle`: the pages' lines kept, the file's taken in their place, or both
    a page saves               `Room.save`: the document written to the file, in place of it (whoever reads it
                               meanwhile reads all of the old or all of the new) -- the file's own change taken in
                               first, and not saved over where it is a conflict found then; a conflict shown before
                               is settled as the pages' lines. Saved, the zone's lines are still its: a change on disk
                               to them -- an actor rewriting what was typed, a script's write from the file before the
                               save -- is a conflict (`Conflict.zone`), the pages say which

A file whose document has changes no one saved stays open after its last page goes (a page opened again finds
them); one with none is closed LINGER seconds after. Only a regular file of UTF-8 text, at most MAX_BYTES, opens,
and only under the root the page names (the actor's working directory). Needs pycrdt: without it (`AVAILABLE`
false) the page does not offer the view."""
import base64
import bisect
import difflib
import getpass
import os
import queue
import sqlite3
import stat
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from . import data

try:
    from pycrdt import Doc, Text
    AVAILABLE = True
except ImportError:                                 # the page says what to install
    Doc = Text = None
    AVAILABLE = False

POLL = 0.4                  # seconds between looks at each open file
LINGER = 30.0               # seconds a file with nothing unsaved stays open after its last page goes
MAX_BYTES = 2_000_000       # the largest file opened
MAX_ENTRIES = 2000          # the most entries listed of one directory
FINE = 4000                 # changed lines up to this many characters (old and new) are changed by character
RECENT = 1800.0             # seconds an actor's change to a file counts in a listing's `writers`
ZONE_GRACE = 5.0            # seconds the conflict zone stays after the last page with the file open goes
GONE_CHECK = 5.0            # the most a stream waits before it looks whether its page went
SKIPPED = frozenset({".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", ".pytest_cache",
                     ".ruff_cache", ".tox", ".DS_Store"})
TEMP = ".ag-edit"           # what a file being saved is written as first, beside it: not listed
ROOT = "text"               # the document's one shared type: the file's text


class EditorError(ValueError):
    """What the page is told: why a file cannot be listed, opened or saved."""


class _Changing(Exception):
    """The file changed while it was read: read it again later."""


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _signature(st: os.stat_result) -> tuple:
    return (st.st_mtime_ns, st.st_size, st.st_ino)


def resolve(path: str, root: str) -> str:
    """`path`, with its links followed, if it is under `root` (likewise): what the page may list, open or save."""
    if not path or not root or not os.path.isabs(path) or not os.path.isabs(root):
        raise EditorError("an absolute path and the directory it is under, please")
    real, top = os.path.realpath(path), os.path.realpath(root)
    if os.path.commonpath([real, top]) != top:
        raise EditorError(f"{path} is not under {root}")
    return real


def read(path: str) -> Tuple[str, tuple]:
    """The file's text and its signature, read between two looks at it that agree."""
    try:
        before = os.stat(path)
    except FileNotFoundError:
        raise EditorError(f"{path} does not exist") from None
    if not stat.S_ISREG(before.st_mode):
        raise EditorError(f"{path} is not a file")
    if before.st_size > MAX_BYTES:
        raise EditorError(f"{path} is too large to edit here ({before.st_size:,} bytes; at most {MAX_BYTES:,})")
    with open(path, "rb") as fh:
        raw = fh.read(MAX_BYTES + 1)
    after = os.stat(path)
    if _signature(before) != _signature(after):
        raise _Changing()
    if len(raw) > MAX_BYTES:
        raise EditorError(f"{path} is too large to edit here")
    if b"\0" in raw[:8192]:
        raise EditorError(f"{path} is not a text file")
    try:
        return raw.decode("utf-8"), _signature(after)
    except UnicodeDecodeError:
        raise EditorError(f"{path} is not UTF-8 text") from None


def change(text, new: str) -> None:
    """Make `text` (a pycrdt Text) hold `new`: what differs, line by line -- and within changed lines by character,
    where they are short -- deleted and inserted, the rest left as it is, so what others typed around it stays
    where it was. pycrdt counts positions in UTF-8 bytes."""
    old = str(text)
    if old == new:
        return
    a, b = old.splitlines(keepends=True), new.splitlines(keepends=True)
    starts = [0]                                    # each line's start in old, in bytes
    for line in a:
        starts.append(starts[-1] + len(line.encode("utf-8")))
    ops: List[Tuple[int, int, str]] = []            # (start, end, what replaces it), in bytes of old
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        was, now = "".join(a[i1:i2]), "".join(b[j1:j2])
        if tag == "replace" and len(was) + len(now) <= FINE:
            for t, k1, k2, l1, l2 in difflib.SequenceMatcher(None, was, now, autojunk=False).get_opcodes():
                if t != "equal":
                    at = starts[i1] + len(was[:k1].encode("utf-8"))
                    ops.append((at, at + len(was[k1:k2].encode("utf-8")), now[l1:l2]))
        else:
            ops.append((starts[i1], starts[i2], now))
    for start, end, put in reversed(ops):           # from the end: each leaves the positions before it as they were
        if end > start:
            del text[start:end]
        if put:
            text.insert(start, put)


def _hunks(base: List[str], new: List[str]) -> List[tuple]:
    """What `new` changed of `base`'s lines: (start, end, its lines there) of each change."""
    return [(i1, i2, new[j1:j2]) for t, i1, i2, j1, j2 in
            difflib.SequenceMatcher(None, base, new, autojunk=False).get_opcodes() if t != "equal"]


def _both(base: List[str], mine: List[str], theirs: List[str]) -> Optional[List[str]]:
    """`base`'s lines with `mine`'s changes and `theirs`', if they change different lines of it (side by side is
    different); None if one changes a line the other does, or both put lines in at the same place."""
    ours, others = _hunks(base, mine), _hunks(base, theirs)
    for a1, a2, _ in ours:
        for b1, b2, _ in others:
            if a1 < b2 and b1 < a2 or a1 == a2 == b1 == b2 or (a1 == a2 and b1 < a1 < b2) or (b1 == b2 and a1 < b1 < a2):
                return None
    out, at = [], 0
    for i1, i2, new in sorted(ours + others, key=lambda h: (h[0], h[1])):
        out += base[at:i1] + new
        at = i2
    return out + base[at:]


def _guarded(a1: int, a2: int, guard) -> bool:
    """Whether `mine`'s lines a1..a2 are in `guard`'s ranges (start, end) -- an empty range, a place between lines:
    whether it is inside one, not at its edge."""
    return any(a1 < g2 and g1 < a2 if a1 < a2 else g1 < a1 < g2 for g1, g2 in guard)


def _meets(a1: int, a2: int, held) -> bool:
    """Whether `mine`'s lines a1..a2 meet any of `held`'s ranges (start, end) -- an empty range: at its edges too."""
    return any(h1 <= a2 and a1 <= h2 if a1 == a2 or h1 == h2 else a1 < h2 and h1 < a2 for h1, h2 in held)


def _theirs_guarded(was: List[str], ours: List[str], others: List[str], at: int, guard) -> bool:
    """Whether a change of `others`' to `was`'s lines is in `guard` -- `mine`'s lines, `ours` from line `at` of it: each
    of `was`'s lines where `ours` has it, after what `ours` changed before it."""
    mine = _hunks(was, ours)
    for i1, i2, _ in _hunks(was, others):
        shift = sum(len(new) - (h2 - h1) for h1, h2, new in mine if h2 <= i1)
        if _guarded(at + i1 + shift, at + i2 + shift, guard):
            return True
    return False


def merge(base: str, mine: str, theirs: str, guard: List[Tuple[int, int]] = (),
          held: List[Tuple[int, int]] = ()) -> Tuple[str, List[tuple], int]:
    """Three ways, by line, as version control merges: `base`, and what `mine` and `theirs` each made of it. The
    merged text; each conflict -- lines both changed, differently, or that `theirs` changed among `guard`'s (ranges
    of `mine`'s lines it may not change unasked: the conflict zone), or changed again where `held`'s are (`mine`'s
    lines of the conflicts still open: what `theirs` does there is that conflict's, not merged around it) -- as
    (start, end) of `mine`'s lines kept in the
    merged text (characters), with `base`'s and `theirs`' lines there, and whether it is one for `guard`; and how many
    of `mine`'s changes `theirs` lacks (kept from `mine` alone)."""
    o, a, b = base.splitlines(True), mine.splitlines(True), theirs.splitlines(True)
    ma = difflib.SequenceMatcher(None, o, a, autojunk=False).get_matching_blocks()
    mb = difflib.SequenceMatcher(None, o, b, autojunk=False).get_matching_blocks()
    syncs, i, j = [], 0, 0                          # base's lines the same in all three: (start, end, in mine, in theirs)
    while i < len(ma) and j < len(mb):
        (oa, aa, na), (ob, bb, nb) = ma[i], mb[j]
        lo, hi = max(oa, ob), min(oa + na, ob + nb)
        if lo < hi:
            syncs.append((lo, hi, aa + lo - oa, bb + lo - ob))
        if oa + na < ob + nb:
            i += 1
        else:
            j += 1
    syncs.append((len(o), len(o), len(a), len(b)))
    out, conflicts, kept, size = [], [], 0, 0
    zo = za = zb = 0
    for lo, hi, sa, sb in syncs:
        was, ours, others = o[zo:lo], a[za:sa], b[zb:sb]
        put, conflict = ours, None
        if others == was or ours == others:         # only mine changed it, or both alike (or neither)
            kept += others == was and ours != was
        elif ours == was:                           # only theirs: taken, but where it may not change mine unasked
            if _theirs_guarded(was, ours, others, za, guard):
                conflict = True
            else:
                put = others
        else:
            both = None if _meets(za, sa, held) else _both(was, ours, others)
            if both is None:                        # both, differently (or a conflict still open): mine kept, a conflict
                conflict = _guarded(za, sa, guard)
            elif _theirs_guarded(was, ours, others, za, guard):
                conflict = True
            else:
                put, kept = both, kept + 1
        if conflict is not None:
            n = sum(map(len, ours))
            conflicts.append((size, size + n, "".join(was), "".join(others), conflict))
        out += put + o[lo:hi]
        size += sum(map(len, put)) + sum(map(len, o[lo:hi]))
        zo, za, zb = hi, sa + hi - lo, sb + hi - lo
    return "".join(out), conflicts, kept


def _utf16(raw: bytes, at: int) -> int:
    """A position in UTF-8 bytes (pycrdt's) as one in UTF-16 units (the page's, JavaScript's)."""
    return len(raw[:at].decode("utf-8", errors="ignore").encode("utf-16-le")) // 2


def writers(directories: List[str], since: float) -> Dict[str, List[dict]]:
    """The actors that changed a file under any of `directories` since `since` (seconds), by the file's path from
    its directory: [{gatherer, channel, at, how}], each actor's latest change, the latest first -- what ag's hook found
    each tool call did on disk (every gatherer's `file_touched` events; an older gatherer's `_touches`, copied there
    once). Read newest first, by the events' type, and only back to `since`: the events are in the order they came
    (copied ones, in theirs, before any that came after)."""
    prefixes = [d.rstrip("/") + "/" for d in set(directories)]
    out: Dict[str, Dict[tuple, dict]] = {}
    for gatherer in data.gatherer_names():
        conn = data._connect(gatherer)
        if conn is None:
            continue
        try:
            kind = conn.execute("SELECT event_type_id FROM event_types WHERE name = 'file_touched'").fetchone()
            if kind is None:
                continue
            for r in conn.execute(f"SELECT {data.CHANNEL} AS session, inserted_at, payload_json FROM events "
                                  "WHERE event_type_id = ? ORDER BY row_id DESC", (kind[0],)):
                at = data._seconds(r["inserted_at"])
                if at is None or at < since:
                    break
                t = data._json(r["payload_json"]) or {}
                path = t.get("path")
                if t.get("how") not in ("created", "modified", "deleted") or not isinstance(path, str):
                    continue
                for prefix in prefixes:
                    if path.startswith(prefix):
                        key, kept = (gatherer, r["session"]), out.setdefault(path[len(prefix):], {})
                        if key not in kept or at > kept[key]["at"]:
                            kept[key] = {"gatherer": gatherer, "channel": r["session"], "at": at, "how": t["how"]}
        except sqlite3.Error:                       # being written, or not ag's: the next listing
            continue
        finally:
            conn.close()
    return {rel: sorted(by.values(), key=lambda w: -w["at"]) for rel, by in out.items()}


def _latest(found: List[dict]) -> List[dict]:
    """Writers, each actor's latest kept, the latest first."""
    kept: Dict[tuple, dict] = {}
    for w in found:
        key = (w["gatherer"], w["channel"])
        if key not in kept or w["at"] > kept[key]["at"]:
            kept[key] = w
    return sorted(kept.values(), key=lambda w: -w["at"])


class Conn:
    """One page's stream of a file: what it is sent (`queue`: (event, value), or None to end), its Yjs client id,
    and its last awareness update (its user and cursor)."""

    def __init__(self, cid: str, client: int):
        self.id, self.client, self.queue, self.aware = cid, client, queue.Queue(), None


class Conflict:
    """Lines the pages and the file on disk both changed, differently, or that the file changed in the conflict zone
    (`zone`): the pages' kept in the document -- from `start` to `end`, in UTF-8 bytes, moved with each edit
    (`Room._move`) -- and the file's (`theirs`, over `base`), until a page settles it."""

    def __init__(self, start: int, end: int, base: str, theirs: str, zone: bool = False, since: Optional[float] = None):
        self.id, self.at, self.zone = uuid.uuid4().hex[:12], time.time(), zone
        self.since = self.at if since is None else since      # when the file first changed these lines, unsettled
        self.start, self.end, self.base, self.theirs = start, end, base, theirs


class Room:
    """A file open for editing: its document, the pages editing it, and the file as last read or written here."""

    def __init__(self, path: str):
        text, sig = read(path)
        self.path, self.lock = path, threading.RLock()
        self.epoch = uuid.uuid4().hex               # this document: a page that had another (the dashboard restarted)
        self.doc = Doc(allow_multithreading=True)   # starts again from this one
        self.doc[ROOT] = self.text = Text(text)
        self.disk, self.sig = text, sig
        self.missing, self.error, self.dirty = False, "", False
        self.changed: Optional[float] = None        # when the file last changed on disk while open
        self.saved: Optional[float] = None          # when it was last saved from here
        self.zone: List[List[int]] = []            # the conflict zone: [start, end] of the document, in UTF-8 bytes
        self._from_page = False                     # an edit being applied is a page's: put in the zone
        self.conflicts: Dict[str, Conflict] = {}
        self.conns: Dict[str, Conn] = {}
        self.idle_since: Optional[float] = None     # when its last page went
        self._moves = self.text.observe(self._move)

    def _move(self, event) -> None:
        """Each conflict's lines, and the conflict zone, moved with an edit to the document, any page's or this one's
        (pycrdt's delta, which counts UTF-8 bytes): what is put in a conflict's lines, or at their edges, theirs; what
        is put inside the zone's ranges, not at their edges, theirs. A page's edit is put in the zone: what it put in,
        and where it took something out (an empty range)."""
        if not self.conflicts and not self.zone and not self._from_page:
            return
        at = 0
        for op in event.delta:
            if "retain" in op:
                at += op["retain"]
            elif "insert" in op:
                n = len(op["insert"].encode("utf-8")) if isinstance(op["insert"], str) else 1
                for c in self.conflicts.values():
                    if at < c.start:
                        c.start, c.end = c.start + n, c.end + n
                    elif at <= c.end:
                        c.end += n
                for z in self.zone:
                    if at <= z[0]:
                        z[0], z[1] = z[0] + n, z[1] + n
                    elif at < z[1]:
                        z[1] += n
                if self._from_page:
                    self.zone.append([at, at + n])
                at += n
            elif "delete" in op:
                n = op["delete"]
                for c in self.conflicts.values():
                    c.start = c.start if c.start <= at else max(at, c.start - n)
                    c.end = c.end if c.end <= at else max(at, c.end - n)
                for z in self.zone:
                    z[0] = z[0] if z[0] <= at else max(at, z[0] - n)
                    z[1] = z[1] if z[1] <= at else max(at, z[1] - n)
                if self._from_page:
                    self.zone.append([at, at])
        if self._from_page:                         # ranges that meet, one
            kept: List[List[int]] = []
            for z in sorted(self.zone):
                if kept and z[0] <= kept[-1][1]:
                    kept[-1][1] = max(kept[-1][1], z[1])
                else:
                    kept.append(z)
            self.zone = kept

    @staticmethod
    def _lines(text: str, ranges) -> List[Tuple[int, int]]:
        """Ranges of `text` (UTF-8 bytes) as ranges (start, end) of its lines: each line a range is on, or an empty
        range is at."""
        starts, at = [], 0
        for line in text.splitlines(True):
            starts.append(at)
            at += len(line.encode("utf-8"))
        if not starts:
            return []
        return [(bisect.bisect_right(starts, a) - 1, bisect.bisect_right(starts, max(a, b - 1))) for a, b in ranges]

    def clear_zone(self) -> dict:
        """The conflict zone cleared: its lines the file's to change, as any other."""
        with self.lock:
            self.zone = []
            self._restate()
            return self.state()

    def state(self) -> dict:
        raw = str(self.text).encode("utf-8")
        return {"dirty": self.dirty, "missing": self.missing, "error": self.error, "changed": self.changed,
                "saved": self.saved, "editors": len(self.conns), "now": time.time(),
                "conflicts": [{"id": c.id, "from": _utf16(raw, c.start), "to": _utf16(raw, c.end), "base": c.base,
                               "theirs": c.theirs, "at": c.at, "since": c.since, "zone": c.zone}
                              for c in sorted(self.conflicts.values(), key=lambda c: c.start)],
                "zone": [[_utf16(raw, a), _utf16(raw, b)] for a, b in self.zone]}

    def _send(self, name: str, value, but: Optional[str] = None) -> None:
        for conn in list(self.conns.values()):
            if conn.id != but:
                conn.queue.put((name, value))

    def _restate(self) -> None:
        text = str(self.text)
        raw = text.encode("utf-8")
        for c in list(self.conflicts.values()):     # made the file's by hand: settled
            if raw[c.start:c.end].decode("utf-8", errors="replace") == c.theirs:
                del self.conflicts[c.id]
        self.dirty = text != self.disk
        self._send("state", self.state())

    def join(self, cid: str, client: int) -> Conn:
        with self.lock:
            old = self.conns.pop(cid, None)
            if old is not None:                     # the page's stream again (it reconnected): the old one ends
                old.queue.put(None)
            conn = Conn(cid, client)
            conn.queue.put(("init", {"epoch": self.epoch, "update": b64(self.doc.get_update()),
                                     "sv": b64(self.doc.get_state()), "state": None,
                                     "aware": [b64(c.aware) for c in self.conns.values() if c.aware]}))
            self.conns[cid], self.idle_since = conn, None
            self._restate()
            return conn

    def leave(self, conn: Conn) -> None:
        with self.lock:
            if self.conns.get(conn.id) is not conn:
                return
            del self.conns[conn.id]
            self._send("left", {"client": conn.client})
            self._restate()
            if not self.conns:
                self.idle_since = time.time()

    def edit(self, cid: str, update: bytes) -> dict:
        with self.lock:
            self._from_page = True
            try:
                self.doc.apply_update(update)
            finally:
                self._from_page = False
            self._send("update", {"update": b64(update)}, but=cid)
            self._restate()
            return self.state()

    def aware(self, cid: str, update: bytes) -> None:
        with self.lock:
            conn = self.conns.get(cid)
            if conn is None:
                raise EditorError("this page has the file open no more: open it again")
            conn.aware = update
            self._send("aware", {"update": b64(update)}, but=cid)

    def check(self) -> None:
        """Take in the file's change on disk, if it has one."""
        with self.lock:
            try:
                sig = _signature(os.stat(self.path))
            except FileNotFoundError:
                if not self.missing:
                    self.missing = True
                    self._restate()
                return
            if sig == self.sig and not self.missing:
                return
            try:
                text, sig = read(self.path)
            except _Changing:
                return                              # being written: the next look
            except (EditorError, OSError) as exc:   # no longer text, or too large: kept as it was here
                self.sig, self.error = sig, str(exc)
                self._restate()
                return
            self.missing, self.error, self.sig = False, "", sig
            if text == self.disk:
                return self._restate()
            mine = str(self.text)
            merged, found, _ = merge(self.disk, mine, text, self._lines(mine, self.zone),
                                     self._lines(mine, [(c.start, c.end) for c in self.conflicts.values()]))
            if merged != mine:
                before = self.doc.get_state()
                change(self.text, merged)
                self._send("update", {"update": b64(self.doc.get_update(before)), "disk": True})
            raw = merged.encode("utf-8")
            for start, end, was, theirs, zone in found:
                b0 = len(merged[:start].encode("utf-8"))
                b1 = b0 + len(merged[start:end].encode("utf-8"))
                since = time.time()
                for old in list(self.conflicts.values()):   # the same lines' conflict before: this one in its place
                    if old.start <= b1 and b0 <= old.end:
                        since = min(since, old.since)
                        del self.conflicts[old.id]
                c = Conflict(b0, b1, was, theirs, zone, since)
                if raw[b0:b1].decode("utf-8") != theirs:
                    self.conflicts[c.id] = c
            self.disk, self.changed = text, time.time()
            self._restate()

    def settle(self, conflict: str, take: str) -> dict:
        """A conflict settled: the pages' lines kept (`mine`), the file's in their place (`theirs`), or the file's
        after them (`both`)."""
        if take not in ("mine", "theirs", "both"):
            raise EditorError(f"take {take!r}: mine, theirs or both")
        with self.lock:
            c = self.conflicts.pop(conflict, None)
            if c is None:
                raise EditorError("that conflict is settled already")
            if take != "mine":
                before = self.doc.get_state()
                if take == "theirs":
                    if c.end > c.start:
                        del self.text[c.start:c.end]
                    if c.theirs:
                        self.text.insert(c.start, c.theirs)
                elif c.theirs:
                    mine = str(self.text).encode("utf-8")[c.start:c.end]
                    self.text.insert(c.end, ("\n" if mine and not mine.endswith(b"\n") else "") + c.theirs)
                self._send("update", {"update": b64(self.doc.get_update(before))})
            self._restate()
            return self.state()

    def save(self) -> dict:
        with self.lock:
            shown = set(self.conflicts)
            for _ in range(3):
                self.check()                        # the file's own change first, merged in
                if set(self.conflicts) - shown:     # where it was edited here too: shown, not saved over
                    raise EditorError("The file changed on disk where it was edited here: see the conflicts, then save.")
                text = str(self.text)
                sig = self._write(text)
                if sig is not None:
                    break
            else:
                raise EditorError("the file keeps changing on disk: save again in a moment")
            self.disk, self.sig = text, sig
            self.conflicts.clear()                  # those shown: settled as the lines kept here
            self.missing, self.error, self.saved = False, "", time.time()
            self._restate()
            return self.state()

    def _write(self, text: str) -> Optional[tuple]:
        """`text` written in place of the file; None, and nothing written, if the file changed since it was last
        looked at."""
        try:
            mode = stat.S_IMODE(os.stat(self.path).st_mode)
        except FileNotFoundError:
            mode = 0o644
        fd, temp = tempfile.mkstemp(prefix="." + os.path.basename(self.path) + ".", suffix=TEMP,
                                    dir=os.path.dirname(self.path))
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(text.encode("utf-8"))
            os.chmod(temp, mode)
            try:
                now = _signature(os.stat(self.path))
            except FileNotFoundError:
                now = None
            if now != (None if self.missing else self.sig):
                os.unlink(temp)
                return None
            os.replace(temp, self.path)
        except BaseException:
            if os.path.exists(temp):
                os.unlink(temp)
            raise
        return _signature(os.stat(self.path))


class Editors:
    """Every file open for editing, each looked at on disk every POLL seconds while it is open."""

    def __init__(self, poll: Optional[float] = None):
        self.rooms: Dict[str, Room] = {}
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.poll = POLL if poll is None else poll
        self.thread = threading.Thread(target=self._watch, name="editor-files", daemon=True)
        self.thread.start()

    def _room(self, path: str, root: str, create: bool = False) -> Room:
        if not AVAILABLE:
            raise EditorError("the Editor panel needs pycrdt: pip install pycrdt")
        real = resolve(path, root)
        with self.lock:
            room = self.rooms.get(real)
            if room is None:
                if not create:
                    raise EditorError(f"{path} is not open: open it again")
                for _ in range(5):
                    try:
                        room = self.rooms[real] = Room(real)
                        break
                    except _Changing:
                        time.sleep(0.05)
                else:
                    raise EditorError(f"{path} keeps changing on disk: open it again in a moment")
            return room

    def join(self, path: str, root: str, cid: str, client: int) -> Tuple[Room, Conn]:
        if not cid:
            raise EditorError("a connection id, please")
        room = self._room(path, root, create=True)
        return room, room.join(cid, client)

    def edit(self, path: str, root: str, cid: str, update: bytes) -> dict:
        return self._room(path, root).edit(cid, update)

    def aware(self, path: str, root: str, cid: str, update: bytes) -> None:
        self._room(path, root).aware(cid, update)

    def save(self, path: str, root: str) -> dict:
        return self._room(path, root).save()

    def settle(self, path: str, root: str, conflict: str, take: str) -> dict:
        return self._room(path, root).settle(conflict, take)

    def clear_zone(self, path: str, root: str) -> dict:
        return self._room(path, root).clear_zone()

    def listing(self, directory: str, root: str) -> dict:
        """The directory's entries -- folders first, then files, by name -- each with whether pages edit it now,
        whether it has changes no one saved, and the actors that changed it lately (`writers`; a folder's: of the
        files in it, all the way down)."""
        real = resolve(directory, root)
        entries, more = [], False
        try:
            with os.scandir(real) as found:
                for entry in found:
                    if entry.name in SKIPPED or entry.name.endswith(TEMP):
                        continue
                    if len(entries) >= MAX_ENTRIES:
                        more = True
                        break
                    try:
                        is_dir, st = entry.is_dir(), entry.stat()
                    except OSError:                 # a link to nothing
                        continue
                    room = self.rooms.get(os.path.realpath(entry.path) if entry.is_symlink() else entry.path)
                    entries.append({"name": entry.name, "dir": is_dir, "size": st.st_size, "mtime": st.st_mtime,
                                    "editors": len(room.conns) if room else 0, "dirty": bool(room and room.dirty),
                                    "conflicts": len(room.conflicts) if room else 0})
        except (FileNotFoundError, NotADirectoryError):
            raise EditorError(f"{directory} is not a directory") from None
        except PermissionError:
            raise EditorError(f"{directory} may not be read") from None
        found: Dict[str, List[dict]] = {}           # by entry: its own writers, or those of what is in it
        for rel, ws in writers([real, os.path.abspath(directory)], time.time() - RECENT).items():
            found.setdefault(rel.split("/")[0], []).extend(ws)
        for e in entries:
            e["writers"] = _latest(found.get(e["name"], []))
        entries.sort(key=lambda e: (not e["dir"], e["name"].lower()))
        return {"dir": directory, "entries": entries, "more": more, "now": time.time(), "user": _user(),
                "home": os.path.expanduser("~")}

    def _watch(self) -> None:
        while not self.stop.wait(self.poll):
            self.look()

    def look(self) -> None:
        """Each open file looked at: its change on disk taken in; with no page left, its conflict zone cleared, and the
        file closed if nothing in it is unsaved."""
        for real, room in list(self.rooms.items()):
            try:
                room.check()
            except Exception:                       # noqa: BLE001 - the next look; the page keeps what it has
                pass
            with self.lock, room.lock:
                idle = None if room.idle_since is None else time.time() - room.idle_since
                if idle is not None and idle > ZONE_GRACE and room.zone:
                    room.zone = []                  # its pages closed it
                if idle is not None and not room.dirty and idle > LINGER:
                    self.rooms.pop(real, None)

    def close(self) -> None:
        self.stop.set()
        for room in list(self.rooms.values()):
            for conn in list(room.conns.values()):
                conn.queue.put(None)


def _user() -> str:
    try:
        return getpass.getuser()
    except Exception:                               # noqa: BLE001 - no name to give
        return ""
