"""Which process sent a request: the harness on the other end of a local TCP connection, as
{"pid", "started"} -- `started` the process's start (the boot's id and its start time since boot,
from /proc), so a later process given the same pid is not taken for it. Linux only (/proc); None
elsewhere, for a connection from another machine or another user's process, or when it cannot be
told.

    process_of(peer, local)     the process holding the client end of the connection from `peer`
                                (host, port) to `local` (host, port)
    identity(pid)               {"pid", "started"} of a running process, or None
    alive(process)              whether that same process still runs (None: cannot be told here)

Finding the process means finding the connection's socket in /proc/net/tcp{,6} and then the
process with that socket open among /proc/<pid>/fd: a scan, so the hook server does it once per
connection (a harness keeps its connection open across calls), not once per request."""

import ipaddress
import os
import sys
from typing import Optional, Tuple

PROC = "/proc"


def _boot_id() -> Optional[str]:
    try:
        with open(os.path.join(PROC, "sys", "kernel", "random", "boot_id"), encoding="ascii") as fh:
            return fh.read().strip()
    except OSError:
        return None


def identity(pid: int) -> Optional[dict]:
    """{"pid", "started": "<boot id>:<start time in clock ticks since boot>"} of process `pid`,
    or None if it does not run (or there is no /proc)."""
    try:
        with open(os.path.join(PROC, str(pid), "stat"), encoding="ascii", errors="replace") as fh:
            stat = fh.read()
    except OSError:
        return None
    fields = stat.rsplit(")", 1)[-1].split()     # after the command, which may hold spaces and ')'
    boot = _boot_id()
    if len(fields) < 20 or boot is None:
        return None
    return {"pid": pid, "started": f"{boot}:{fields[19]}"}      # field 22 of stat: starttime


def alive(process) -> Optional[bool]:
    """Whether `process` ({"pid", "started"}) still runs: True, False, or None when it cannot be
    told here (no /proc)."""
    if not isinstance(process, dict) or not isinstance(process.get("pid"), int):
        return None
    if not os.path.isdir(PROC):
        return None
    now = identity(process["pid"])
    return now is not None and now["started"] == process.get("started")


def _hex_address(host: str, port: int) -> Optional[str]:
    """`host:port` as /proc/net/tcp{,6} writes it: each 32-bit word of the address in hex as the
    machine stores it (127.0.0.1 is 0100007F on a little-endian one), the port in hex."""
    try:
        ip = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return None
    raw = ip.packed                              # network order; the kernel prints each word as it sits in memory
    words = [int.from_bytes(raw[i:i + 4], sys.byteorder) for i in range(0, len(raw), 4)]
    return "".join(f"{w:08X}" for w in words) + f":{port:04X}"


def _inode(peer: Tuple[str, int], local: Tuple[str, int]) -> Optional[str]:
    """The inode of the socket whose local end is `peer` and remote end `local`: the client's end."""
    want = (_hex_address(peer[0], peer[1]), _hex_address(local[0], local[1]))
    if None in want:
        return None
    for table in ("tcp", "tcp6"):
        try:
            with open(os.path.join(PROC, "net", table), encoding="ascii") as fh:
                next(fh, None)
                for line in fh:
                    parts = line.split()
                    if len(parts) > 9 and parts[1] == want[0] and parts[2] == want[1]:
                        return parts[9]
        except OSError:
            continue
    return None


def process_of(peer, local) -> Optional[dict]:
    """{"pid", "started"} of the process holding the client end of the TCP connection from `peer`
    to `local` (each (host, port, ...) as asyncio gives them), or None (module doc)."""
    try:
        peer, local = (str(peer[0]), int(peer[1])), (str(local[0]), int(local[1]))
    except (TypeError, ValueError, IndexError):
        return None
    inode = _inode(peer, local)
    if inode is None or inode == "0":
        return None
    target = f"socket:[{inode}]"
    try:
        pids = [int(n) for n in os.listdir(PROC) if n.isdigit()]
    except OSError:
        return None
    for pid in pids:
        fd_dir = os.path.join(PROC, str(pid), "fd")
        try:
            names = os.listdir(fd_dir)
        except OSError:                          # gone, or another user's
            continue
        for name in names:
            try:
                if os.readlink(os.path.join(fd_dir, name)) == target:
                    return identity(pid)
            except OSError:
                continue
    return None
