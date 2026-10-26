"""The files a session worked on, one turn at a time: for each file, the calls that touched it,
each with what it did -- the lines it read (by the Read tool, or by a shell command that only
prints part of a file: `sed -n`, `cat`, `head`, `tail`, `nl`, `grep -n`), the matches it found, or
what it changed, at the lines where: by an edit tool, or by a shell command whose change can be
read from it (`cat > F <<EOF`, `tee`, `sed -i`, a Python script that replaces constant strings in a
file and writes it back).

A codex code-mode call (`exec`: a script that calls the other tools) is read as the calls its script
makes (commands.opened_script), each in the list of commands and touching files as itself would.

A turn is what follows one of the user's messages, up to the next -- not counting one written while
the turn ran (Claude Code sent it mid-turn, or held it until the turn ended), which is part of it. Each call is read from the
event's parts (data.parts), so whichever harness wrote it; only the tools' names differ.

Where ag's hook server checked a call against the disk as it ran (`_touches`, written by
ag/integrations/tools/ag_orchestrator/file_touches/), that is what is shown of it: the files it read, kept where the
file says so, each marked checked (what the call showed of it is on disk) or not; what it changed,
at the lines the file itself says; and the files that changed while it ran, which it doesn't name.
A change it found to a file in ag's home (the databases and logs ag writes as calls run) is left out
unless the call says it writes the file -- as the hook server now does itself, for what it kept before.

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
import textwrap
from typing import Dict, List, Optional

from . import data, queued, work
from . import home as paths
from .commands import (  # noqa: F401 - python_changes: tested here
    CODE_MODE, EDITS, GLOB, GREP_PATH_LINE, READ_LINE, SHELLS, _patch_files, _resolve, _shell_text, opened_script,
    python_changes, script_calls, script_output, shell_changes, shell_reads)

MAX_ROWS = 4000            # the most lines one file shows in a turn
HELD_SECONDS = 30          # a message held until its turn ended: stored this close to when Claude Code sent it
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
    for r in ("/tmp", "/private/tmp", "/var/tmp", "/var/folders", tempfile.gettempdir(), os.environ.get("TMPDIR") or ""):
        if r:                                                          # macOS's /tmp is /private/tmp: named
            roots |= {os.path.normpath(r), os.path.realpath(r)}        # either way, on any system
    return tuple(sorted(roots))


TEMPORARY = _temporary_roots()   # the temporary folders: /tmp, macOS's per-user /var/folders/..., $TMPDIR


def ags(path: str) -> bool:
    """Whether `path` is in ag's home (AG_HOME, ~/.ag), whose files ag itself writes as calls run: its
    databases at every model call, its logs."""
    roots = {paths.HOME, os.path.realpath(paths.HOME)}
    return any(path == r or path.startswith(r.rstrip("/") + "/") for r in roots)


def says_writes(name: str, raw, cwd: str) -> set:
    """The files a call (its input, `raw`) says it changes: an edit tool's, or a shell command's that says so."""
    if name in SHELLS:
        command, workdir = _shell_text(name, raw)
        return {p for p, _, _ in shell_changes(command, _resolve(workdir, cwd) if workdir else cwd)[0]}
    if name not in EDITS:
        return set()
    inp = raw if isinstance(raw, dict) else {"input": raw}
    out = {_resolve(str(inp[k]), cwd) for k in ("file_path", "notebook_path") if isinstance(inp.get(k), str) and inp[k]}
    body = inp.get("input") if isinstance(inp.get("input"), str) else inp.get("patch") or ""
    return out | {_resolve(p, cwd) for p, _, _ in _patch_files(str(body))}


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
        self.head = {"n": n, "row_id": row_id, "at": at, "text": text[:REPLY_CHARS], "replies": [], "now": None, "more": [],
                     "last": None}
        self.acts: Dict[str, dict] = {}              # its calls, by id, for what it is doing (work.summary)
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
    """A call in a line: its own description, else its tool and what it worked on -- a code-mode
    script, the calls it makes."""
    if name == CODE_MODE and isinstance(raw, str) and script_calls(raw):
        return " · ".join(_label(n, a if isinstance(a, dict) else {"input": a}, a, cwd) or n
                          for n, a in script_calls(raw))[:200]
    if isinstance(inp.get("description"), str) and inp["description"].strip():
        return inp["description"].strip()[:200]
    if name in SHELLS:
        command, _ = _shell_text(name, raw)
        return re.sub(r"^cd \S+ && ", "", command.strip().split("\n")[0])[:200]
    if name == "Skill" and isinstance(inp.get("skill"), str):
        args = inp.get("args") if isinstance(inp.get("args"), str) else ""
        return f"Load skill {inp['skill']}{' ' + args if args.strip() else ''}"[:200]
    if name == "ToolSearch" and isinstance(inp.get("query"), str):    # Claude Code loading tools it was told of by name
        q = inp["query"].strip()
        picked = [tool_name(t.strip()) for t in q[len("select:"):].split(",") if t.strip()] if q.startswith("select:") else []
        return (f"Load {', '.join(picked)}" if picked else f"Search tools: {q}")[:200]
    path = inp.get("file_path") or inp.get("notebook_path")
    target = path if isinstance(path, str) and path else inp.get("pattern") or inp.get("query") \
        or inp.get("url") or inp.get("skill") or inp.get("prompt") or ""
    if isinstance(target, str) and target == path:
        target = short_path(target, cwd)
    elif isinstance(target, str) and cwd and target.startswith(cwd.rstrip("/") + "/"):
        target = target[len(cwd.rstrip("/")) + 1:]
    return f"{tool_name(name)} {target if isinstance(target, str) else ''}".strip()[:200]


MCP_TOOL = re.compile(r"^mcp__([^_]+(?:_[^_]+)*)__(.+)$")                # an MCP server's tool: mcp__<server>__<tool>
MEMORY = re.compile(r"/\.claude/projects/[^/]+/memory(/.*)?$")           # Claude Code's memory of a project's directory


def tool_name(name: str) -> str:
    """A tool's name as read: an MCP server's as "server · tool"."""
    m = MCP_TOOL.match(name or "")
    return f"{m.group(1)} · {m.group(2)}" if m else name


def short_path(path: str, cwd: str) -> str:
    """A file's path in a call's line: from the session's directory; a file of Claude Code's memory as
    memory/<file>; else from the home folder (~), or whole."""
    if cwd and path.startswith(cwd.rstrip("/") + "/"):
        return path[len(cwd.rstrip("/")) + 1:]
    m = MEMORY.search(path)
    if m:
        return "memory" + (m.group(1) or "")
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path.startswith(home + "/") else path


def _opened(part: dict, result: Optional[dict]) -> List[tuple]:
    """[(call, its result)]: a code-mode script's calls, each with its own result (commands.opened_script),
    as the hook server checked them -- the last also with what the script printed (`printed`), shown as its
    output; any other call as it is."""
    raw = part.get("input")
    inner = opened_script(part.get("id"), raw, None if result is None else (result.get("text") or "", bool(result.get("error")))) \
        if part.get("name") == CODE_MODE and isinstance(raw, str) and part.get("id") else []
    if not inner:
        return [(part, result)]
    printed = script_output(result.get("text") or "")[0] if result is not None else ""
    return [(dict(part, id=iid, name=name, input=inp),
             None if got is None else dict(result, text=got[0], error=got[1], printed=printed if n == len(inner) else got[0]))
            for n, (iid, name, inp, got) in enumerate(inner, 1)]


def _call_view(part: dict) -> dict:
    """A call as its source shows it: its tool, and its input clipped."""
    return {"name": part.get("name"), "input": data._clip(part.get("input"), COMMAND_OUTPUT)}


# ------------------------------------------------------------------ Claude Code's notes, as the conversation shows them

SKILL = re.compile(r"^\s*Base directory for this skill: ([^\n]*)\n+([\s\S]*?)(?:\n+ARGUMENTS: ([\s\S]*?))?\s*$")
AGENT_MESSAGE = re.compile(r'<agent-message from="([^"]*)"[^>]*>\n?([\s\S]*?)\n?</agent-message>')
# another session's message, sent to this one (Claude Code's SendMessage across sessions), as it hands it on: the sender's
# name in `from-name` (its socket in `from`), and after the tag Claude Code's own caution about it
PEER_MESSAGE = re.compile(r'<cross-session-message\b([^>]*)>\n?([\s\S]*?)\n?</cross-session-message>')
REPORT_FOLLOWS = "The report follows:\n"
RAN = re.compile(r"^\s*<command-name>/?([^<]*)</command-name>\s*<command-message>[^<]*</command-message>"
                 r"\s*(?:<command-args>([\s\S]*?)</command-args>)?\s*$")
PRINTED = re.compile(r"^\s*<bash-stdout>([\s\S]*?)</bash-stdout>\s*(?:<bash-stderr>([\s\S]*?)</bash-stderr>)?\s*$")
AGENT_ID = re.compile(r"\bagentId: ([\w-]+)")
MENTIONED = re.compile(r"Called the Read tool with the following input: (\{[^\n]*\})\nResult of calling the Read tool:\n")
LOADED = re.compile(r"(?:^|\n)Contents of (/[^\n]*?)(?: \([^)\n]*\))?:\n\n")


def _note(text: str) -> Optional[dict]:
    """What a note of Claude Code's in the conversation is, as the Chat view shows it; None for one it doesn't:
        {kind: "skill", name, args, text}   a skill's instructions, loaded by the Skill tool or the user's /name
        {kind: "report", from, text}        another session's message: a subagent's report as it hands back
        {kind: "peer", name, text}          another session's message: one another Claude session sent this one
        {kind: "command", name}             a command the user ran that Claude Code runs itself (/context, /mcp): not
                                            shown, only matched with what was sent from the page
        {kind: "printed", text}             what a command the user ran with ! printed"""
    m = SKILL.match(text)
    if m:
        return {"kind": "skill", "name": os.path.basename(m.group(1).strip().rstrip("/")), "args": (m.group(3) or "").strip(),
                "text": m.group(2).strip()[:REPLY_CHARS]}
    m = AGENT_MESSAGE.search(text) if text.lstrip().startswith(("Another Claude session sent a message:", "<agent-message ")) else None
    if m:
        body = m.group(2)
        if REPORT_FOLLOWS in body:                   # a hand-back: the report, each of its lines indented by Claude Code
            body = textwrap.dedent(body.split(REPORT_FOLLOWS, 1)[1])
        return {"kind": "report", "from": m.group(1), "text": body.strip()[:REPLY_CHARS]}
    m = PEER_MESSAGE.search(text) if text.lstrip().startswith("Another Claude session sent a message:") else None
    if m:
        who = dict(re.findall(r'([\w-]+)="([^"]*)"', m.group(1)))
        return {"kind": "peer", "name": who.get("from-name") or who.get("from") or "", "text": m.group(2).strip()[:REPLY_CHARS]}
    m = RAN.match(text)
    if m:
        args = (m.group(2) or "").strip()
        return {"kind": "command", "name": "/" + m.group(1).strip() + (f" {args}" if args else "")}
    m = PRINTED.match(text)
    if m:
        return {"kind": "printed", "text": "\n".join(x for x in (m.group(1).rstrip("\n"), (m.group(2) or "").rstrip("\n")) if x)[:COMMAND_OUTPUT]}
    return None


def _loaded(text: str) -> List[tuple]:
    """The files a note of Claude Code's gives the agent the lines of, not by a call of its own: one the user
    @-mentioned (read as the Read tool reads it), the CLAUDE.md files and memory it loads ("Contents of <path>:")
    -- each (path, [(n, line)], how)."""
    out = []
    for m in MENTIONED.finditer(text):
        try:
            path = json.loads(m.group(1)).get("file_path")
        except (ValueError, AttributeError):
            continue
        rows = []
        for line in text[m.end():].split("\n"):
            r = READ_LINE.match(line)
            if not r:
                break
            rows.append((int(r.group(1)), r.group(2)))
        if isinstance(path, str) and path:
            out.append((path, rows, "@-mentioned: read into the message by Claude Code"))
    found = list(LOADED.finditer(text))
    for k, m in enumerate(found):
        body = text[m.end():found[k + 1].start() if k + 1 < len(found) else len(text)]
        body = re.sub(r"\n*</system-reminder>[\s\S]*$", "", body).rstrip("\n")
        out.append((m.group(1), list(enumerate(body.split("\n"), 1)), "loaded into the context by Claude Code"))
    return out


def files(gatherer: str, channel: str, turn: Optional[int] = None, cwd: str = "") -> dict:
    """The session's turns ({n, row_id, at, text, more, replies, now, last, work}: what the user asked, and what they wrote while it
    ran ({row_id, at, text}: sent mid-turn, or held until it ended; queued.py) -- part of it, not a turn of its own; what the agent
    said back and thought, in order -- each {kind: "text", text} or {kind: "thinking", texts} (a run of
    thinking between two replies, its readable words: none when encrypted), and among them a subagent's report
    handed back (`_note`): {kind: "report", name (what the subagent was started for, else ""), text}; `ran`, the commands the user ran that Claude Code runs itself (/context,
    /mcp: not shown, but what was sent from the page is matched with them); `output`, what a command the user
    ran with ! printed, when it is one; what it was doing
    last -- {kind: "thinking"}, {kind: "call", id, text} (a call with no result yet), or None; and its latest
    call while nothing readable was said or thought after it -- {id, text, call, running, error, output} -- or
    None; and what its calls are doing and how they ended, work.summary's), and for turn `turn` (None:
    the latest) the files it worked on, in the order first touched, each
        {path, kinds (read, edit, write, hit), created,
         sources: [{via, kind, kinds, error, call, blocks}]: the calls that touched it, in order, each
         with what it did to it -- blocks of {t: "lines", start (None: not known), lines} (read),
         {t: "hits", rows: [[n, text]]}, {t: "diff", at (None: not found), old, new, above, below
         ([[n, text]]: known lines around it)}, {t: "write", lines, created}, {t: "append", lines},
         {t: "image", row_id, id} (fetched by `image`), {t: "note", text}}; `call` None for a file Claude Code
         gave the agent the lines of itself (`_loaded`: one the user @-mentioned, a CLAUDE.md, its memory)
    and every call it made, in order: {text, error, running, call, output, files (the paths it touched)} -- a skill
    loaded with them, as its Skill call, its instructions its output, or as a call of its own when the user typed its /name.
    A source the hook server checked on disk also has `checked` (True: what the call showed of the file
    is on disk; False: it is not; None: nothing to match), and `unnamed` when the file changed while
    the call ran but the call doesn't name it; its kinds may be "delete" too. A file in a temporary
    folder (`temporary`) has `temporary` true, and so has a call whose every file is in one.
    Relative paths in shell commands are taken from `cwd` (the session's directory). `home`: the
    user's home folder, which the page shows as ~."""
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
        said = None
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
            if how in ("created", "modified", "deleted") and ags(path):
                said = says_writes(part.get("name") or "", part.get("input"), cwd) if said is None else said
                if path not in said:
                    continue                                # ag's own write: kept before the hook server left them out
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

    def loaded(t: Optional[_Turn], part: dict) -> None:
        """A file Claude Code gave the agent the lines of in a note (`_loaded`): read, at its line numbers."""
        path = part["path"]
        for n, line in part["rows"]:
            knows(path).rows[n] = {"text": line}
        rec = t if t is not None and t is want else None
        if rec:
            rec.current = None                                  # no call of the agent's
            f = rec.file(path)
            src = rec.source(f, part["via"], "read", None, False)
            for start, lines in _runs(part["rows"]):
                rec.block(f, src, {"t": "lines", "start": start, "lines": lines})

    def skilled(t: Optional[_Turn], n: dict) -> None:
        """A skill Claude Code loaded (`_note`), among the turn's calls: the Skill call that loaded it, its instructions
        as its output; else, the user having typed its /name, a call of its own."""
        rec = t if t is not None and t is want else None
        if rec is None:
            return
        rec.current = None
        last = rec.commands[-1] if rec.commands else None
        call = (last or {}).get("call") or {}
        inp = call.get("input") if isinstance(call.get("input"), dict) else {}
        asked = str(inp.get("skill") or "") if call.get("name") == "Skill" else ""
        if asked and (asked == n["name"] or asked.endswith(":" + n["name"])) and not last.get("loaded"):
            last.update(output=n["text"][:COMMAND_OUTPUT], loaded=True)
            return
        rec.commands.append({"text": f"Load skill {n['name']}{' ' + n['args'] if n['args'] else ''}"[:200], "error": False,
                             "running": False, "call": {"name": "Skill", "input": {"skill": n["name"], "args": n["args"]}},
                             "output": n["text"][:COMMAND_OUTPUT], "files": [], "loaded": True})

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
                "call": view, "output": (result or {}).get("printed", text)[:COMMAND_OUTPUT], "files": []}
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

    # the turns, first: which one is wanted. A message the user wrote while a turn ran is part of it, not a turn of
    # its own: one Claude Code sent mid-turn (wrapped), or held until the turn ended and sent then, as its record
    # says (queued.py's `meanwhile`: matched by its words, stored as it was sent)
    held = queued.meanwhile(channel, cwd)
    starts, more = [], {}                            # more: what was written while a turn ran, by the turn it is part of
    for i, (row_id, typ, at, parts) in enumerate(evs):
        said = [p["text"] for p in parts if p["kind"] == "text" and p.get("role") == "user"]
        if said and typ == "user_message":
            text = queued.mid_turn(said[0])
            meanwhile = text is not None
            if not meanwhile and at is not None:
                q = next((q for q in held if q["text"].strip() == said[0].strip() and abs(at - q["sent"]) <= HELD_SECONDS), None)
                if q is not None:
                    held.remove(q)
                    meanwhile = True
            text = said[0] if text is None else text
            if meanwhile and starts:
                more.setdefault(len(starts) - 1, []).append({"row_id": row_id, "at": at, "text": text.rstrip()[:REPLY_CHARS]})
            else:
                starts.append((i, row_id, at, text))
    heads = [_Turn(n, row_id, at, t) for n, (i, row_id, at, t) in enumerate(starts)]
    for n, got in more.items():
        heads[n].head["more"] = got
    pick = len(heads) - 1 if turn is None or not heads else max(0, min(turn, len(heads) - 1))
    want = heads[pick] if heads else None
    # then every call, in order, each with its result, keeping what is known of each file
    begins = {i: heads[n] for n, (i, *_rest) in enumerate(starts)}
    # Claude Code's notes stored just before a user's message came with it (ag stores them ahead of it): the files they
    # give the agent are that turn's
    ahead, nxt = [None] * len(evs), None
    for i in range(len(evs) - 1, -1, -1):
        if i in begins:
            nxt = begins[i]
        elif any(p["kind"] != "note" for p in evs[i][3]):
            nxt = None
        ahead[i] = nxt
    cur: Optional[_Turn] = None
    order: List[tuple] = []                          # (turn, call part), in the order called
    results: Dict[str, dict] = {}
    agents: Dict[str, str] = {}                      # a subagent's id: what it was started for (its call's description)
    for i, (row_id, typ, at, parts) in enumerate(evs):
        cur = begins.get(i, cur)
        head = cur.head if cur is not None else {"replies": [], "now": None, "last": None}   # before the first message: kept nowhere
        acts = cur.acts if cur is not None else {}
        for p in parts:
            if p["kind"] == "call":
                order.append((cur, p))
                if p.get("id"):
                    calls[p["id"]] = p
                inp = p.get("input") if isinstance(p.get("input"), dict) else {"input": p.get("input")}
                label = _label(p.get("name") or "", inp, p.get("input"), cwd)
                head["now"] = {"kind": "call", "id": p.get("id"), "text": label}
                head["last"] = {"id": p.get("id"), "text": label, "call": _call_view(p), "running": True, "error": False, "output": ""}
                acts[p.get("id") or f"#{len(acts)}"] = {"id": p.get("id"), "kind": work.doing(p.get("name") or "", p.get("input")),
                                                         "ended": None, "ok": True}
            elif p["kind"] == "result" and p.get("id"):
                results[p["id"]] = dict(p, row_id=row_id)      # where it is stored: its image is fetched from there
                if p["id"] in acts and acts[p["id"]]["ended"] is None:
                    a = acts[p["id"]]
                    a.update(ended=at or 0, seq=len(results), ok=work.ok(a["kind"], bool(p.get("error")), p.get("text") or ""))
                if (head["now"] or {}).get("id") == p["id"]:
                    head["now"] = None
                if (head["last"] or {}).get("id") == p["id"]:
                    head["last"].update(running=False, error=bool(p.get("error")), output=(p.get("text") or "")[:COMMAND_OUTPUT])
                started = calls.get(p["id"]) or {}
                m = AGENT_ID.search(p.get("text") or "") if started.get("name") in ("Agent", "Task") else None
                if m:
                    agents[m.group(1)] = str((started.get("input") or {}).get("description") or "")
            elif p["kind"] == "text" and p.get("role") == "assistant" and p["text"].strip():
                head["replies"].append({"kind": "text", "text": p["text"][:REPLY_CHARS]})
                head["now"] = head["last"] = None
            elif p["kind"] == "thinking":                    # a run of thinking between two replies: one, its words gathered
                said = head["replies"]
                if not said or said[-1]["kind"] != "thinking":
                    said.append({"kind": "thinking", "texts": []})
                if p["text"].strip():
                    said[-1]["texts"].append(p["text"][:REPLY_CHARS])
                    head["last"] = None                      # shown after the call: the call is no longer the last
                head["now"] = {"kind": "thinking"}
            elif p["kind"] == "note":                        # Claude Code's own: a report, a message, a skill loaded, a ! command's output
                n = _note(p.get("text") or "")
                if n is None:
                    pass
                elif n["kind"] == "report":
                    n["name"] = agents.get(n.pop("from"), "")
                    head["replies"].append(n)
                elif n["kind"] == "peer":
                    head["replies"].append(n)
                elif n["kind"] == "skill":                   # among the calls, not the conversation (skilled)
                    order.append((cur, n))
                    if ((head["last"] or {}).get("call") or {}).get("name") == "Skill":
                        head["last"]["output"] = n["text"][:COMMAND_OUTPUT]
                elif n["kind"] == "command":
                    head.setdefault("ran", []).append(n["name"])
                else:
                    head["output"] = n["text"]               # what a ! command printed: under it
                for path, rows, how in _loaded(p.get("text") or ""):
                    order.append((ahead[i] or cur, {"kind": "loaded", "path": path, "rows": rows, "via": how}))
    for t, p in order:
        if p["kind"] == "loaded":
            loaded(t, p)
        elif p["kind"] == "skill":
            skilled(t, p)
        else:                                        # a codex script: the calls it makes
            for q, r in _opened(p, results.get(p.get("id")) if p.get("id") else None):
                apply(t, q, r)
    for h in heads:                                  # its newest call, while nothing readable was said or thought after it
        h.head["work"] = dict(work.summary(list(h.acts.values())), **({} if h.head["last"] else {"last": None}))
    out = {"turns": [h.head for h in heads], "turn": pick if heads else None, "files": [], "commands": [],
           "home": os.path.expanduser("~")}
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
