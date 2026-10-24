"""The files a session worked on, one turn at a time: for each file, the calls that touched it,
each with what it did -- the lines it read (by the Read tool, or by a shell command that only
prints part of a file: `sed -n`, `cat`, `head`, `tail`, `nl`, `grep -n`), the matches it found, or
what it changed, at the lines where: by an edit tool, or by a shell command whose change can be
read from it (`cat > F <<EOF`, `tee`, `sed -i`, a Python script that replaces constant strings in a
file and writes it back).

A turn is what follows one of the user's messages, up to the next. Each call is read from the
event's parts (data.parts), so whichever harness wrote it; only the tools' names differ.

ag stores what the model saw, not the files: a Read's lines carry their numbers, but an edit
carries only the text it replaced. An edit is placed by finding that text among the lines seen
of the file so far in the session (earlier turns too); one that is not found is listed apart.
The files themselves are never read: they show what the agent saw then, not what is there now."""
import ast
import base64
import binascii
import json
import os
import re
import shlex
from typing import Dict, List, Optional

from . import data

MAX_ROWS = 4000            # the most lines one file shows in a turn
LINE_CHARS = 400           # the most of one line's text sent
COMMAND_OUTPUT = 4000      # the most of a command's output sent
CONTEXT = 2                # the lines known around a change shown with it
REPLY_CHARS = 4000         # the most of a user message or one of the agent's replies sent

READ_LINE = re.compile(r"^\s*(\d+)(?:\t|→)(.*)$")              # a Read result's line: "12\ttext"
GREP_LINE = re.compile(r"^(\d+)[:-](.*)$")                       # grep -n on one file: "12:text"
GREP_PATH_LINE = re.compile(r"^([^\s:][^:]*):(\d+)[:-](.*)$")    # grep -n on several: "a/b.py:12:text"
SED_RANGE = re.compile(r"^(\d+)(?:,(\d+|\$))?p$")
SHELLS = {"Bash", "shell", "exec_command", "local_shell", "shell_command"}
EDITS = {"Edit", "MultiEdit", "Write", "NotebookEdit", "apply_patch"}


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


# ------------------------------------------------------------------ shell commands that read files

def _segments(command: str):
    """A shell command's simple commands, in order, each its words and the operator after it
    ("&&", ";", "|", ...); None when it is not plain enough to read (substitutions, heredocs)."""
    if any(s in command for s in ("$(", "`", "<<", "<(")):
        return None
    try:
        lex = shlex.shlex(command, posix=True, punctuation_chars=";&|")
        lex.whitespace_split = True
        lex.commenters = ""
        words = list(lex)
    except ValueError:
        return None
    segs, cur = [], []
    for w in words:
        if w and set(w) <= set(";&|"):
            segs.append((cur, w))
            cur = []
        else:
            cur.append(w)
    segs.append((cur, ""))
    return [(w, op) for w, op in segs if w]


def _resolve(path: str, cwd: str) -> str:
    path = os.path.expanduser(path)
    return os.path.normpath(path if os.path.isabs(path) or not cwd else os.path.join(cwd, path))


def _read_command(words: List[str]):
    """What a simple command reads: {"kind": "range", path, start, count (None: to its end)},
    {"kind": "numbered", path} (output lines carry their numbers), {"kind": "tail", path, count},
    {"kind": "grep", paths, numbered}, or None."""
    cmd, args = words[0], words[1:]
    opts = [a for a in args if a.startswith("-") and a != "-"]
    files = [a for a in args if not a.startswith("-")]
    if cmd == "sed" and "-n" in args:
        rest = [a for a in args if a != "-n"]
        if len(rest) == 2 and not rest[1].startswith("-"):
            m = SED_RANGE.match(rest[0])
            if m:
                a = int(m.group(1))
                b = m.group(2)
                count = 1 if b is None else None if b == "$" else int(b) - a + 1
                return {"kind": "range", "path": rest[1], "start": a, "count": count if count is None or count > 0 else 0}
    if cmd == "cat" and len(files) == 1:
        if not opts:
            return {"kind": "range", "path": files[0], "start": 1, "count": None}
        if opts in (["-n"],):
            return {"kind": "numbered", "path": files[0]}
    if cmd == "nl" and len(files) == 1 and all(o in ("-ba", "-b", "a") for o in opts + files[:-1]):
        return {"kind": "numbered", "path": files[-1]}
    if cmd in ("head", "tail"):
        n, rest, i = 10, [], 0
        while i < len(args):
            a = args[i]
            if a == "-n" and i + 1 < len(args) and args[i + 1].lstrip("+").isdigit():
                n = int(args[i + 1].lstrip("+")); i += 2; continue
            if re.fullmatch(r"-n?\d+", a):
                n = int(re.sub(r"\D", "", a)); i += 1; continue
            if a.startswith("-"):
                return None
            rest.append(a); i += 1
        if len(rest) == 1:
            if cmd == "head":
                return {"kind": "range", "path": rest[0], "start": 1, "count": n}
            return {"kind": "tail", "path": rest[0], "count": n}
    if cmd in ("grep", "rg", "egrep"):
        numbered = cmd == "rg" or any("n" in o[1:] for o in opts if not o.startswith("--")) or "--line-number" in opts
        pattern_given = any(o in ("-e", "-f") for o in opts)
        paths = files if pattern_given else files[1:]
        recursive = cmd == "rg" or "--recursive" in opts or any(c in o[1:] for o in opts if not o.startswith("--") for c in "rR")
        return {"kind": "grep", "paths": paths, "numbered": numbered, "single": len(paths) == 1 and not recursive}
    return None


def _head_count(words: List[str]) -> Optional[int]:
    """`head -N`, `head -n N`, `head`: how many lines it keeps; None when it is not a plain head."""
    if words[0] != "head":
        return None
    args = words[1:]
    if not args:
        return 10
    if len(args) == 1 and re.fullmatch(r"-n?\d+", args[0]):
        return int(re.sub(r"\D", "", args[0]))
    if len(args) == 2 and args[0] == "-n" and args[1].isdigit():
        return int(args[1])
    return None


def _units(segs, cwd: str):
    """A command's pipelines, in order, each what its output is: {"read": what it reads (_read_command,
    its path resolved), "size": its lines when known, "form": a pattern its every line has (a numbered
    grep's, cat -n's), "cap": at most this many}; and whether any did more than read."""
    units, other, i = [], False, 0
    while i < len(segs):
        pipe = [segs[i][0]]
        while segs[i][1] == "|" and i + 1 < len(segs):
            i += 1
            pipe.append(segs[i][0])
        i += 1
        words = pipe[0]
        if words[0] == "cd" and len(words) == 2 and len(pipe) == 1:
            cwd = _resolve(words[1], cwd)
            continue
        heads = [_head_count(w) for w in pipe[1:]]
        cap = heads[0] if len(heads) == 1 and heads[0] is not None else None
        plain = len(pipe) == 1 or cap is not None
        r = _read_command(words)
        u = {"read": None, "size": None, "form": None, "cap": cap}
        if words[0] == "echo" and len(pipe) == 1 and not any(w.startswith("-") for w in words[1:2]):
            u["size"] = 1
        elif r is None or not plain:
            other = True
            if r and r["kind"] == "grep" and r["numbered"]:          # filtered on: its lines still have their form
                u["form"] = "grep"
                u["read"] = dict(r, paths=[_resolve(x, cwd) for x in r["paths"]] or [cwd])
        elif r["kind"] == "grep":
            other = True
            if r["numbered"]:
                u["form"] = "grep"
                u["read"] = dict(r, paths=[_resolve(x, cwd) for x in r["paths"]] or [cwd])
        else:
            u["read"] = dict(r, path=_resolve(r["path"], cwd))
            if r["kind"] == "numbered":
                u["form"] = "numbered"
            elif r["kind"] == "range" and r["count"] is not None:
                u["size"] = r["count"] if cap is None else min(r["count"], cap)
            elif r["kind"] == "range" and cap is not None:            # cat F | head -N
                u["read"]["count"] = u["size"] = cap
            elif r["kind"] == "tail":
                u["size"] = r["count"]
        units.append(u)
    return units, other


NUMBERED_LINE = re.compile(r"^\s*\d+\t")


def _fits(u: dict, line: str) -> bool:
    if u["form"] == "numbered":
        return bool(NUMBERED_LINE.match(line))
    if u["form"] == "grep":
        return bool(GREP_PATH_LINE.match(line) or (GREP_LINE.match(line) and u["read"]["single"]))
    return False


def shell_reads(command: str, output: str, cwd: str):
    """What a shell command read, from its output: [(path, "lines", start, lines)] for its parts that
    print a file (start None: where in it is not known), [(path, "hit", n, text)] for numbered search
    matches, [(path, "unsplit", None, [])] for a read whose lines cannot be told apart from the rest;
    and whether the command did anything but read.
    Its output is shared out among its parts from the front while each one's size is known (sed -n
    A,Bp prints B-A+1 lines, echo one) or its lines have a form of their own (grep -n's "12:", cat -n's),
    then the same from the back; a part of unknown size between the two cannot be told apart."""
    segs = _segments(command)
    if segs is None:
        return [], True
    units, other = _units(segs, cwd)
    out = output.split("\n") if output else []
    while out and out[-1] == "":
        out.pop()
    spans: Dict[int, tuple] = {}

    def take(u, lines, frm, back):
        """How many lines `u` takes at `frm` (forward) or ending at `frm` (backward); None: unknown."""
        if u["size"] is not None:
            return u["size"]
        if u["form"]:
            n = 0
            while n < (u["cap"] or 10 ** 9):
                k = frm + n if not back else frm - 1 - n
                if k < 0 or k >= len(lines) or not _fits(u, lines[k]):
                    break
                n += 1
            return n
        return None

    pos, front = 0, 0
    for idx, u in enumerate(units):
        n = take(u, out, pos, False)
        if n is None:
            break
        if idx == len(units) - 1 and u["size"] is not None:     # the last: what is left, at most its size
            n = min(n, len(out) - pos)
        spans[idx] = (pos, pos + n)
        pos += n
        front = idx + 1
    if front < len(units):
        end = len(out)
        for idx in range(len(units) - 1, front - 1, -1):
            u = units[idx]
            n = take(u, out, end, True)
            if n is None:
                if idx == front:                                  # the only one left: all between
                    spans[idx] = (pos, end)
                break
            spans[idx] = (max(pos, end - n), end)
            end -= n
    found = []
    for idx, u in enumerate(units):
        r = u["read"]
        if not r:
            continue
        if idx not in spans:
            if r["kind"] != "grep":
                found.append((r["path"], "unsplit", None, []))
            continue
        lines = out[spans[idx][0]:spans[idx][1]]
        if r["kind"] == "grep":
            for t in lines:
                m = GREP_LINE.match(t)
                if m and r["single"]:
                    found.append((r["paths"][0], "hit", int(m.group(1)), m.group(2)))
                    continue
                m = GREP_PATH_LINE.match(t)
                if m:
                    found.append((_resolve(m.group(1), cwd), "hit", int(m.group(2)), m.group(3)))
        elif r["kind"] == "numbered":
            for t in lines:
                m = re.match(r"^\s*(\d+)\t(.*)$", t)
                if m:
                    found.append((r["path"], "lines", int(m.group(1)), [m.group(2)]))
        elif r["kind"] == "tail":
            found.append((r["path"], "lines", None, lines))
        else:
            found.append((r["path"], "lines", r["start"], lines[:r["count"]] if r.get("count") else lines))
    return found, other


def _shell_text(name: str, inp) -> (str, Optional[str]):
    """A shell call's command and its working directory, whichever harness's."""
    if not isinstance(inp, dict):
        return str(inp or ""), None
    c = inp.get("command", inp.get("cmd", ""))
    if isinstance(c, list):
        c = c[2] if len(c) >= 3 and c[0] in ("bash", "sh", "zsh") and c[1] in ("-lc", "-c") else " ".join(c)
    return str(c or ""), inp.get("workdir") or inp.get("cwd")


# ------------------------------------------------------------------ shell commands that change files

HEREDOC = re.compile(r"<<(-?)\s*(['\"]?)([A-Za-z_][\w.-]*)\2")
REDIRECT_TO = {">", ">>", ">|", "&>", "&>>"}
NOT_A_FILE = {"/dev/null", "/dev/stdout", "/dev/stderr"}


def _heredocs(command: str):
    """The command with each heredoc's body taken out and its `<<EOF` made `<< \\x00N`, and the bodies."""
    lines, bodies, out, waiting = command.split("\n"), [], [], []
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        found = list(HEREDOC.finditer(line))
        for m in reversed(found):
            line = line[:m.start()] + f"<< \x00{len(bodies) + found.index(m)}" + line[m.end():]
        out.append(line)
        for m in found:
            body = []
            while i < len(lines) and (lines[i].lstrip("\t") if m.group(1) else lines[i]) != m.group(3):
                body.append(lines[i])
                i += 1
            i += 1                                       # the delimiter
            bodies.append("\n".join(body))
    return out, bodies


def _simple_commands(command: str):
    """A shell command's simple commands, in order: (words, redirections [(op, target)]), heredoc
    bodies standing as their text; None when it cannot be read."""
    lines, bodies = _heredocs(command)
    words, buf = [], ""
    for line in lines:                                   # a line is a command, unless a quote runs on
        buf = buf + "\n" + line if buf else line
        try:
            lex = shlex.shlex(buf, posix=True, punctuation_chars=";&|<>")
            lex.whitespace_split = True
            lex.commenters = ""
            got = list(lex)
        except ValueError:
            continue
        words += got + [";"]
        buf = ""
    if buf:
        return None
    cmds, cur, redirs, k = [], [], [], 0
    while k < len(words):
        w = words[k]
        if w and set(w) <= set(";&|"):
            if cur or redirs:
                cmds.append((cur, redirs))
            cur, redirs = [], []
        elif w and set(w) <= set("<>&|") and k + 1 < len(words):
            fd = None
            if cur and cur[-1].isdigit() and re.search(rf"(?<![\w-]){cur[-1]}{re.escape(w)}", command):
                fd = cur.pop()                           # 2>file: the fd is not an argument
            t = words[k + 1]
            if t.startswith("\x00") and t[1:].isdigit():
                t = bodies[int(t[1:])]
            if fd not in ("2",):                         # stderr: a log, not what the command wrote
                redirs.append((w, t))
            k += 1
        else:
            cur.append(w)
        k += 1
    if cur or redirs:
        cmds.append((cur, redirs))
    return cmds


def shell_changes(command: str, cwd: str):
    """What a shell command changed: [(path, how, what)] -- "write" (what: the whole new text),
    "append" (what: the text added at its end), "pairs" (what: [(old, new)], from a Python script's
    replacements), "changed" (what: how it was changed, not which lines) -- and whether that is all it
    did: a script, or a command that also ran something else, is a command as well."""
    cmds = _simple_commands(command)
    if cmds is None:
        return [], False
    out, pure, env = [], True, {}

    def expand(w: str) -> str:
        return re.sub(r"\$(?:\{(\w+)\}|(\w+))", lambda m: env.get(m.group(1) or m.group(2), m.group(0)), w)

    for words, redirs in cmds:
        if words and all(re.fullmatch(r"[A-Za-z_]\w*=.*", w, re.S) for w in words):   # S=/tmp/x
            for w in words:
                k, v = w.split("=", 1)
                env[k] = expand(v)
            continue
        words = [expand(w) for w in words]
        redirs = [(op, t if op in ("<<", "<<-") else expand(t)) for op, t in redirs]
        stdin = next((t for op, t in redirs if op in ("<<", "<<-")), None)
        to = [(op, _resolve(t, cwd)) for op, t in redirs if op in REDIRECT_TO and t not in NOT_A_FILE
              and not t.startswith("&") and not t.isdigit()]
        cmd = os.path.basename(words[0]) if words else ""
        if cmd == "cd" and len(words) == 2:
            cwd = _resolve(words[1], cwd)
            continue
        if cmd in ("echo", "printf", "true", ":") and not to:   # prints a line: nothing else
            continue
        if cmd in ("cat", "tee") or (cmd in ("echo", "printf") and to):
            args = [w for w in words[1:] if not w.startswith("-")]
            append = "-a" in words[1:] or any(op.endswith(">>") for op, _ in to)
            if cmd == "tee":
                to += [(">", _resolve(a, cwd)) for a in args]
                text = stdin
            elif cmd == "cat":
                text = stdin if not args else None
            else:
                text = " ".join(args) if cmd == "echo" else None
            if not to:
                pure = False
            for _, path in to:
                out.append((path, "changed", " ".join(words)) if text is None else (path, "append" if append else "write", text))
            continue
        if cmd == "sed" and any(w == "--in-place" or re.fullmatch(r"-[a-zA-Z]*i\S*", w) for w in words[1:]):
            rest, script, k = words[1:], None, 0
            files_ = []
            while k < len(rest):
                w = rest[k]
                if w in ("-e", "--expression", "-f"):
                    script = rest[k + 1] if k + 1 < len(rest) else None
                    k += 2
                    continue
                if w.startswith("-"):
                    k += 1
                    continue
                if script is None:
                    script = w
                else:
                    files_.append(w)
                k += 1
            for f in files_:
                out.append((_resolve(f, cwd), "changed", f"sed -i {script or ''}".strip()))
            continue
        pure = False
        if re.fullmatch(r"python[\d.]*", cmd):
            code = stdin if stdin is not None and (len(words) == 1 or words[-1] == "-") else None
            if "-c" in words[:-1]:
                code = words[words.index("-c") + 1]
            if code is not None:
                for path, pairs in python_changes(code, cwd):
                    out.append((path, "pairs", pairs) if pairs else (path, "changed", "a Python script"))
        for _, path in to:                               # git diff > x.patch, ... > log
            out.append((path, "changed", " ".join(words)[:200]))
    out = [c for c in out if "$" not in c[0] and "*" not in c[0]]   # a path still holding a variable: not known
    return out, pure and bool(out)


def _fold(node, env):
    """A Python expression's value when it is made of string constants: a str, or a list/tuple of them
    (nested); None otherwise."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return env.get(node.id)
    if isinstance(node, ast.BinOp):
        a, b = _fold(node.left, env), _fold(node.right, env)
        if isinstance(a, str) and isinstance(b, str):
            return a + b if isinstance(node.op, ast.Add) else os.path.join(a, b) if isinstance(node.op, ast.Div) else None
        return None
    if isinstance(node, (ast.List, ast.Tuple)):
        items = [_fold(e, env) for e in node.elts]
        return None if any(i is None for i in items) else tuple(items)
    if isinstance(node, ast.Call):
        f = ast.unparse(node.func)
        args = [_fold(a, env) for a in node.args]
        if args and all(isinstance(a, str) for a in args):
            if f in ("Path", "pathlib.Path", "PurePath", "os.path.join"):
                return os.path.join(*args)
            if f == "os.path.expanduser":
                return os.path.expanduser(args[0])
        if isinstance(node.func, ast.Attribute) and node.func.attr in ("expanduser", "resolve") and not node.args:
            return _fold(node.func.value, env)
    return None


WRITE_MODE = re.compile(r"[wax]")


class _Script:
    """A Python script read without running it: the files it writes, and the replacements (made of
    string constants) it made in the text it wrote to each."""

    def __init__(self, cwd: str):
        self.cwd, self.env, self.helpers = cwd, {}, {}
        self.pending: List[tuple] = []
        self.out: Dict[str, List[tuple]] = {}

    def target(self, path) -> None:
        if not isinstance(path, str):
            return
        path = _resolve(path, self.cwd)
        self.out.setdefault(path, []).extend(self.pending)
        self.pending = []

    def body(self, stmts) -> None:
        for st in stmts:
            self.stmt(st)

    def stmt(self, st) -> None:
        if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
            self.helper(st)
            return
        if isinstance(st, ast.ClassDef):
            return
        if isinstance(st, ast.For):
            self.calls(st.iter)
            pairs = _fold(st.iter, self.env)
            names = [e.id for e in st.target.elts] if isinstance(st.target, ast.Tuple) and all(
                isinstance(e, ast.Name) for e in st.target.elts) else [st.target.id] if isinstance(st.target, ast.Name) else []
            if isinstance(pairs, tuple) and names:
                for item in pairs:                          # for old, new in reps: each pair, in turn
                    item = item if len(names) > 1 else (item,)
                    if isinstance(item, tuple) and len(item) == len(names):
                        self.env.update(zip(names, item))
                        self.body(st.body)
            else:
                for n in names:
                    self.env.pop(n, None)
                self.body(st.body)
            self.body(st.orelse)
            return
        if isinstance(st, (ast.With, ast.AsyncWith)):
            for item in st.items:
                self.calls(item.context_expr)
                if isinstance(item.optional_vars, ast.Name):
                    self.env.pop(item.optional_vars.id, None)
            self.body(st.body)
            return
        if isinstance(st, (ast.If, ast.While, ast.Try)):
            self.calls(getattr(st, "test", None))
            for part in ("body", "orelse", "finalbody"):
                self.body(getattr(st, part, []))
            for h in getattr(st, "handlers", []):
                self.body(h.body)
            return
        self.calls(st)
        if isinstance(st, ast.Assign):
            value = _fold(st.value, self.env)
            for t in st.targets:
                if isinstance(t, ast.Name):
                    self.env[t.id] = value
                elif isinstance(t, ast.Tuple) and isinstance(value, tuple) and len(value) == len(t.elts):
                    for e, v in zip(t.elts, value):
                        if isinstance(e, ast.Name):
                            self.env[e.id] = v
            for t in st.targets:
                for n in ast.walk(t):
                    if isinstance(n, ast.Name) and self.env.get(n.id) is None:
                        self.env.pop(n.id, None)

    def calls(self, node) -> None:
        """The calls in `node`, innermost first: what they replace, and what they write."""
        if node is None or isinstance(node, (ast.Lambda, ast.FunctionDef)):
            return
        for child in ast.iter_child_nodes(node):
            self.calls(child)
        if not isinstance(node, ast.Call):
            return
        f, args = node.func, node.args
        if isinstance(f, ast.Attribute) and f.attr == "replace" and len(args) >= 2:
            a, b = _fold(args[0], self.env), _fold(args[1], self.env)
            if isinstance(a, str) and isinstance(b, str) and a != b:
                self.pending.append((a, b))
        elif isinstance(f, ast.Name) and f.id == "open" and args:
            mode = args[1] if len(args) > 1 else next((k.value for k in node.keywords if k.arg == "mode"), None)
            mode = _fold(mode, self.env) if mode is not None else "r"
            if isinstance(mode, str) and WRITE_MODE.search(mode):
                self.target(_fold(args[0], self.env))
        elif isinstance(f, ast.Attribute) and f.attr in ("write_text", "write_bytes"):
            self.target(_fold(f.value, self.env))
        elif ast.unparse(f) in ("shutil.copy", "shutil.copyfile", "shutil.copy2", "shutil.move", "os.rename", "os.replace") \
                and len(args) == 2:
            self.target(_fold(args[1], self.env))
        elif isinstance(f, ast.Name) and f.id in self.helpers:
            h, given = self.helpers[f.id], {}
            for i, a in enumerate(args):
                if i < len(h["params"]):
                    given[h["params"][i]] = _fold(a, self.env)
            for k in node.keywords:
                given[k.arg] = _fold(k.value, self.env)
            for old, new in h["replaces"]:
                a, b = given.get(old, self.env.get(old)), given.get(new, self.env.get(new))
                if isinstance(a, str) and isinstance(b, str) and a != b:
                    self.pending.append((a, b))
            for w in h["writes"]:
                self.target(given[w] if w in given else self.env.get(w))

    def helper(self, fn) -> None:
        """A function the script defines: which of its names it replaces with which, and writes to."""
        h = {"params": [a.arg for a in fn.args.args], "replaces": [], "writes": []}
        for n in ast.walk(fn):
            if not isinstance(n, ast.Call):
                continue
            f, args = n.func, n.args
            if isinstance(f, ast.Attribute) and f.attr == "replace" and len(args) >= 2 \
                    and all(isinstance(a, ast.Name) for a in args[:2]):
                h["replaces"].append((args[0].id, args[1].id))
            elif isinstance(f, ast.Name) and f.id == "open" and len(args) > 1 and isinstance(args[0], ast.Name) \
                    and isinstance(args[1], ast.Constant) and WRITE_MODE.search(str(args[1].value)):
                h["writes"].append(args[0].id)
        self.helpers[fn.name] = h


def python_changes(code: str, cwd: str) -> List[tuple]:
    """The files a Python script writes, each with the replacements it made in it: [(path, [(old, new)])].
    Read, not run: a replacement counts when its two strings are constants (or names, lists and helper
    functions made of them), and goes to the next file the script writes -- or, when it writes one
    file only, to that one."""
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return []
    s = _Script(cwd)
    s.body(tree.body)
    if s.pending and len(s.out) == 1:
        next(iter(s.out.values())).extend(s.pending)
    return list(s.out.items())


def _patch_files(text: str):
    """A codex apply_patch's files: [(path, "add"/"update"/"delete", hunks)], each hunk (old, new) lines."""
    out, cur, hunk = [], None, None
    for line in text.split("\n"):
        m = re.match(r"^\*\*\* (Add|Update|Delete) File: (.+)$", line)
        if m:
            cur = [m.group(2).strip(), m.group(1).lower(), []]
            out.append(cur)
            hunk = None
            continue
        if cur is None or line.startswith("*** "):
            continue
        if line.startswith("@@"):
            hunk = ([], [])
            cur[2].append(hunk)
            continue
        if hunk is None:
            hunk = ([], [])
            cur[2].append(hunk)
        if line.startswith("+"):
            hunk[1].append(line[1:])
        elif line.startswith("-"):
            hunk[0].append(line[1:])
        elif line.startswith(" ") or line == "":
            hunk[0].append(line[1:]); hunk[1].append(line[1:])
    return out


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
        self.head = {"n": n, "row_id": row_id, "at": at, "text": text[:REPLY_CHARS], "replies": []}
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
    """The session's turns ({n, row_id, at, text, replies}: what the user asked, and what the agent
    said back), and for turn `turn` (None:
    the latest) the files it worked on, in the order first touched, each
        {path, kinds (read, edit, write, hit), created,
         sources: [{via, kind, kinds, error, call, blocks}]: the calls that touched it, in order, each
         with what it did to it -- blocks of {t: "lines", start (None: not known), lines} (read),
         {t: "hits", rows: [[n, text]]}, {t: "diff", at (None: not found), old, new, above, below
         ([[n, text]]: known lines around it)}, {t: "write", lines, created}, {t: "append", lines},
         {t: "image", row_id, id} (fetched by `image`), {t: "note", text}}
    and every call it made, in order: {text, error, running, call, output, files (the paths it touched)}.
    Relative paths in shell commands are taken from `cwd` (the session's directory)."""
    conn = data._connect(gatherer)
    if conn is None:
        return {"error": f"no database for gatherer {gatherer!r}"}
    try:
        evs = list(_events(conn, channel))
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
                for path, how, n, got in found:
                    f = rec.file(path)
                    if how == "hit":
                        rec.block(f, rec.source(f, via, "hit", view, error), {"t": "hits", "rows": [[n, got[:LINE_CHARS]]]})
                    else:
                        src = rec.source(f, via, "read", view, error)
                        if how == "lines":                  # start None: where in the file is not known
                            rec.block(f, src, {"t": "lines", "start": n, "lines": got})
                        else:
                            rec.block(f, src, {"t": "note", "text": "read, but its lines can't be told apart from the rest of the output"})
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
        for p in parts:
            if p["kind"] == "call":
                order.append((cur, p))
                if p.get("id"):
                    calls[p["id"]] = p
            elif p["kind"] == "result" and p.get("id"):
                results[p["id"]] = dict(p, row_id=row_id)      # where it is stored: its image is fetched from there
            elif p["kind"] == "text" and p.get("role") == "assistant" and cur is not None and p["text"].strip():
                cur.head["replies"].append(p["text"][:REPLY_CHARS])
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
                key = "rows" if b["t"] == "hits" else "lines" if b["t"] in ("lines", "append") else None
                if key:
                    b["cut"] = max(0, len(b[key]) - room)
                    b[key] = [x[:LINE_CHARS] if isinstance(x, str) else x for x in b[key][:room]]
                    room = max(0, room - len(b[key]))
        out["files"].append({"path": path, "kinds": sorted(f["kinds"]), "created": f["created"],
                             "sources": f["sources"]})
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
