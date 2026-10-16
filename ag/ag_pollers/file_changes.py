"""Which files under a directory changed since the last poll, as
`environment_update` events (defined here, as the policy that takes them defines its own).

The plain way: a walk of the directory comparing each file's modification
time with the moment of the last poll. Left out: hidden directories (`.git`
and the like), `__pycache__`, `node_modules`, and symbolic links. The walk
stops at `limit` changed files, so a mass change (a checkout, a build) costs
a bounded number of events.

Files are named the way the agent refers to them: relative to the directory
(`notes.txt`, `src/a.py`). That is the update's `subject`, what a policy
matches against the conversation; its `what` says what happened in words:
"File notes.txt was changed on disk".
"""

import os
from typing import List, Optional, Tuple

from ag.ag_interface import Event, EventType, Poller

#: The event type it outputs, by name: what a policy that takes it declares.
ENVIRONMENT_UPDATE = "environment_update"
#: The properties it sets on each event: its id, which of the gatherer's pollers
#: it is; and the directory it watched, which a file's relative path is in.
POLLER = "poller"
CWD = "cwd"


def environment_update(type_id: int, subject: str, what: str, timestamp, source: str = "",
                       poller: str = "", cwd: str = "") -> Event:
    """An environment_update event: payload {"subject", "what", "timestamp",
    "source"}; its id is the source, the subject and the timestamp; its
    `poller` and `cwd` properties the poller's id and the directory the
    subject is relative to, if given."""
    properties = {k: v for k, v in ((POLLER, poller), (CWD, cwd)) if v}
    return Event(type_id, {"subject": subject, "what": what, "timestamp": timestamp, "source": source},
                 id=f"environment_update:{source}:{subject}@{timestamp}", properties=properties,
                 text=f"{subject}: {what}" if what else subject)

SKIP_DIRS = {"__pycache__", "node_modules"}

#: How far before `since` the poller looks (seconds). A file's mtime comes from
#: the kernel's coarse clock, which can lag `time.time()` by a few milliseconds
#: (a jiffy), so a change made just after a poll can carry an mtime just before
#: its mark. Looking back a little finds it; one seen twice has the same id and
#: is stored once. Kept short: whatever was written within it before a gatherer's
#: first poll -- which reports nothing -- is reported by the second as a change.
LOOKBACK = 0.05


def changed_files(root: str, since: float, limit: int = 500) -> List[Tuple[str, float]]:
    """`(path relative to root, mtime)` for every regular file under `root`
    modified after `since` (seconds since the epoch), oldest change first;
    at most `limit` of them. An unreadable root or file is skipped, never an
    error."""
    found = []
    if not root or since is None or not os.path.isdir(root):
        return found
    root = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d not in SKIP_DIRS
                             and not os.path.islink(os.path.join(dirpath, d)))
        for name in filenames:
            path = os.path.join(dirpath, name)
            try:
                if os.path.islink(path):
                    continue
                mtime = os.stat(path).st_mtime
            except OSError:
                continue
            if mtime > since:
                found.append((os.path.relpath(path, root), mtime))
                if len(found) >= limit:
                    found.sort(key=lambda x: x[1])
                    return found
    found.sort(key=lambda x: x[1])
    return found


class FileChangePoller(Poller):
    """The files under `root` modified since the last poll, as
    `environment_update` events; nothing on the first poll (there is no
    earlier moment), and nothing for a gatherer whose types have no
    `environment_update`.

    Named after its directory (`file_changes:<root>`), so that threads of one
    gatherer working in different directories each keep their own poll mark,
    and a change is known by its directory too (the event's `source`). Each
    event carries its id as the property `poller`, and its directory as `cwd`:
    a read in another directory has files of the same name of its own."""

    outputs = ("environment_update",)
    properties = (POLLER, CWD)

    def __init__(self, root: str, limit: int = 500):
        self.root = root
        self.limit = limit
        self.name = f"file_changes:{os.path.abspath(root) if root else ''}"

    def poll(self, since: Optional[float], types: List[EventType]) -> List[Event]:
        type_id = next((t.id for t in types if t.name == ENVIRONMENT_UPDATE), None)
        if since is None or type_id is None:
            return []
        return [environment_update(type_id, path, f"File {path} was changed on disk", round(mtime, 3), source=self.name,
                                   poller=self.id or self.name, cwd=os.path.abspath(self.root))
                for path, mtime in changed_files(self.root, since - LOOKBACK, self.limit)]
