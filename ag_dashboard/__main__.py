"""`python -m ag_dashboard [--home DIR] [--host H] [--port N] [--out FILE]` (or `ag dashboard`):
the page on localhost until interrupted (Ctrl-C, SIGTERM or SIGHUP: each one stops it the same
way, removing its socket in the home's listeners/), or, with --out, written to FILE with its
data inside it."""

import argparse
import os
import signal
import sys
from typing import List, Optional

from . import data, home, live, server


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="ag dashboard", description="See every agent's context over time.")
    ap.add_argument("--home", help="the context manager's home (default: AG_HOME, or ~/.ag)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=4200)
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


if __name__ == "__main__":
    sys.exit(main())
