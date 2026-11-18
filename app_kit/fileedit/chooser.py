"""The system's own Open dialog -- Finder's on macOS, zenity's or kdialog's on Linux -- opened by the dashboard on the
machine it runs on, for the Editor: a page's own file picker never says where a file is on disk, and the Editor opens
files by their paths. And the system's file manager, showing a file the Editor cannot open where it is (`reveal`).

Only for a page on this same machine (the routes check): the dialog opens on this machine's screen, not the reader's."""

import functools
import os
import shutil
import subprocess
import sys
import threading
from typing import List, Optional

TIMEOUT = 900.0                 # seconds a dialog may stay open before it is closed unanswered
_open = threading.Lock()        # one dialog at a time

# macOS: AppleScript's own dialogs (no permission asked for them). -128: cancelled. No `activate` first: the dialog is a
# modal panel, drawn above every app's windows as it is, and macOS lets no program in the background take the keyboard
# from the app in front -- asked to, osascript waited 2 s, then showed it all the same (measured 2026-11-04: 2.32 s to
# the window with it, 0.37 s without).
APPLESCRIPT = """on run argv
  set what to item 1 of argv
  set here to POSIX file (item 2 of argv)
  try
    if what is "folder" then
      set got to choose folder with prompt "A folder to show in the Editor" default location here
    else
      set got to choose file with prompt "A file to open in the Editor" default location here
    end if
  on error number -128
    return ""
  end try
  return POSIX path of got
end run
"""


class ChooseError(ValueError):
    """Why no dialog opened: told to the page."""


class Busy(ChooseError):
    """A dialog is open already."""


@functools.lru_cache(maxsize=1)
def tool() -> Optional[str]:
    """The dialog this machine has: "osascript" (macOS), "zenity" or "kdialog" (Linux, with a display), else None."""
    if sys.platform == "darwin":
        return "osascript" if shutil.which("osascript") else None
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return None
    return next((t for t in ("zenity", "kdialog") if shutil.which(t)), None)


def name() -> Optional[str]:
    """What the page calls it: "Finder", or "the file dialog"; None, no dialog here."""
    t = tool()
    return None if t is None else "Finder" if t == "osascript" else "the file dialog"


def command(what: str, start: str, which: str) -> List[str]:
    """The command that shows `which` dialog for a file (what "file") or a folder, opened at `start` (a folder)."""
    folder = what == "folder"
    if which == "osascript":
        return ["osascript", "-", what, start]
    if which == "zenity":
        return ["zenity", "--file-selection", "--title", "A folder to show in the Editor" if folder else "A file to open in the Editor",
                *(["--directory"] if folder else []), f"--filename={start.rstrip('/')}/"]
    return ["kdialog", "--title", "Editor", "--getexistingdirectory" if folder else "--getopenfilename", start]


def choose(what: str, start: str) -> Optional[str]:
    """The path picked in the system's dialog for a file (what "file") or a folder ("folder"), opened at `start`
    (else the home folder); None if it was cancelled. Waits for it -- up to TIMEOUT -- one dialog at a time (Busy)."""
    if what not in ("file", "folder"):
        raise ChooseError('what: "file" or "folder", please')
    which = tool()
    if which is None:
        raise ChooseError("This machine has no file dialog the dashboard can open (macOS's, zenity or kdialog)")
    if not start or not os.path.isabs(start) or not os.path.isdir(start):
        start = os.path.expanduser("~")
    if not _open.acquire(blocking=False):
        raise Busy("A dialog is open already: answer it first")
    try:
        try:
            done = subprocess.run(command(what, start, which), input=APPLESCRIPT if which == "osascript" else None,
                                  capture_output=True, text=True, timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            return None
        except OSError as exc:
            raise ChooseError(f"The dialog did not open: {exc}") from None
    finally:
        _open.release()
    got = done.stdout.strip()
    if done.returncode < 0:                          # ended by a signal (the dashboard stopping, say): no answer
        return None
    if done.returncode != 0:
        if which != "osascript" and done.returncode == 1 and not done.stderr.strip():
            return None                              # zenity's and kdialog's cancel
        raise ChooseError(f"The dialog did not open: {done.stderr.strip() or f'it exited {done.returncode}'}")
    if not got:
        return None
    return got.rstrip("/") or "/"


# A file shown where it is, in the system's file manager -- Finder's window with it selected on macOS (`open -R`), its
# folder opened on Linux (xdg-open, with a display) -- for a file the Editor shows but cannot open: the reader opens it
# from there. Nothing is opened in an app here, so a file that is a program is never run.
def shower() -> Optional[str]:
    """What the page calls it: "Finder", or "the file manager"; None, none here."""
    if sys.platform == "darwin":
        return "Finder" if shutil.which("open") else None
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return None
    return "the file manager" if shutil.which("xdg-open") else None


def reveal(path: str) -> None:
    """`path` shown in the file manager (shower), at once: not waited on."""
    if shower() is None:
        raise ChooseError("This machine has no file manager the dashboard can open")
    if not os.path.isabs(path) or not os.path.exists(path):
        raise ChooseError(f"{path} does not exist")
    argv = ["open", "-R", path] if sys.platform == "darwin" else ["xdg-open", os.path.dirname(path) or "/"]
    try:
        subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except OSError as exc:
        raise ChooseError(f"It did not open: {exc}") from None
