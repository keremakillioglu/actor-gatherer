"""Which files the conversation refers to changed since the last poll, as
`environment_update` events (defined here, as the policy that takes them defines its own).

Only files the conversation names are looked at: before each poll the manager
gives the poller what the conversation's raw part says (`Poller.watch`: the
events the channels were last sent verbatim, and those since), and the poller
takes from it every path-like name of an existing file under its directory --
absolute, or relative to the directory -- and compares those files'
modification times with the moment of the last poll. Nothing else is read: a
working directory of any size (a home directory) costs what the conversation
names. A change to a file the conversation never named is not reported; a
policy has nothing to match it against anyway (proactive_context_manager
shows an update only where the verbatim history refers to its file). Left
out: files under hidden directories (`.git` and the like), `__pycache__` and
`node_modules`, and symbolic links. At most `limit` changed files a poll, so a
mass change (a checkout, a build) costs a bounded number of events.

Files are named the way the agent refers to them: relative to the directory
(`notes.txt`, `src/a.py`). That is the update's `subject`, what a policy
matches against the conversation; its `what` says what happened in words:
"File notes.txt was changed on disk".
"""

import os
import re
from typing import Iterable, List, Optional, Tuple

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


#: Path-like names in a text: with a slash, or a name with an extension.
PATH = re.compile(r"[~\w.\-/]*/[\w.\-/]+|[\w\-][\w.\-]*\.[A-Za-z0-9]{1,12}\b")
#: The most files a poller watches; names past it, in the order the conversation gives them, are not.
WATCHED = 5000


def names_in(text: Optional[str]) -> List[str]:
    """The path-like names in `text`, in order."""
    return [n for n in (m.rstrip(".") for m in PATH.findall(text or "")) if n]


def resolve(root: str, name: str) -> Optional[str]:
    """`name` as an existing file under `root` (absolute, or relative to it), relative to `root`;
    None if it is none -- or under a hidden directory, `__pycache__` or `node_modules`, or a link."""
    path = os.path.normpath(os.path.join(root, os.path.expanduser(name)))
    rel = os.path.relpath(path, root)
    if rel.startswith(os.pardir) or rel == os.curdir:
        return None                                  # not under the directory
    if any(p.startswith(".") or p in SKIP_DIRS for p in rel.split(os.sep)[:-1]):
        return None
    if os.path.islink(path) or not os.path.isfile(path):
        return None
    return rel


def mentioned_files(root: str, texts: Iterable[str], limit: int = WATCHED) -> List[str]:
    """The existing files under `root` that `texts` name -- by an absolute path, or one relative to
    `root` -- as paths relative to `root`, each once, in the order first named; at most `limit`.
    A file under a hidden directory, `__pycache__` or `node_modules`, or a symbolic link, is not one."""
    found, seen = [], set()
    if not root or not os.path.isdir(root):
        return found
    root = os.path.abspath(root)
    for text in texts:
        for name in names_in(text):
            if name in seen:
                continue
            seen.add(name)
            rel = resolve(root, name)
            if rel is not None and rel not in found:
                found.append(rel)
                if len(found) >= limit:
                    return found
    return found


def changed_files(root: str, paths: Iterable[str], since: float, limit: int = 500) -> List[Tuple[str, float]]:
    """`(path, mtime)` for each of `paths` (relative to `root`) modified after `since` (seconds since
    the epoch), oldest change first; at most `limit` of them. A file gone or unreadable is skipped."""
    found = []
    if not root or since is None:
        return found
    root = os.path.abspath(root)
    for rel in paths:
        try:
            mtime = os.stat(os.path.join(root, rel)).st_mtime
        except OSError:
            continue
        if mtime > since:
            found.append((rel, mtime))
    found.sort(key=lambda x: x[1])
    return found[:limit]


class FileChangePoller(Poller):
    """The files under `root` the conversation names (`watch`) modified since
    the last poll, as `environment_update` events; nothing on the first poll
    (there is no earlier moment), nothing before it is told what the
    conversation says, and nothing for a gatherer whose types have no
    `environment_update`.

    Named after its directory (`file_changes:<root>`), so that threads of one
    gatherer working in different directories each keep their own poll mark,
    and a change is known by its directory too (the event's `source`). Each
    event carries its id as the property `poller`, and its directory as `cwd`:
    a read in another directory has files of the same name of its own."""

    outputs = ("environment_update",)
    properties = (POLLER, CWD)

    def __init__(self, root: str, limit: int = 500, watched: int = WATCHED):
        self.root = root
        self.limit, self.most = limit, watched
        self.watched: List[str] = []
        self.name = f"file_changes:{os.path.abspath(root) if root else ''}"

    def watch(self, texts: Iterable[str]) -> None:
        self.watched = mentioned_files(self.root, texts, self.most)

    def poll(self, since: Optional[float], types: List[EventType]) -> List[Event]:
        type_id = next((t.id for t in types if t.name == ENVIRONMENT_UPDATE), None)
        if since is None or type_id is None:
            return []
        return [environment_update(type_id, path, f"File {path} was changed on disk", round(mtime, 3), source=self.name,
                                   poller=self.id or self.name, cwd=os.path.abspath(self.root))
                for path, mtime in changed_files(self.root, self.watched, since - LOOKBACK, self.limit)]
