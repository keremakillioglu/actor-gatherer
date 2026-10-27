"""A gatherer's old tables copied into records, once, as a dashboard that serves the page starts -- by ag's harness
side, through ag's server (ag/integrations/tools/ag_orchestrator/migrate.py, run as a program). The dashboard reads
records alone, so a gatherer from before its hooks recorded them would otherwise show none of what those tables kept:
its recaps and names, what its calls did to files, the answers no call carried back, its failed calls, which harness
each of its sessions ran on.

Due for a gatherer whose database has the old tables (`_pending`, `_recaps`, `_names`, `_touches`: an older ag made
them; this one does not) and no `_migrated` "records" yet. Run in the background: the page is served meanwhile, and
every page rung once it is done. A failure is a line in the dashboard's log; the next start tries again."""

import os
import sqlite3
import subprocess
import sys
import threading
from typing import Callable, List, Optional

from . import data, sessions

OLD_TABLES = ("_pending", "_recaps", "_names", "_touches")
SECONDS = 600                   # the most a run may take
PROGRAM = "ag.integrations.tools.ag_orchestrator.migrate"


def due(gatherer: str) -> bool:
    """Whether the gatherer's old tables are still to be copied (module doc)."""
    conn = data._connect(gatherer)
    if conn is None:
        return False
    try:
        tables = data._tables(conn)
        if not tables & set(OLD_TABLES):
            return False
        return "_migrated" not in tables or conn.execute(
            "SELECT 1 FROM _migrated WHERE name = 'records'").fetchone() is None
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def start(ring: Callable[[Optional[str]], None]) -> Optional[threading.Thread]:
    """The copy (PROGRAM) for the gatherers due, in the background, on ag's own Python (AG_PYTHON, else the
    dashboard's); `ring(None)` once it is done. None: none due."""
    names: List[str] = [g for g in data.gatherer_names() if due(g)]
    if not names:
        return None

    def run() -> None:
        try:
            python = os.environ.get("AG_PYTHON") or sys.executable
            done = subprocess.run([python, "-m", PROGRAM, *names], env=sessions.agent_env(),
                                  capture_output=True, text=True, timeout=SECONDS, stdin=subprocess.DEVNULL)
            for line in done.stdout.splitlines():
                print(f"dashboard: old tables copied into records: {line}", file=sys.stderr, flush=True)
            if done.returncode:
                print(f"dashboard: copying old tables into records failed: {(done.stderr or '').strip()[-500:]}",
                      file=sys.stderr, flush=True)
        except Exception as exc:  # noqa: BLE001 - never in the reader's way
            print(f"dashboard: copying old tables into records failed: {exc!r}", file=sys.stderr, flush=True)
        ring(None)

    thread = threading.Thread(target=run, name="dashboard-migrate", daemon=True)
    thread.start()
    return thread
