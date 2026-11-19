"""File-change notices and messages from a stream: the two event types pollers bring in from outside the
conversation (events.py), and when the agent hears of them. Both are shown only in the VERBATIM part of the context
(from the running task on; the whole history before a build), each at its row's place:

  * `context_stream` events are shown as a developer message (`message`) at
    their row's place. Pollers run at read time, so a message's row is where
    the model first saw it, and each read's context extends the last one.
    Never between a tool call and its output, though: one whose row falls
    there (the output stored again later) goes right after it (`interleave_messages`).
  * `environment_update` events whose SUBJECT one of the agent's own tool
    calls in the verbatim part opened before them (by that path: `is_file_mentioned`)
    get a developer message (`notice`) at their row's place; what the model
    did about it follows, so it is never repeated as news. An update to
    something no tool call named, one the agent made itself (a tool call
    that came in with it could have WRITTEN the subject, `is_file_written`), or a
    second one before the agent opened the subject again since its notice,
    is not shown: better a notice too few than one too many.

The events themselves never reach the model, and neither kind is history for
the build."""

import os
import re
from datetime import datetime, timezone
from typing import Dict, List, Tuple

from ag.ag_interface import event_text
from ag.ag_interface.policy import TypeIds
from ag.ag_policies.tools import history
from ag.ag_policies.tools.cwd import cwd_of, same_place
from ..db import tables
from ..events import CONTEXT_STREAM, ENVIRONMENT_UPDATE
from ag.ag_policies.tools.groups import TOOL_CALL
from .parallel_sessions import ParallelSessions

# A tool call that could have WRITTEN a file it names. Reading one (cat, head, grep, wc, awk, a script
# that only opens it for reading) does not make a change to it the agent's own: in parallel work the
# change is usually someone else's, landing right after the agent looked (the agent's read is often
# what it was waiting on). Missing such a change costs a wrong answer; a needless notice after the
# agent's own write costs one re-read -- so anything unclear counts as not a write.
WRITE = re.compile(
    r">>?|\btee\b|\bsed\b[^|;&]*\s-i|\bperl\b[^|;&]*\s-[a-z]*i|\b(?:mv|cp|rm|truncate|touch|install|dd)\b"
    r"|apply_patch|\*\*\* (?:Update|Add|Delete) File"
    r"|open\([^)]*,\s*\\?['\"](?:w|a|x|r\+)"
    r"|\.write\(|writelines|write_text\(|to_csv\(|\.dump\(|shutil\.(?:copy|move)")
# `>` alone also matches 2>/dev/null or `x > 5` in a script: a redirect only counts when the file follows it.

# A harness's own file-editing tool (Claude Code's Edit, Write, MultiEdit, NotebookEdit; pi's and
# opencode's edit, write), as a tool call's text shows it: `Name({...})`. It writes the file its path
# argument names, and only that one.
EDIT_TOOL = re.compile(r"(?:Edit|Write|MultiEdit|NotebookEdit|edit|write|multiedit)\(")
EDIT_PATH = re.compile(r'"(?:file_path|notebook_path|filePath|path)"\s*:\s*"((?:[^"\\]|\\.)*)"')


def is_file_written(call_text: str, subject: str, cwd=None) -> bool:
    """Whether a tool call that names `subject` could have written it: a harness's editing tool
    whose path is the subject (`EDIT_TOOL`), a redirect INTO it, an in-place editor, a move/copy/
    remove, an apply_patch, or a script that opens something for writing. Unclear means no."""
    if EDIT_TOOL.match(call_text):
        return any(is_file_mentioned(path, subject, cwd) for path in EDIT_PATH.findall(call_text))
    for match in WRITE.finditer(call_text):
        if match.group(0).startswith(">"):                      # a redirect: only into the subject itself
            if re.match(r">>?\s*['\"\\]*[^\s'\"\\]*" + re.escape(subject), call_text[match.start():]):
                return True
            continue
        return True
    return False


CD = re.compile(r"(?<![\w\-])cd\s+\\?['\"]?([^\s;&|'\"\\]+)")


def has_changed_directory(command_so_far: str, cwd) -> bool:
    """Whether a command, up to here (`command_so_far`), changed to a directory other than `cwd`: its last
    `cd` goes anywhere else (a relative one too, but `.`)."""
    cds = list(CD.finditer(command_so_far))
    if not cds:
        return False
    target = os.path.expanduser(cds[-1].group(1))
    return os.path.normpath(target) != "." and os.path.normpath(target) != os.path.normpath(str(cwd))


PATH_CHAR = r"[\w.\-/~+@%]"                        # what a path is made of, for where one starts


def is_file_mentioned(text: str, subject: str, cwd=None) -> bool:
    """Whether `text` refers to `subject`: it appears as a whole -- not
    inside another name (`a.py` is not in `data.py` or `a.pyc`) -- and
    the path it ends is that file. Without `cwd`, a longer path ending in
    it counts too (`/w/notes.txt` mentions `notes.txt`). With it, only the
    subject itself (`./a.py` too) or the absolute path `cwd`/subject, and
    the subject itself not after a `cd` elsewhere (`cd /x && cat a.py`)."""
    for match in re.finditer(r"(?<![\w.\-])" + re.escape(subject) + r"(?![\w\-])(?!\.\w)", text):
        start = match.start()
        while start and re.match(PATH_CHAR, text[start - 1]):
            start -= 1
        path = os.path.expanduser(text[start:match.end()])
        if not cwd:
            return True
        if os.path.isabs(path):
            if os.path.normpath(path) == os.path.normpath(os.path.join(str(cwd), subject)):
                return True
        elif os.path.normpath(path) == os.path.normpath(subject) and not has_changed_directory(text[:start], cwd):
            return True
    return False


def format_time(timestamp) -> str:
    """A timestamp as it is shown: seconds since the epoch become a UTC date
    and time; anything else is shown as it is."""
    if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool) and timestamp > 10 ** 9:
        return datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return str(timestamp)


class ExternalEvents(ParallelSessions):

    def make_stream_messages(self, conn, types: TypeIds, channel_id, verbatim_start: int) -> List[tuple]:
        """("made", row_id, item, (made_id, tokens)) for each stream message
        of the verbatim part: a developer message worded by the config,
        stored as a made item so the read log shows what was sent; keyed by
        the event's row id so it sorts into its place in the history."""
        out = []
        for row in self.get_visible_events(conn, types, channel_id, verbatim_start, CONTEXT_STREAM):
            payload = row.payload if isinstance(row.payload, dict) else {}
            text = self.config.message.format(stream=payload.get("stream", ""), author=payload.get("author", ""),
                                              text=payload.get("text", ""), timestamp=format_time(payload.get("timestamp")))
            made_id, item, tokens = tables.make_message(conn, self.format, self.tokenizer, channel_id, text, CONTEXT_STREAM, f"message {row.row_id}")
            out.append(("made", row.row_id, item, (made_id, tokens)))
        return out

    def make_file_change_notices(self, conn, types: TypeIds, channel_id, verbatim_start: int, verbatim,
                read_properties=None) -> List[tuple]:
        """("made", row_id, item, (made_id, tokens)): one notice per poll, for
        the environment updates of the verbatim part -- in the read's working
        directory (`cwd`), when both have one -- that the agent should hear
        of. Better one notice too few than one too many, so an update counts
        only when:

          - a tool call of the agent's own before it, in the verbatim part,
            names the subject (`is_file_mentioned`: the file itself, by its path
            under `cwd` when absolute) -- what a message or a tool's output
            says does not count;
          - for a subject already notified there, a tool call names it again
            after that notice: the agent read it since, so there is a newer
            read to be out of date (without one, the notice it has stands);
          - it is not the agent's own doing: no tool call that came in with
            it (`history.batch_start`: what the agent ran since its previous
            model call, while the change happened) names the subject and
            could have written it (`is_own_change`) -- nor one that came in with
            the first request after the change's own time (`history.batch_at`),
            for a change reported late: a poller for a directory the agent
            comes back to reports what changed there since it last looked.

        It names them (up to `notice_names`), or counts them. Keyed by the
        first update's row id, so it sorts into its place in the history.
        On the read after the poll, it is the newest thing in the context; on
        later ones it is history, and whatever the model did about it (read
        the file again) comes after it. Each is a made item."""
        updates = self.get_visible_events(conn, types, channel_id, verbatim_start, ENVIRONMENT_UPDATE)
        if not updates:
            return []
        texts = [(row.row_id, row.type.id, event_text(row)) for row in verbatim]
        calls = types.of(TOOL_CALL)
        noticed: Dict[str, Tuple[int, int]] = {}              # subject -> (its last notice's update row, batch start)
        polls: Dict[int, dict] = {}                          # batch start -> {subject: (row id, subject, payload, repeat)}
        for update in updates:
            payload = update.payload if isinstance(update.payload, dict) else {}
            subject = payload.get("subject")
            if not isinstance(subject, str) or not subject or not same_place(update, read_properties):
                continue                                     # another directory's file of that name
            cwd = cwd_of(update) or cwd_of(read_properties)
            start = history.batch_start(conn, channel_id, update.row_id)
            previous_notice = noticed.get(subject)
            if previous_notice is not None and previous_notice[1] == start:    # changed again in the same poll: its latest
                polls[start][subject] = (update.row_id, subject, payload, polls[start][subject][3])
                noticed[subject] = (update.row_id, start)
                continue
            after = previous_notice[0] if previous_notice else 0
            if not any(after < row < update.row_id and type_id in calls and is_file_mentioned(text, subject, cwd)
                       for row, type_id, text in texts):
                continue                                     # not seen, or not again since its notice
            if self.is_own_change(texts, types, start, update.row_id, subject, cwd):
                continue                                     # the agent's own doing
            stamp = payload.get("timestamp")
            if isinstance(stamp, (int, float)) and not isinstance(stamp, bool) and stamp > 10 ** 9:
                after, through = history.batch_at(conn, channel_id, stamp, update.row_id)
                if self.is_own_change(texts, types, after, through + 1, subject, cwd):
                    continue                                 # its own, made then, reported late
            polls.setdefault(start, {})[subject] = (update.row_id, subject, payload, previous_notice is not None)
            noticed[subject] = (update.row_id, start)
        out = []
        for by_subject in polls.values():
            subject_updates = sorted(by_subject.values(), key=lambda update: update[0])
            config = self.config
            if len(subject_updates) == 1:
                row, subject, payload, repeat = subject_updates[0]
                text = config.notice.format(**self.get_notice_values(subject, payload, repeat))
            elif len(subject_updates) <= config.notice_names:
                text = config.notice_named.format(subjects=", ".join(update[1] for update in subject_updates))
            else:
                text = config.notice_counted.format(count=len(subject_updates))
            rows = [update[0] for update in subject_updates]
            made_id, item, tokens = tables.make_message(conn, self.format, self.tokenizer, channel_id, text, ENVIRONMENT_UPDATE,
                                              "update " + ",".join(map(str, rows)))
            out.append(("made", rows[0], item, (made_id, tokens)))
        return out

    def get_notice_values(self, subject: str, payload: dict, repeat: bool) -> dict:
        """What a one-file notice is worded from (`notice`): {what}, {subject}, {timestamp}, and
        {repeat}: the config's `notice_repeat` when an earlier change to the same file was already
        notified in the verbatim part (and the agent read the file again since), else ""."""
        return {"what": payload.get("what") or f"{subject} changed", "subject": subject,
                "timestamp": format_time(payload.get("timestamp")), "repeat": self.config.notice_repeat if repeat else ""}

    def is_own_change(self, texts, types: TypeIds, start: int, row_id: int, subject: str, cwd=None) -> bool:
        """Whether the update at `row_id` is the agent's own doing: a tool CALL that came in with it
        (rows after `start`, the channel's last read before it) names the subject and could have
        written it (`is_file_written`). A call that only read the file, or an output that shows it, does not
        hide someone else's change."""
        calls = types.of(TOOL_CALL)
        return any(start < row < row_id and type_id in calls and is_file_mentioned(text, subject, cwd) and is_file_written(text, subject, cwd)
                   for row, type_id, text in texts)
