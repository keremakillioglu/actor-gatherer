"""The CWD property: the working directory an event belongs to -- the
agent's, on what the harness sends (and so on a read); the directory a file
poller watched, on what it found. A notice about a file is for a read in
the same directory: a relative path means another file elsewhere. Declared,
optional, by the standard types and by the types a file poller outputs.

    CWD_PROPERTY           what a type declares
    same_place(a, b)       whether two events or reads are in one directory
                           (either without one: yes)
"""

import os
from typing import Any

from ag.ag_interface import Property

CWD = "cwd"
CWD_PROPERTY = Property(CWD)


def cwd_of(x) -> Any:
    """The working directory of a Read, a Row, or properties; None: none."""
    properties = x if x is None or isinstance(x, dict) else x.properties
    return (properties or {}).get(CWD)


def same_place(a, b) -> bool:
    """Whether `a` and `b` (Reads, Rows, or properties) are in the same
    directory; True when either has none."""
    x, y = cwd_of(a), cwd_of(b)
    if not x or not y:
        return True
    return os.path.normpath(str(x)) == os.path.normpath(str(y))
