"""`python -m ag_dashboard [--home DIR] [--host H] [--port N] [--open] [--out FILE]` (or `ag`, `ag dashboard`):
the page on localhost until interrupted (Ctrl-C, SIGTERM or SIGHUP: each one stops it the same
way, removing its socket in the home's listeners/), or, with --out, written to FILE with its
data inside it. With --open (as `ag` runs it), the page is also opened in the browser -- the one
already on that port, if it is this home's dashboard."""

import argparse
import errno
import json
import os
import signal
import sys
import urllib.request
import webbrowser
from typing import List, Optional

from . import data, home, live, server


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="ag dashboard", description="Start, talk to and watch your agents in the browser.")
    ap.add_argument("--home", help="the context manager's home (default: AG_HOME, or ~/.ag)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=4200)
    ap.add_argument("--open", action=argparse.BooleanOptionalAction, default=False,
                    help="open the page in the browser (`ag` does; --no-open: not)")
    ap.add_argument("--out", help="write the page, its data inside it, to this file and stop")
    args = ap.parse_args(argv)
    if args.home:
        home.HOME = os.path.abspath(os.path.expanduser(args.home))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(server.page(data.snapshot()))
        print(f"wrote {os.path.abspath(args.out)}")
        return 0
    try:
        httpd = server.serve(args.host, args.port)
    except (OSError, ValueError) as exc:
        url = _url(args.host, args.port)
        if args.open and getattr(exc, "errno", None) == errno.EADDRINUSE and _serves_this_home(url):
            print(f"dashboard: {url}  (already running, on home {home.HOME})", file=sys.stderr)
            _open(url)
            return 0
        print(f"ag dashboard: cannot listen on {args.host}:{args.port}: {exc}", file=sys.stderr)
        return 1
    stopping = {}
    for name in ("SIGTERM", "SIGHUP"):             # a kill, a closed terminal: stopped as Ctrl-C stops it
        sig = getattr(signal, name, None)          # (Windows has no SIGHUP); before it says it is up
        if sig is not None:
            stopping[sig] = signal.signal(sig, _interrupt)
    try:                                           # a stop from here on, even mid-print, closes it
        updates = "ag's notifications" if httpd.listener and httpd.listener.ok else \
            f"a check of the files every {live.FALLBACK_SECONDS:g}s"
        print(f"dashboard: http://{args.host}:{httpd.server_port}/  (home {home.HOME}; live from {updates}; "
              f"Ctrl-C to stop)", file=sys.stderr)
        if args.open:                              # bound already: the browser's first request waits for it
            _open(_url(args.host, httpd.server_port))
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        for sig, before in stopping.items():
            signal.signal(sig, before)
    return 0


def _interrupt(signum, frame):
    raise KeyboardInterrupt


def _url(host: str, port: int) -> str:
    """The page's address for a browser on this machine: a server on every address is on localhost too."""
    if host in ("", "0.0.0.0", "::"):
        host = "127.0.0.1"
    return f"http://[{host}]:{port}/" if ":" in host else f"http://{host}:{port}/"


def _serves_this_home(url: str) -> bool:
    """Whether the server at `url` is a dashboard of this home (its /api/home says so)."""
    try:
        with urllib.request.urlopen(url + "api/home", timeout=10) as answer:
            return json.load(answer).get("home") == home.HOME
    except (OSError, ValueError, AttributeError):
        return False


def _open(url: str) -> None:
    """The page in the user's browser, where there is one to show it: on Linux only with a display, since
    without one Python's webbrowser falls back on a text browser that would take over this terminal."""
    if sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        print(f"ag dashboard: no display to open a browser on; open {url} yourself", file=sys.stderr)
        return
    try:
        if not webbrowser.open(url):
            print(f"ag dashboard: could not open a browser; open {url} yourself", file=sys.stderr)
    except webbrowser.Error as exc:
        print(f"ag dashboard: could not open a browser ({exc}); open {url} yourself", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
