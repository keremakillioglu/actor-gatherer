"""Telling the gatherer's listeners (the dashboard) what was written: the
doorbell of ag/ag_tools/notify.py, rung in this home's `listeners/` folder."""

import os
from typing import Any, Dict, Optional

from ag.ag_tools import notify as doorbell

from . import paths


def listeners_dir() -> str:
    """Where listeners bind their sockets: beside the gatherers, in the same
    home (a test that points TRACE_DIR elsewhere gets its own)."""
    return os.path.join(os.path.dirname(paths.TRACE_DIR), doorbell.LISTENERS)


def notify(gatherer_id: str, what: str, properties: Optional[Dict[str, Any]] = None,
           row: Optional[int] = None) -> int:
    """Tell every listener that `what` of `gatherer_id` was written, after it
    committed (ag/ag_tools/notify.py). How many it reached."""
    return doorbell.notify(listeners_dir(), gatherer_id, what, properties, row)
