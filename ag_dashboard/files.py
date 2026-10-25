"""The files a session worked on, one turn at a time: for each file, the calls that touched it,
each with what it did -- the lines it read (by the Read tool, or by a shell command that only
prints part of a file: `sed -n`, `cat`, `head`, `tail`, `nl`, `grep -n`), the matches it found, or
what it changed, at the lines where: by an edit tool, or by a shell command whose change can be
read from it (`cat > F <<EOF`, `tee`, `sed -i`, a Python script that replaces constant strings in a
file and writes it back).

A turn is what follows one of the user's messages, up to the next. Each call is read from the
event's parts (data.parts), so whichever harness wrote it; only the tools' names differ.

Where ag's hook server checked a call against the disk as it ran (`_touches`, written by
ag/integrations/tools/ag_orchestrator/file_touches/), that is what is shown of it: the files it read, kept where the
file says so, each marked checked (what the call showed of it is on disk) or not; what it changed,
at the lines the file itself says; and the files that changed while it ran, which it doesn't name.

Any other call (one from before the hook checked calls) is read from what the model saw alone
(file_touches/commands.py): a Read's lines carry their numbers, but an edit carries only the text it
replaced. An edit is placed by finding that text among the lines seen of the file so far in the
session (earlier turns too); one that is not found is listed apart. The files themselves are never
read here: they show what the agent saw then, not what is there now."""
import base64
import binascii
import json
import os
import re
import tempfile
from typing import Dict, List, Optional

from . import data
from .commands import (  # noqa: F401 - python_changes: tested here
    EDITS, GLOB, GREP_PATH_LINE, READ_LINE, SHELLS, _patch_files, _resolve, _shell_text, python_changes, shell_changes,
    shell_reads)

MAX_ROWS = 4000            # the most lines one file shows in a turn
LINE_CHARS = 400           # the most of one line's text sent
COMMAND_OUTPUT = 4000      # the most of a command's output sent
CONTEXT = 2                # the lines known around a change shown with it
REPLY_CHARS = 4000         # the most of a user message or one of the agent's replies sent
# as the hook server's file_touches/check.py has them: Claude Code's note after a command's output, codex's header before it
SHELL_CWD_NOTE = re.compile(r"\n?Shell cwd was reset to [^\n]*\s*$")
CODEX_HEADER = re.compile(r"^(?:Chunk ID: [^\n]*\n)?(?:Wall time: [^\n]*\n)?(?:Process exited with code [^\n]*\n)?"
                          r"(?:Original token count: [^\n]*\n)?Output:\n")


def _unsplit(name: str, text: str) -> dict:
    """A file a call read whose lines can't be told apart from the rest of its output (`cat a; cat b`),
    or one a Read showed no numbered lines of: the call's whole output, said to be that."""
    text = SHELL_CWD_NOTE.sub("", text or "")
    m = CODEX_HEADER.match(text)
    text = (text[m.end():] if m else text).rstrip("\n")
    if not text:
        return {"t": "note", "text": "read, but the output was empty"}
    note = ("the command's whole output: this file's lines are in it, but which ones can't be told apart from the rest"
            if name in SHELLS else "the call's whole output: it shows none of the file's lines by number")
    return {"t": "output", "note": note, "lines": text.split("\n")}


def _temporary_roots() -> tuple:
    roots = set()
    for r in ("/tmp", "/var/tmp", "/var/folders", tempfile.gettempdir(), os.environ.get("TMPDIR") or ""):
        if r:
            roots |= {os.path.normpath(r), os.path.realpath(r)}        # macOS's /tmp is /private/tmp
    return tuple(sorted(roots))


TEMPORARY = _temporary_roots()   # the temporary folders: /tmp, macOS's per-user /var/folders/..., $TMPDIR


def temporary(path: str) -> bool:
    """Whether `path` is in a temporary folder: a scratchpad's, a test's -- not the work itself."""
    return any(path == r or path.startswith(r.rstrip("/") + "/") for r in TEMPORARY)



# ------------------------------------------------------------------ a file's lines, as known

class Sheet:
    """A file's lines by number, as far as they were seen in the session, kept current through the
    changes made to it: each {text}."""

    def __init__(self):
        self.rows: Dict[int, dict] = {}

    def text(self, n: int) -> Optional[str]:
        r = self.rows.get(n)
        return None if r is None else r["text"]

    def replace(self, at: int, old: List[str], new: List[str]) -> None:
        """Lines at..at+len(old)-1 replaced by `new`; the lines after moved along."""
        shift, end = len(new) - len(old), at + len(old)
        rows = {n if n < at else n + shift: r for n, r in self.rows.items() if n < at or n >= end}
        for i, t in enumerate(new):
            rows[at + i] = {"text": t}
        self.rows = rows


def place(known: Sheet, old: str, new: str):
    """Where `old` is among the lines known of a file: (first line, the whole lines it lies in, those
    lines with `new` in its place), or None when it is not there in full."""
    if not old:
        return None
    k = old.count("\n") + 1
    head = old.split("\n")[0]
    for a in sorted(known.rows):
        first = known.rows[a]["text"]
        if head not in first:
            continue
        span = [known.text(a + i) for i in range(k)]
        if any(t is None for t in span):
            continue
        joined = "\n".join(span)
        i = joined.find(old)
        if i < 0 or i > len(span[0]) or i + len(old) < len(joined) - len(span[-1]):
            continue
        return a, span, (joined[:i] + new + joined[i + len(old):]).split("\n")
    return None


# ------------------------------------------------------------------ the session, turn by turn

def _events(conn, channel: str):
    """The channel's events, oldest first, then what it has pending: (row_id, type, at, parts) --
    parts unclipped, the lines of a long read all there."""
    rows = conn.execute(
        "SELECT e.row_id, t.name AS type, e.text, e.payload_json, e.inserted_at FROM events e "
        f"LEFT JOIN event_types t ON t.event_type_id = e.event_type_id WHERE e.{data.CHANNEL} = ? ORDER BY e.row_id",
        (channel,)).fetchall()
    for r in rows:
        yield r["row_id"], r["type"] or "?", data._seconds(r["inserted_at"]), data.parts(r["type"] or "?", r["payload_json"], r["text"], None)
    tables = data._tables(conn)
    if "_pending" in tables and data.CHANNEL in data._columns(conn, "_pending"):
        for r in conn.execute(f"SELECT received_at, type, payload_json, text FROM _pending WHERE {data.CHANNEL} = ? "
                              "ORDER BY pending_id", (channel,)):
            yield None, r["type"], data._seconds(r["received_at"]), data.parts(r["type"], r["payload_json"], r["text"], None)


def _touches(conn, channel: str) -> Dict[str, List[dict]]:
    """What the hook server found each of the session's calls did to files, by call id (none: the
    call was not checked): [{path (None: it touched none), how, checked, named, detail}]."""
    if "_touches" not in data._tables(conn):
        return {}
    out: Dict[str, List[dict]] = {}
    for r in conn.execute("SELECT call_id, path, how, checked, named, detail_json FROM _touches WHERE session = ? "
                          "ORDER BY touch_id", (channel,)):
        try:
            detail = json.loads(r["detail_json"]) if r["detail_json"] else {}
        except ValueError:
            detail = {}
        out.setdefault(r["call_id"], []).append({"path": r["path"], "how": r["how"], "checked": r["checked"],
                                                 "named": r["named"], "detail": detail if isinstance(detail, dict) else {}})
    return out


TOUCH_KINDS = {"read": "read", "hit": "hit", "created": "write", "modified": "edit", "deleted": "delete"}


def _runs(numbered: List[tuple]) -> List[tuple]:
    """Numbered lines [(n, text)] as runs of consecutive lines: [(start, [text, ...])]."""
    runs: List[tuple] = []
    for n, t in numbered:
        if runs and runs[-1][0] + len(runs[-1][1]) == n:
            runs[-1][1].append(t)
        else:
            runs.append((n, [t]))
    return runs


class _Turn:
    def __init__(self, n, row_id, at, text):
        self.head = {"n": n, "row_id": row_id, "at": at, "text": text[:REPLY_CHARS], "replies": [], "now": None}
        self.files: Dict[str, dict] = {}
        self.commands: List[dict] = []
        self.order: List[str] = []
        self.current: Optional[dict] = None              # the call being read, as `commands` lists it

    def file(self, path: str) -> dict:
        f = self.files.get(path)
        if f is None:
            f = self.files[path] = {"path": path, "sources": [], "kinds": set(), "created": False}
            self.order.append(path)
        return f

    def source(self, f: dict, via: str, kind: str, call: dict, error: bool) -> int:
        """A call that touched `f`: the same call again (a read and a hit, five replacements) is one."""
        last = f["sources"][-1] if f["sources"] else None
        f["kinds"].add(kind)
        if self.current is not None and f["path"] not in self.current["files"]:
            self.current["files"].append(f["path"])
        if last and last["call"] is call:
            last["kinds"] = sorted(set(last["kinds"]) | {kind})
            return len(f["sources"]) - 1
        f["sources"].append({"via": via, "kind": kind, "kinds": [kind], "error": error, "call": call, "blocks": []})
        return len(f["sources"]) - 1

    def checked(self, f: dict, src: int, checked: Optional[bool], named: bool) -> None:
        """What the disk said of call `src`'s use of `f`: its lines there (True), not (False), not
        matched (None); `named`: the call names the file (else it changed while the call ran)."""
        s = f["sources"][src]
        if checked is not None:
            s["checked"] = checked if s.get("checked") is None else s["checked"] and checked
        else:
            s.setdefault("checked", None)
        if not named:
            s["unnamed"] = True

    @staticmethod
    def block(f: dict, src: int, b: dict) -> None:
        """What call `src` did to `f`: lines it read, matches it found, a change; matches gathered in one."""
        blocks = f["sources"][src]["blocks"]
        if b["t"] == "hits" and blocks and blocks[-1]["t"] == "hits":
            blocks[-1]["rows"] += b["rows"]
        else:
            blocks.append(b)


def _label(name: str, inp: dict, raw, cwd: str) -> str:
    """A call in a line: its own description, else its tool and what it worked on."""
    if isinstance(inp.get("description"), str) and inp["description"].strip():
        return inp["description"].strip()[:200]
    if name in SHELLS:
        command, _ = _shell_text(name, raw)
        return re.sub(r"^cd \S+ && ", "", command.strip().split("\n")[0])[:200]
    target = inp.get("file_path") or inp.get("notebook_path") or inp.get("pattern") or inp.get("query") \
        or inp.get("url") or inp.get("skill") or inp.get("prompt") or ""
    if isinstance(target, str) and cwd and target.startswith(cwd.rstrip("/") + "/"):
        target = target[len(cwd.rstrip("/")) + 1:]
    return f"{name} {target if isinstance(target, str) else ''}".strip()[:200]


def _call_view(part: dict) -> dict:
    """A call as its source shows it: its tool, and its input clipped."""
    return {"name": part.get("name"), "input": data._clip(part.get("input"), COMMAND_OUTPUT)}


def files(gatherer: str, channel: str, turn: Optional[int] = None, cwd: str = "") -> dict:
    """The session's turns ({n, row_id, at, text, replies, now}: what the user asked; what the agent
    said back and thought, in order -- each {kind: "text", text} or {kind: "thinking", texts} (a run of
    thinking between two replies, its readable words: none when encrypted); and what it was doing
    last -- {kind: "thinking"}, {kind: "call", id, text} (a call with no result yet), or None), and for turn `turn` (None:
    the latest) the files it worked on, in the order first touched, each
        {path, kinds (read, edit, write, hit), created,
         sources: [{via, kind, kinds, error, call, blocks}]: the calls that touched it, in order, each
         with what it did to it -- blocks of {t: "lines", start (None: not known), lines} (read),
         {t: "hits", rows: [[n, text]]}, {t: "diff", at (None: not found), old, new, above, below
         ([[n, text]]: known lines around it)}, {t: "write", lines, created}, {t: "append", lines},
         {t: "image", row_id, id} (fetched by `image`), {t: "note", text}}
    and every call it made, in order: {text, error, running, call, output, files (the paths it touched)}.
    A source the hook server checked on disk also has `checked` (True: what the call showed of the file
    is on disk; False: it is not; None: nothing to match), and `unnamed` when the file changed while
    the call ran but the call doesn't name it; its kinds may be "delete" too. A file in a temporary
    folder (`temporary`) has `temporary` true, and so has a call whose every file is in one.
    Relative paths in shell commands are taken from `cwd` (the session's directory)."""
    conn = data._connect(gatherer)
    if conn is None:
        return {"error": f"no database for gatherer {gatherer!r}"}
    try:
        evs = list(_events(conn, channel))
        touched = _touches(conn, channel)
    finally:
        conn.close()
    known: Dict[str, Sheet] = {}                     # each file's lines as last seen, over the whole session
    calls: Dict[str, dict] = {}                      # a call waiting for its result, by id
    turns: List[_Turn] = []
    want = None

    def knows(path) -> Sheet:
        return known.setdefault(path, Sheet())

    def change(rec, view, via: str, path: str, old: Optional[str], new: str, whole: bool, error: bool) -> None:
        """One change to a file, by an edit tool or a shell command: the whole new text (`whole`), or
        `old` replaced by `new`, placed among its lines seen so far (`at`: None when not found), with
        CONTEXT lines of what is known around it."""
        k = knows(path)
        src = f = None
        if rec:
            f = rec.file(path)
            src = rec.source(f, via, "write" if whole else "edit", view, error)
        if error:
            return
        if whole:
            lines = new.split("\n")
            if rec:
                f["created"] = f["created"] or not k.rows
                rec.block(f, src, {"t": "write", "lines": [l[:LINE_CHARS] for l in lines[:MAX_ROWS]],
                                   "cut": max(0, len(lines) - MAX_ROWS), "created": not k.rows})
            known[path] = Sheet()
            known[path].rows = {i + 1: {"text": t} for i, t in enumerate(lines)}
            return
        spot = place(k, old, new)
        if spot is None:
            if rec:
                rec.block(f, src, {"t": "diff", "at": None, "old": old[:COMMAND_OUTPUT].split("\n"),
                                   "new": new[:COMMAND_OUTPUT].split("\n")})
            return
        at, before, after = spot
        if rec:
            above = [[n, k.text(n)] for n in range(at - CONTEXT, at) if k.text(n) is not None]
            below = [[n + len(after) - len(before), k.text(n)] for n in range(at + len(before), at + len(before) + CONTEXT)
                     if k.text(n) is not None]
            rec.block(f, src, {"t": "diff", "at": at, "old": before, "new": after, "above": above, "below": below})
        k.replace(at, before, after)

    def from_disk(rec, view, via: str, part: dict, result: dict, rows: List[dict], error: bool) -> None:
        """A call as the hook server found it on disk (`_touches`): the files it read and changed."""
        for r in rows:
            path, how, d = r["path"], r["how"], r["detail"]
            if path is None or how not in TOUCH_KINDS:
                continue
            if how == "read":                               # what is known of the file, for calls not checked
                for start, lines in d.get("lines") or []:
                    for i, line in enumerate(lines if start is not None else []):
                        knows(path).rows[start + i] = {"text": line}
            elif how == "created" and not d.get("cut"):
                known[path] = Sheet()
                known[path].rows = {i + 1: {"text": t} for i, t in enumerate(d.get("lines") or [])}
            elif how in ("modified", "deleted"):
                known.pop(path, None)
            if not rec:
                continue
            f = rec.file(path)
            src = rec.source(f, via, TOUCH_KINDS[how], view, error)
            unnamed = how in ("created", "modified", "deleted") and r["named"] == 0
            rec.checked(f, src, None if r["checked"] is None else bool(r["checked"]), not unnamed)
            if unnamed:
                rec.block(f, src, {"t": "note", "text": "changed while this ran; the call doesn't name it"})
            if how == "read":
                if d.get("image") and result.get("row_id") is not None:
                    rec.block(f, src, {"t": "image", "row_id": result["row_id"], "id": part.get("id")})
                elif d.get("unsplit"):
                    rec.block(f, src, _unsplit(part.get("name") or "", result.get("text") or ""))
                for start, lines in d.get("lines") or []:
                    rec.block(f, src, {"t": "lines", "start": start, "lines": lines})
            elif how == "hit":
                if d.get("listed"):
                    rec.block(f, src, {"t": "note", "text": "listed by name"})
                if d.get("hits"):
                    rec.block(f, src, {"t": "hits", "rows": d["hits"]})
            elif how == "created":
                f["created"] = True
                rec.block(f, src, {"t": "write", "lines": d.get("lines") or [], "cut": d.get("cut", 0), "created": True})
            elif how == "modified":
                for h in d.get("hunks") or []:
                    if h.get("more"):
                        rec.block(f, src, {"t": "note", "text": "changed in more places, not shown"})
                    else:
                        rec.block(f, src, {"t": "diff", "at": h.get("at"), "old": h.get("old") or [], "new": h.get("new") or [],
                                           "above": h.get("above") or [], "below": h.get("below") or []})
                if not d.get("hunks"):
                    rec.block(f, src, {"t": "note", "text": "changed; at which lines isn't known (it wasn't seen before, "
                                                            "or isn't text)"})
            else:
                rec.block(f, src, {"t": "note", "text": "deleted"})

    def apply(t: Optional[_Turn], part: dict, result: Optional[dict]) -> None:
        name, inp = part.get("name") or "", part.get("input")
        inp = inp if isinstance(inp, dict) else {"input": inp}
        error = bool(result and result.get("error"))
        text = (result or {}).get("text") or ""
        rec = t if t is not None and t is want else None          # only the asked-for turn is kept in full
        view = _call_view(part) if rec else None
        if rec:                                                 # every call, in order, with the files it touched
            rec.current = None if name in ("TodoWrite", "update_plan") else {
                "text": _label(name, inp, part.get("input"), cwd), "error": error, "running": result is None,
                "call": view, "output": text[:COMMAND_OUTPUT], "files": []}
            if rec.current:
                rec.commands.append(rec.current)
        rows = touched.get(part.get("id")) if part.get("id") and result is not None else None
        if rows is not None:                                    # checked on disk as it ran: as found there
            desc = inp.get("description") if isinstance(inp.get("description"), str) else ""
            command = _shell_text(name, part.get("input"))[0] if name in SHELLS else ""
            via = desc.strip()[:200] or (re.sub(r"^cd \S+ && ", "", command.split("\n")[0])[:200] if command else name)
            from_disk(rec, view, via, part, result, rows, error)
            return
        if name == "Read" and inp.get("file_path"):
            path = _resolve(str(inp["file_path"]), cwd)
            got = [] if error else [(int(m.group(1)), m.group(2)) for m in map(READ_LINE.match, text.split("\n")) if m]
            for n, line in got:
                knows(path).rows[n] = {"text": line}
            if rec:
                f = rec.file(path)
                image = text.strip() == "[image]"
                src = rec.source(f, "Read", "read", view, error)     # an image is read like any file: its content an image
                if image and result.get("row_id") is not None:
                    rec.block(f, src, {"t": "image", "row_id": result["row_id"], "id": part.get("id")})
                for start, lines in _runs(got):
                    rec.block(f, src, {"t": "lines", "start": start, "lines": lines})
            return
        if name in EDITS:
            edits = []                                              # (path, old, new, whole file?)
            if name == "Edit":
                edits.append((inp.get("file_path"), str(inp.get("old_string") or ""), str(inp.get("new_string") or ""), False))
            elif name == "MultiEdit":
                for e in inp.get("edits") or []:
                    if isinstance(e, dict):
                        edits.append((inp.get("file_path"), str(e.get("old_string") or ""), str(e.get("new_string") or ""), False))
            elif name == "Write":
                edits.append((inp.get("file_path"), None, str(inp.get("content") or ""), True))
            elif name == "NotebookEdit":
                edits.append((inp.get("notebook_path"), "", str(inp.get("new_source") or ""), False))
            else:                                                   # codex's apply_patch: the patch is its input
                body = inp.get("input") if isinstance(inp.get("input"), str) else inp.get("patch") or ""
                for path, how, hunks in _patch_files(str(body)):
                    if how == "add":
                        edits.append((path, None, "\n".join(l for _, new in hunks for l in new), True))
                    else:
                        for old, new in hunks:
                            edits.append((path, "\n".join(old), "\n".join(new), False))
            for path, old, new, whole in edits:
                if path:
                    change(rec, view, name, _resolve(str(path), cwd), old, new, whole, error)
            return
        if name in SHELLS:
            command, workdir = _shell_text(name, part.get("input"))
            here = _resolve(workdir, cwd) if workdir else cwd
            found, _ = shell_reads(command, "" if error else text, here)
            changes, _ = shell_changes(command, here)
            found = [x for x in found if not GLOB.search(x[0])]      # a pattern: which files, not known here
            changes = [c for c in changes if not GLOB.search(c[0])]
            for path, how, n, got in found:
                if how == "lines" and n is not None:
                    for i, line in enumerate(got):
                        knows(path).rows[n + i] = {"text": line}
                elif how == "hit" and n not in knows(path).rows:  # a match is its whole line
                    knows(path).rows[n] = {"text": got}
            desc = inp.get("description") if isinstance(inp.get("description"), str) else ""
            via = desc or re.sub(r"^cd \S+ && ", "", command.split("\n")[0])[:200]
            for path, how, what in changes:
                if how == "write":
                    change(rec, view, via, path, None, what, True, error)
                elif how == "pairs":
                    for old, new in what:
                        change(rec, view, via, path, old, new, False, error)
                else:                                       # added to, or changed in a way the command doesn't say
                    if rec:
                        f = rec.file(path)
                        src = rec.source(f, via, "edit", view, error)
                        rec.block(f, src, {"t": "append", "lines": what[:COMMAND_OUTPUT].split("\n")} if how == "append"
                                  else {"t": "note", "text": f"changed by {what}, which doesn't say which lines"})
                    if how == "changed" and not error:
                        known.pop(path, None)               # its lines are no longer known
            if rec:
                noted = set()
                for path, how, n, got in found:
                    f = rec.file(path)
                    if how == "hit":
                        rec.block(f, rec.source(f, via, "hit", view, error), {"t": "hits", "rows": [[n, got[:LINE_CHARS]]]})
                    elif how == "maybe":                    # searched with others: whose each match is, not known
                        src = rec.source(f, via, "hit", view, error)
                        if path not in noted:
                            noted.add(path)
                            rec.block(f, src, {"t": "note", "text": "searched one after another with other files: "
                                                                    "which of the matches are this file's can't be told apart"})
                    else:
                        src = rec.source(f, via, "read", view, error)
                        if how == "lines":                  # start None: where in the file is not known
                            rec.block(f, src, {"t": "lines", "start": n, "lines": got})
                        else:
                            rec.block(f, src, _unsplit(name, text))
            return
        if name in ("Grep", "Glob") and rec is None:
            return
        if name in ("Grep", "Glob"):
            root = _resolve(str(inp.get("path") or "."), cwd)
            for line in text.split("\n") if not error else []:
                m = GREP_PATH_LINE.match(line)
                if m:
                    p = _resolve(m.group(1), root)
                    f = rec.file(p)
                    src = rec.source(f, f"{name} {inp.get('pattern', '')}", "hit", view, error)
                    rec.block(f, src, {"t": "hits", "rows": [[int(m.group(2)), m.group(3)[:LINE_CHARS]]]})
                elif line.strip().startswith("/") and " " not in line.strip():
                    f = rec.file(_resolve(line.strip(), root))
                    rec.block(f, rec.source(f, f"{name} {inp.get('pattern', '')}", "hit", view, error),
                              {"t": "note", "text": "listed by name"})
            return

    # the turns, first: which one is wanted
    starts = []
    for i, (row_id, typ, at, parts) in enumerate(evs):
        said = [p["text"] for p in parts if p["kind"] == "text" and p.get("role") == "user"]
        if said and typ == "user_message":
            starts.append((i, row_id, at, said[0]))
    heads = [_Turn(n, row_id, at, t) for n, (i, row_id, at, t) in enumerate(starts)]
    pick = len(heads) - 1 if turn is None or not heads else max(0, min(turn, len(heads) - 1))
    want = heads[pick] if heads else None
    # then every call, in order, each with its result, keeping what is known of each file
    begins = {i: heads[n] for n, (i, *_rest) in enumerate(starts)}
    cur: Optional[_Turn] = None
    order: List[tuple] = []                          # (turn, call part), in the order called
    results: Dict[str, dict] = {}
    for i, (row_id, typ, at, parts) in enumerate(evs):
        cur = begins.get(i, cur)
        head = cur.head if cur is not None else {"replies": [], "now": None}   # before the first message: kept nowhere
        for p in parts:
            if p["kind"] == "call":
                order.append((cur, p))
                if p.get("id"):
                    calls[p["id"]] = p
                inp = p.get("input") if isinstance(p.get("input"), dict) else {"input": p.get("input")}
                head["now"] = {"kind": "call", "id": p.get("id"), "text": _label(p.get("name") or "", inp, p.get("input"), cwd)}
            elif p["kind"] == "result" and p.get("id"):
                results[p["id"]] = dict(p, row_id=row_id)      # where it is stored: its image is fetched from there
                if (head["now"] or {}).get("id") == p["id"]:
                    head["now"] = None
            elif p["kind"] == "text" and p.get("role") == "assistant" and p["text"].strip():
                head["replies"].append({"kind": "text", "text": p["text"][:REPLY_CHARS]})
                head["now"] = None
            elif p["kind"] == "thinking":                    # a run of thinking between two replies: one, its words gathered
                said = head["replies"]
                if not said or said[-1]["kind"] != "thinking":
                    said.append({"kind": "thinking", "texts": []})
                if p["text"].strip():
                    said[-1]["texts"].append(p["text"][:REPLY_CHARS])
                head["now"] = {"kind": "thinking"}
    for t, p in order:
        apply(t, p, results.get(p.get("id")) if p.get("id") else None)
    out = {"turns": [h.head for h in heads], "turn": pick if heads else None, "files": [], "commands": []}
    if want is None:
        return out
    for path in want.order:
        f = want.files[path]
        room = MAX_ROWS                              # the most lines one file shows, over all its calls
        for src in f["sources"]:
            for b in src["blocks"]:
                key = "rows" if b["t"] == "hits" else "lines" if b["t"] in ("lines", "append", "output") else None
                if key:
                    b["cut"] = max(0, len(b[key]) - room)
                    b[key] = [x[:LINE_CHARS] if isinstance(x, str) else x for x in b[key][:room]]
                    room = max(0, room - len(b[key]))
        out["files"].append({"path": path, "kinds": sorted(f["kinds"]), "created": f["created"],
                             "temporary": temporary(path), "sources": f["sources"]})
    for c in want.commands:
        c["temporary"] = bool(c["files"]) and all(temporary(p) for p in c["files"])
    out["commands"] = want.commands
    return out


IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}


def image(gatherer: str, row_id: int, call_id: str) -> Optional[tuple]:
    """The image a call's result holds, as stored in event `row_id`: (media type, bytes), or None.
    Claude Code's {"type": "image", "source": {"media_type", "data"}}, or codex's input_image with a
    data URL."""
    conn = data._connect(gatherer)
    if conn is None:
        return None
    try:
        row = conn.execute("SELECT payload_json FROM events WHERE row_id = ?", (row_id,)).fetchone()
    finally:
        conn.close()
    try:
        payload = json.loads(row["payload_json"]) if row else None
    except (TypeError, ValueError):
        return None

    def found(value, inside: bool):
        if isinstance(value, list):
            for v in value:
                got = found(v, inside)
                if got:
                    return got
        elif isinstance(value, dict):
            mine = inside or value.get("tool_use_id") == call_id or value.get("call_id") == call_id
            src = value.get("source")
            if mine and value.get("type") == "image" and isinstance(src, dict) and src.get("type") == "base64":
                return src.get("media_type"), src.get("data")
            url = value.get("image_url")
            if mine and value.get("type") == "input_image" and isinstance(url, str) and url.startswith("data:"):
                head, _, body = url.partition(",")
                return head[5:].split(";")[0], body
            for v in value.values():
                if isinstance(v, (list, dict)):
                    got = found(v, mine)
                    if got:
                        return got
        return None

    got = found(payload, False)
    if not got or got[0] not in IMAGE_TYPES or not isinstance(got[1], str):
        return None
    try:
        return got[0], base64.b64decode(got[1], validate=False)
    except (ValueError, binascii.Error):
        return None
