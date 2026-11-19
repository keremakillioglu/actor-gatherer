"""A LaTeX build's problems, read from the log TeX writes (<job>.log): its errors, warnings and bad boxes, each with
the file and line it is at -- what the LaTeX editor's preview lists, and marks on the file's lines (runs.py's `problems`;
preview.js, editor.js), as Overleaf does.

    parse(data)        the log's problems, in its order: {level, file, line, message, token, log}
                       level "error", "warning" or "box"; file as the log names it (None: not known); line (None:
                       none said); token: a piece of the line to mark (an undefined macro, a label), or None; log: the
                       log's own lines for it

An error says its file and line itself when TeX is run with -file-line-error (`./chap/one.tex:3: Undefined control
sequence.`). Without it, the file is the one TeX had open: TeX writes "(" and a file's name as it opens one, and ")" as
it closes it, so the files open are followed through the log. TeX wraps the log's lines at 79 bytes
(max_print_line), cutting names in two: those lines are joined first."""

import re
from typing import List, Optional

WIDTH = 79                  # TeX's max_print_line: the log's lines are cut at this many bytes
MAX = 400                   # the most problems kept
MAX_LOG = 24                # the most lines of the log kept for one
#: A line that starts a message of its own: never the end of a line cut at WIDTH.
STARTS = re.compile(rb"^(?:! |l\.\d|LaTeX |Package |Class |Module |Overfull |Underfull |pdfTeX warning)")
#: -file-line-error's form of an error: `./main.tex:12: Undefined control sequence.`
FILE_LINE = re.compile(r"^(?P<file>(?:[A-Za-z]:)?[^\s:][^:]*?\.(?P<ext>[A-Za-z0-9]{1,8})):(?P<line>\d+): (?P<msg>.*)$")
CONTEXT = re.compile(r"^l\.(?P<line>\d+)(?: |$)")
WARNING = re.compile(r"^(?:(?:Package|Class|Module) (?P<pkg>\S+)|LaTeX(?P<font> Font)?|LaTeX3) Warning: (?P<msg>.*)$")
PDFTEX = re.compile(r"^pdfTeX warning(?: \([^)]*\))?: (?P<msg>.*)$")
BOX = re.compile(r"^(?P<kind>Over|Under)full \\(?P<box>[hv])box \((?P<why>[^)]*)\) (?P<rest>.*)$")
AT_LINE = re.compile(r" on input line (?P<line>\d+)\.?")
LINES = re.compile(r"\blines? (?P<line>\d+)")
PKG_ERROR = re.compile(r"^(?:Package|Class|Module) (?P<pkg>\S+) Error: ")
MACRO = re.compile(r"(\\(?:[A-Za-z@]+|.))\s*$")
QUOTED = re.compile(r"^(?:Reference|Citation|Label) `([^']+)'")
NAME = re.compile(r'"([^"]+)"|([^\s()\[\]{}"<>]+)')
#: The kinds of file TeX reads that a name in the log may be, when it does not start with a folder.
TEXISH = {"tex", "ltx", "sty", "cls", "clo", "cfg", "def", "fd", "aux", "toc", "lof", "lot", "bbl", "out", "nav", "snm",
          "vrb", "tikz", "pgf", "ind", "gls", "dtx", "ins", "ldf", "lua", "bib", "code", "dict", "tcx", "map", "enc"}


def _filey(name: str) -> bool:
    """Whether a name after "(" in the log is a file's: from a folder (./, ../, /, ~, C:), or with TeX's extensions."""
    if re.match(r"^(?:\.{1,2}[/\\]|/|~|[A-Za-z]:[/\\])", name):
        return True
    ext = name.rsplit(".", 1)[1].lower() if "." in name else ""
    return ext in TEXISH and not name[0].isdigit()


def _lines(data: bytes) -> List[str]:
    """The log's lines, those TeX cut at WIDTH joined again -- unless the log's lines are not cut at it (a longer
    max_print_line: more lines longer than WIDTH than lines of it; TeX's own first and last lines are longer always)."""
    raw = [ln[:-1] if ln.endswith(b"\r") else ln for ln in data.split(b"\n")]
    at = sum(1 for ln in raw if len(ln) == WIDTH)
    width = WIDTH if at and at >= sum(1 for ln in raw if len(ln) > WIDTH) else None
    out: List[bytes] = []
    cur: Optional[bytes] = None
    for ln in raw:
        if cur is not None:
            if not STARTS.match(ln):
                cur += ln
                if len(ln) == width:
                    continue
                out.append(cur)
                cur = None
                continue
            out.append(cur)
            cur = None
        if width and len(ln) == width and not ln.startswith(b"l."):
            cur = ln
        else:
            out.append(ln)
    if cur is not None:
        out.append(cur)
    return [ln.decode("utf-8", "replace") for ln in out]


def _continued(lines: List[str], k: int, name: Optional[str]) -> int:
    """The line after a message's own: its lines that start "(<name>)" (a package's, LaTeX's own) skipped."""
    if not name:
        return k
    lead = f"({name})"
    while k < len(lines) and lines[k].startswith(lead):
        k += 1
    return k


def _error(lines: List[str], i: int, first: str) -> tuple:
    """An error starting at line i (its message `first`): (where it ends, its line from TeX's `l.<n>`, its token)."""
    n, token = len(lines), None
    pkg = PKG_ERROR.match(first)
    start = _continued(lines, i + 1, pkg.group("pkg") if pkg else None)
    # The first line of TeX's context, where it was reading: an undefined macro is the last thing on it. (LaTeX's own
    # errors put an empty line and a pointer to the manual before the context.)
    shown = next((x for x in lines[start:start + 8] if x.strip() and not x.startswith(("See the ", "Type  H "))), None)
    if first.startswith("Undefined control sequence") and shown:
        m = MACRO.search(shown.rstrip())
        token = m.group(1) if m else None
    k = start
    while k < n and k - i < 40:
        ln = lines[k]
        if ln.startswith("! ") or FILE_LINE.match(ln) or WARNING.match(ln) or BOX.match(ln):
            break
        m = CONTEXT.match(ln)
        if m:
            k += 2                                       # and the context's second line, what TeX had not read yet
            while k < n and lines[k].strip() and k - i < 60:   # TeX's help, to the empty line after it
                k += 1
            return min(k, n), int(m.group("line")), token
        k += 1
    k = start                                            # no `l.<n>` (an emergency stop): to the first empty line
    while k < n and lines[k].strip() and k - i < 40:
        k += 1
    return k, None, token


def _message(msg: str, token: Optional[str]) -> str:
    msg = re.sub(r"^LaTeX Error: ", "", msg).strip()
    if token and msg.startswith("Undefined control sequence"):
        return f"Undefined control sequence {token}"
    return msg


def _problem(level: str, file: Optional[str], line: Optional[int], message: str, token: Optional[str],
             log: List[str]) -> dict:
    return {"level": level, "file": file, "line": line, "message": message, "token": token,
            "log": [ln[:300] for ln in log[:MAX_LOG]]}


def parse(data: bytes) -> List[dict]:
    """The problems a TeX log tells of, in its order (at most MAX)."""
    lines = _lines(data)
    stack: List[Optional[str]] = []                      # the files TeX has open, as it names them (None: a "(" not a file's)
    out: List[dict] = []
    top = lambda: next((f for f in reversed(stack) if f), None)   # noqa: E731
    i, n = 0, len(lines)
    while i < n and len(out) < MAX:
        ln = lines[i]
        m = FILE_LINE.match(ln)
        if m and _filey(m.group("file")):
            k, _, token = _error(lines, i, m.group("msg"))
            out.append(_problem("error", m.group("file"), int(m.group("line")), _message(m.group("msg"), token), token,
                                lines[i:k]))
            i = k
            continue
        if ln.startswith("! "):
            k, line, token = _error(lines, i, ln[2:])
            out.append(_problem("error", top(), line, _message(ln[2:], token), token, lines[i:k]))
            i = k
            continue
        m = WARNING.match(ln) or PDFTEX.match(ln)
        if m:
            name = (m.groupdict().get("pkg") or ("Font" if m.groupdict().get("font") else "LaTeX")) if m.re is WARNING else None
            k = _continued(lines, i + 1, name)
            text = " ".join([m.group("msg").strip()] + [re.sub(r"^\([^)]*\)\s*", "", x).strip() for x in lines[i + 1:k]])
            at = AT_LINE.search(text)
            line = int(at.group("line")) if at else None
            text = AT_LINE.sub("", text).strip()
            q = QUOTED.match(text)
            if m.re is WARNING and m.groupdict().get("pkg"):
                text = f"{m.group('pkg')}: {text}"
            out.append(_problem("warning", top(), line, text, q.group(1) if q else None, lines[i:k]))
            i = k
            continue
        m = BOX.match(ln)
        if m:
            at = LINES.search(m.group("rest"))
            k = i + 1
            while k < n and lines[k] != "" and k - i < 30:     # the box's contents, as TeX shows them, to an empty line
                k += 1
            out.append(_problem("box", top(), int(at.group("line")) if at else None,
                                f"{m.group('kind')}full \\{m.group('box')}box ({m.group('why')})", None, lines[i:k]))
            i = k
            continue
        _follow(ln, stack)
        i += 1
    return out


def _follow(ln: str, stack: List[Optional[str]]) -> None:
    """The files a line of the log opens, "(<name>", and closes, ")", followed on the stack."""
    j = 0
    while True:
        a, b = ln.find("(", j), ln.find(")", j)
        if a < 0 and b < 0:
            return
        if b >= 0 and (a < 0 or b < a):
            if stack:
                stack.pop()
            j = b + 1
            continue
        m = NAME.match(ln, a + 1)
        name = (m.group(1) or m.group(2)) if m else None
        stack.append(name if name and _filey(name) else None)
        j = a + 1
