"""SyncTeX, for an app whose panel shows a PDF built from TeX sources (LaTeX's preview, DocWriter): between a place in the
PDF and a line of its source, by the `synctex` command (TeX Live's), as `synctex view` and `synctex edit` answer. What
a path may be -- in the app's folder, a project's checkout -- is the app's to check; this only runs the tool and reads
what it says.

    built(pdf)                     whether the build wrote SyncTeX's data beside the PDF (-synctex=1)
    tool()                         whether `synctex` is here
    forward(pdf, src, line, column, cwd)   a source line's place in the PDF: {page, x, y, h, v, w, height} (big points
                                   from the page's top left); None: no match
    backward(pdf, page, x, y, cwd) a place in the PDF to (its source's path, absolute, line); None: no match"""
import os
import shutil
import subprocess
from typing import Dict, List, Optional, Tuple

TIMEOUT = 20                     # seconds `synctex` is given


def built(pdf: str) -> bool:
    stem = os.path.splitext(pdf)[0]
    return any(os.path.isfile(stem + ext) for ext in (".synctex.gz", ".synctex"))


def tool() -> bool:
    return shutil.which("synctex") is not None


def run(args: List[str], cwd: str) -> str:
    """`synctex` with `args`, its output; "" when it cannot run."""
    try:
        return subprocess.run(["synctex", *args], cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT,
                              stdin=subprocess.DEVNULL).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def forward(pdf: str, src: str, line: int, column: int, cwd: str) -> Optional[dict]:
    got: Dict[str, str] = {}
    for raw in run(["view", "-i", f"{line}:{column}:{src}", "-o", pdf], cwd).splitlines():
        k, _, v = raw.partition(":")
        if k in ("Page", "x", "y", "h", "v", "W", "H") and k not in got:
            got[k] = v.strip()
        if raw.startswith("SyncTeX result end"):
            break
    if "Page" not in got:
        return None
    num = lambda k: float(got[k]) if k in got else None   # noqa: E731
    return {"page": int(float(got["Page"])), "x": num("x"), "y": num("y"), "h": num("h"), "v": num("v"),
            "w": num("W"), "height": num("H")}


def backward(pdf: str, page: float, x: float, y: float, cwd: str) -> Optional[Tuple[str, int]]:
    src, line, begun = None, None, False
    for raw in run(["edit", "-o", f"{round(page)}:{x}:{y}:{pdf}"], cwd).splitlines():
        begun = begun or raw.startswith("SyncTeX result begin")
        if begun and raw.startswith("Input:") and src is None:
            src = raw[len("Input:"):].strip()
        elif begun and raw.startswith("Line:") and line is None:
            line = int(raw[len("Line:"):].strip() or 0)
    if not src or not line:
        return None
    return os.path.normpath(src if os.path.isabs(src) else os.path.join(os.path.dirname(pdf), src)), line
