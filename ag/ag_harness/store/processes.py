"""A process as ag records it: {"pid", "started"}, `started` the boot's id and the process's start
time in clock ticks since boot, as /proc gives them ("<boot id>:<ticks>"), so a later process given
the same pid is not taken for it. Linux only: elsewhere nothing can be told (None).

    identity(pid)            {"pid", "started"} of a running process, or None
    alive(pid, started)      whether that same process still runs: True, False, or None"""

import os
from typing import Optional

PROC = "/proc"


def _boot_id() -> Optional[str]:
    try:
        with open(os.path.join(PROC, "sys", "kernel", "random", "boot_id"), encoding="ascii") as fh:
            return fh.read().strip()
    except OSError:
        return None


def identity(pid: int) -> Optional[dict]:
    try:
        with open(os.path.join(PROC, str(int(pid)), "stat"), encoding="ascii", errors="replace") as fh:
            fields = fh.read().rsplit(")", 1)[-1].split()   # after the command, which may hold spaces and ')'
    except (OSError, ValueError):
        return None
    boot = _boot_id()
    if len(fields) < 20 or boot is None:
        return None
    return {"pid": int(pid), "started": f"{boot}:{fields[19]}"}      # field 22 of stat: starttime


def alive(pid, started) -> Optional[bool]:
    if not isinstance(pid, int) or not isinstance(started, str) or not os.path.isdir(PROC):
        return None
    now = identity(pid)
    return now is not None and now["started"] == started
