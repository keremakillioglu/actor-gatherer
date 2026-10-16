"""Run the context manager's server: JSON lines on stdin, answers on stdout.

    python -m ag.ag_harness.server [--factory module:attr] [--path DIR ...]

What every harness starts (ag/integrations/tools/ag_connection/ag_client.py, ag/integrations/tools/ag_connection/ag_client.ts). Each
gatherer is what its config in the home says (`ag.ag_harness.home`: ~/.ag,
or AG_HOME); `--factory` names a callable (gatherer) -> a manager instead,
with each `--path` on sys.path.
"""

import argparse
import io
import os
import sys

from .. import home as ag_home
from ..store import paths
from ag.ag_tools.imports import call, load_factory
from . import Server, log_line, serve


def describe(gatherer: str) -> dict:
    cfg = ag_home.home().gatherer(gatherer)
    return {"policy": cfg.policy, "pollers": cfg.pollers, "config": cfg.path, "database": paths.db_path(gatherer)}


def server_for(factory=None) -> Server:
    """The server: gatherers as the home configures them (or managers from
    `factory`)."""
    make = (lambda gatherer: call(factory, gatherer)) if factory else ag_home.manager
    return Server(make, pollers=ag_home.pollers, log=log_line, describe=describe)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ag.ag_harness.server")
    ap.add_argument("--factory", help="module:attr, (gatherer) -> a new manager (default: the gatherer's config)")
    ap.add_argument("--path", action="append", default=[], help="put on sys.path first, for --factory")
    a = ap.parse_args(argv)
    # Both directions are UTF-8, as the harness side writes and reads them,
    # whatever the locale: under a latin-1 one, stdin would otherwise turn
    # "café" into "cafÃ©", which would be stored and sent to the model.
    requests = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8")
    # stdout carries the answers alone: anything else written to fd 1 -- a
    # print in a policy or a plugin -- goes to stderr instead.
    out = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8")
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    sys.stdout = sys.stderr
    h = ag_home.home()
    h.ensure()
    for line in h.problems():                          # say what will not work, before a call does
        print(f"ag.ag_harness server: warning: {line}", file=sys.stderr, flush=True)
    print(f"ag.ag_harness server: gatherers from {h.root} (default policy {h.default_policy()})",
          file=sys.stderr, flush=True)
    factory = load_factory(a.factory, a.path) if a.factory else None
    serve(server_for(factory), requests, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
