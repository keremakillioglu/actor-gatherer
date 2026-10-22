"""The proactive context manager: earlier history as sections built in the
background, aware of what happens outside the conversation and of the
requests the user makes to the session's other channels.

Three moments, composed from the policies' toolkit -- `read`, `build` (the
analysis), `check` (the boundary verdict and what follows) -- and three
additions in `assemble`. Two, one per outside type (events.py), are confined
to the VERBATIM part of the context (from the running task on; the whole
history before a build):

  * `context_stream` events are shown as a developer message (`message`) at
    their row's place. Pollers run at read time, so a message's row is where
    the model first saw it, and each read's context extends the last one.
  * `environment_update` events whose SUBJECT a verbatim row before them
    refers to get a developer message (`notice`) at their row's place; what
    the model did about it follows, so it is never repeated as news. An
    update the conversation had not referred to, or one the agent made
    itself (a tool call that came in with it could have WRITTEN the subject,
    `writes`), is not shown.

The events themselves never reach the model, and neither kind is history for
the build.

The third: each request the user made to another channel since the build in
use (since the start, before one) is a developer message (`parallel_message`)
placed just before this channel's latest user message. Requests before the
build's mark are in its index section instead. All three are made items,
remade on every read and never reused as sections.

The session's context -- the sections, the pinned rows, the running task
with all of the above among it; not the agent's preamble nor the sections'
overview -- is kept at or under max_context_tokens. Above it, on any read
(not only at a user message), a build is started -- or the running one
awaited -- and the read waits for it; adopted, it cuts the running task
after its last event when the context would not otherwise fit (`cut_for`):
the running task, condensed, is "This task so far", and only what comes
after it is verbatim. The budgets add up under the limit (the config
refuses them otherwise), every section keeps to its own, and the pinned rows
to keep_pinned_tokens, the newest kept. What still does not fit -- a step
larger than the room the build leaves -- is left out with a note naming its
rows (`stubbed`).

Everything below `assemble` is the sections' logic: segmentation, ranking,
builds and their adoption.
"""

import re
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ag.ag_interface import LLM, Format, Tokenizer
from ag.ag_policies.tools import boundary, channel, history, ranking, segmentation, summarize
from ag.ag_policies.tools import tasks as tasks_tool

from ag.ag_interface import Ref, Row, event_text, property_column
from ag.ag_interface.policy import Context, Policy, Read, TypeIds
from ag.ag_policies.tools.channel import CHANNEL, channel_of
from ag.ag_policies.tools.cwd import same_place
from ag.ag_policies.tools.options import config_from
from . import layout, tables
from .config import ProactiveContextManagerConfig, within_limit
from .events import CONTEXT_STREAM, ENVIRONMENT_UPDATE, EVENT_TYPES

PARALLEL_REQUEST = "parallel_request"
CURRENT_REQUEST = "Current request"   # the running task a `limit` build starts at the last user message
LEFT_OUT = "left_out"           # a step stubbed to keep the context within max_context_tokens
AGENT_STEP = ("agent_message", "tool_call", "agent_reasoning")   # what an agent step may start with

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


def writes(call_text: str, subject: str) -> bool:
    """Whether a tool call that names `subject` could have written it: a redirect INTO it, an
    in-place editor, a move/copy/remove, an apply_patch, or a script that opens something for
    writing. Unclear means no."""
    for m in WRITE.finditer(call_text):
        if m.group(0).startswith(">"):                      # a redirect: only into the subject itself
            if re.match(r">>?\s*['\"\\]*[^\s'\"\\]*" + re.escape(subject), call_text[m.start():]):
                return True
            continue
        return True
    return False


def shown(timestamp) -> str:
    """A timestamp as it is shown: seconds since the epoch become a UTC date
    and time; anything else is shown as it is."""
    if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool) and timestamp > 10 ** 9:
        return datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return str(timestamp)


def cleaned_of(tasks, turns) -> dict:
    """{events row_id: cleaned text} for the user messages the summaries of `tasks` cleaned -- each
    entry's turn mapped to its user message's row -- taken out of the tasks' retention (they are
    kept in their own table, not with the task's rules)."""
    by_index = {t.index: t for t in turns}
    out = {}
    for task in tasks:
        for c in (task.retention or {}).pop(summarize.CLEANED, None) or []:
            turn = by_index.get(c.get("turn"))
            if turn is not None and task.start_turn <= turn.index <= task.end_turn and c.get("text", "").strip():
                out[turn.first_row] = c["text"]
    return out


def with_cleaned(conn, entries) -> None:
    """Show each user message in `entries` as its cleaned text, where it has one (in place). Its
    row id -- the [id N] the context names it by -- is the original message's."""
    texts = tables.cleaned_texts(conn, [e.row_id for e in entries])
    for e in entries:
        if e.row_id in texts:
            e.text = texts[e.row_id]


def mentions(text: str, subject: str) -> bool:
    """Whether `text` refers to `subject`: it appears as a whole -- not
    inside another name (`a.py` is not in `data.py` or `a.pyc`), while a
    longer path ending in it counts (`/w/notes.txt` mentions `notes.txt`)."""
    return re.search(r"(?<![\w.\-])" + re.escape(subject) + r"(?![\w\-])(?!\.\w)", text) is not None


class ProactiveContextManager(Policy):
    name = "proactive_context_manager"
    event_types = EVENT_TYPES           # events.py

    def __init__(self, format: Format, llm: LLM, config: Optional[ProactiveContextManagerConfig] = None,
                 tokenizer: Optional[Tokenizer] = None, gatherers=None, jobs=None, log=None,
                 options: Optional[dict] = None):
        self.tokenizer = tokenizer                  # None: the manager's
        self.gatherers, self.jobs = gatherers, jobs         # Gatherers, Jobs (ag.ag_interface.store); jobs None: no background work
        if log is not None:
            self.log = log
        self.format = format
        self.llm = llm
        self.config = config or config_from(ProactiveContextManagerConfig, options, llm)
        # a max_context_tokens of the gatherer's own (or a whole config) wins over a harness's limit
        self.max_given = config is not None or "max_context_tokens" in (options or {})
        self._limited: Dict[int, ProactiveContextManagerConfig] = {}

    @property
    def groups(self):
        return self.config.groups

    # ------------------------------------------------------------ storage

    def init(self, conn) -> None:
        """`tasks`, `_builds` and `_boundaries` (tables.py), if absent."""
        tables.create(conn)

    def failed(self, gatherer_id: str, properties, job: str, job_id: int, error: str) -> None:
        """What a job of this policy leaves behind when it raised in the
        worker: a build is settled `failed`, a check's verdict is "no"."""
        channel_id = channel_of(properties)
        conn = self.gatherers.open(gatherer_id)
        try:
            if job == "build":
                tables.fail_build(conn, job_id, error)
            elif job == "check":
                tables.record_boundary(conn, job_id, False, f"check failed: {error}", channel_id)
        finally:
            conn.close()

    # ------------------------------------------------------------ read time

    @contextmanager
    def within(self, limit: Optional[int]):
        """`self.config` as a harness's own limit makes it (`config.within_limit`), while in
        the block: one read, or one build. Not when the gatherer sets max_context_tokens, or
        none is stated. (The server answers one request at a time, the worker runs one job.)"""
        saved = self.config
        if limit and not self.max_given:
            if limit not in self._limited:
                try:
                    self._limited[limit] = within_limit(saved, limit)
                except ValueError as exc:
                    self.log(f"the harness's limit {limit} leaves too little for the budgets ({exc}); "
                             f"max_context_tokens={saved.max_context_tokens} kept")
                    self._limited[limit] = saved
            self.config = self._limited[limit]
        try:
            yield
        finally:
            self.config = saved

    def read(self, conn, read: Read) -> Context:
        """The context for the channel's next model call: the sectioned
        context, with the stream messages of the verbatim part shown where
        they arrived, and a notice for every environment update the
        verbatim part refers to. Within the harness's own limit, when the
        call states one (`within`)."""
        with self.within(read.limit):
            return self.read_within(conn, read)

    def read_within(self, conn, read: Read) -> Context:
        cfg, ch = self.config, channel_of(read)
        types = TypeIds.load(conn)
        rows = history.rows(conn, types, self.groups, ch)
        if not rows:
            return Context()
        at_user = history.opens_turn(rows[-1], types, self.groups)
        latest = tables.build_for(conn, ch)
        last = conn.last_read(channel.of(ch))
        build, made = self.choose(conn, types, rows, latest, last, at_user, read)
        items, refs, size = self.assemble(conn, rows, build, made, types, read)
        over = size > cfg.max_context_tokens or self.measured_over(last, build, ch)
        if over and not at_user and tables.waiting(latest, last):        # a ready build: taken now, not at the user
            build, made = self.choose(conn, types, rows, latest, last, True, read)
            items, refs, size = self.assemble(conn, rows, build, made, types, read)
            over = size > cfg.max_context_tokens or self.measured_over(last, build, ch)
        if at_user or over:
            latest = tables.build_for(conn, ch)
            started = self.start_due(conn, types, read, rows, latest, build, size, over)
            # over the limit, the read waits for its build however long it takes (up to build_timeout)
            seconds = cfg.build_timeout if over and started == "build" else cfg.sync_seconds
            if started and seconds > 0 and self.wait(conn, ch, rows[-1].row_id, started, seconds):
                latest = tables.build_for(conn, ch)
                build, made = self.choose(conn, types, rows, latest, last, True, read)
                items, refs, size = self.assemble(conn, rows, build, made, types, read)
        if size > cfg.max_context_tokens:                # still over: the steps that do not fit, left out
            items, refs, size = self.assemble(conn, rows, build, made, types, read, stub=True)
        if size > cfg.max_context_tokens:
            self.log(f"[{ch}] context {size} tokens, over max_context_tokens={cfg.max_context_tokens}")
        self.last_tokens = size                     # the session's context the read returned, as max bounds it
        return Context(items, refs, str(build["build_id"]) if build else None, tokens=size)

    def measured_over(self, last: Optional[dict], build: Optional[dict], ch) -> bool:
        """Whether the provider's count of the last call's context (`real_tokens`, reported
        after the call) was over max_context_tokens, and that context is the one this read
        extends: the last read was made from the same build (or, like this one, from none).
        After a build its first call has not been counted yet, so a count from before it
        does not ask for another."""
        if not last or not last.get("real_tokens"):
            return False
        if last.get("basis") != (str(build["build_id"]) if build else None):
            return False
        if last["real_tokens"] <= self.config.max_context_tokens:
            return False
        self.log(f"[{ch}] the last call's context was {last['real_tokens']} tokens by the provider's count "
                 f"(ag counted {last.get('est_tokens')}), over max_context_tokens={self.config.max_context_tokens}")
        return True

    def assemble(self, conn, rows, build: Optional[dict], made: List[int], types: TypeIds,
                 read: Read, stub: bool = False) -> Tuple[list, list, int]:
        """(items, refs, tokens): the sectioned context -- preamble, the
        section items, the pinned rows of the condensed span (the newest that
        fit keep_pinned_tokens), the running task verbatim (or the whole
        history before a build; after a build that cut the running task,
        only what came after it) -- with every stream message of the
        verbatim part shown in that last, verbatim run, at its row's place,
        and a notice at the place of each environment update of the verbatim
        part whose subject the rows before it refer to. Messages and notices
        are made items; the events are never returned. Then the requests made
        to the other channels (`parallel_requests`), right before this
        channel's latest user message.

        `tokens` is the session's context, what max_context_tokens bounds:
        all of it but the preamble and the sections' fixed overview. With
        `stub`, over the limit, agent steps of the verbatim part are replaced
        by notes naming their rows (`stubbed`): the read's last resort, once
        it has built what it could."""
        cfg = self.config
        preamble, body = history.arrange(rows, types, self.groups)
        if build is None:
            cut = 0
            pinned, tail = [], body
            made_items = {}
        else:
            cut = build["open_from_row"]
            pinned_ids = types.of(*self.groups.pinned)
            pinned = self.newest_within([r for r in body if r.row_id < cut and r.type.id in pinned_ids],
                                        cfg.keep_pinned_tokens)
            tail = [r for r in body if r.row_id >= cut]
            made_items = conn.made_items(made)
        items = ([r.payload for r in preamble] + [made_items[m][1] for m in made] + [r.payload for r in pinned])
        refs = ([Ref(row_id=r.row_id) for r in preamble] + [Ref(made_id=m) for m in made]
                + [Ref(row_id=r.row_id) for r in pinned])
        fixed = self.tokenizer.count(layout.overview(cfg, conn.path)) if made else 0
        tokens = sum(r.tokens for r in pinned) + sum(made_items[m][2] for m in made) - fixed
        made_here = (self.shown_messages(conn, types, channel_of(read), cut)
                     + self.notices(conn, types, channel_of(read), cut, preamble + pinned + tail, read.properties))
        entries = list(self.interleave(tail, made_here, types))
        shown = self.parallel_requests(conn, types, channel_of(read), build["parallel_mark"] if build else 0)
        tokens += sum(cost[1] if kind == "made" else cost for kind, _, _, cost in entries) + sum(c for _, _, c in shown)
        if stub and tokens > cfg.max_context_tokens:
            entries, tokens = self.stubbed(conn, entries, tokens, types, read)
        for kind, row_id, item, cost in entries:
            items.append(item)
            refs.append(Ref(row_id=row_id) if kind == "row" else Ref(made_id=cost[0]))
        if shown:
            at = self.latest_request(refs, rows, types, channel_of(read))
            for made_id, item, cost in reversed(shown):
                items.insert(at, item)
                refs.insert(at, Ref(made_id=made_id))
        return items, refs, tokens

    @staticmethod
    def newest_within(rows: list, budget: int) -> list:
        """The newest of `rows` whose tokens add up to at most `budget`, in order."""
        kept, used = [], 0
        for r in reversed(rows):
            if used + r.tokens > budget:
                break
            kept.append(r)
            used += r.tokens
        return kept[::-1]

    def step_starts(self, rows) -> List[int]:
        """The rows an agent step starts at: an agent event right after a tool output (the context
        events between them aside) -- where a cut keeps every tool call with its output and every
        model reply whole."""
        out, previous = [], None
        for r in rows:
            name = r.type.name
            if name == "context":
                continue
            if name in AGENT_STEP and previous == "tool_output":
                out.append(r.row_id)
            previous = name
        return out

    def stubbed(self, conn, entries: list, tokens: int, types: TypeIds, read: Read) -> Tuple[list, int]:
        """`entries` brought within max_context_tokens, as far as replacing agent steps of the verbatim
        part by notes naming their rows gets there: first each step far larger than its note, largest
        first (a huge tool output); then, if still over, the oldest steps together, by one note,
        until it fits -- the newest step is kept. A step's tool calls go with their outputs, so what
        remains is still a valid conversation; user messages are never replaced."""
        cfg = self.config
        by_row = {r.row_id: r for r in history.rows(conn, types, self.groups, channel_of(read))}
        rows = [(i, rid) for i, (kind, rid, _, _) in enumerate(entries) if kind == "row" and rid in by_row]
        starts = set(self.step_starts([by_row[rid] for _, rid in rows]))
        steps, current = [], None
        for i, rid in rows:
            if history.opens_turn(by_row[rid], types, self.groups):
                current = None
                continue
            if rid in starts or current is None:
                current = []
                steps.append(current)
            current.append(i)
        cost = lambda i: entries[i][3][1] if entries[i][0] == "made" else entries[i][3]
        replaced: Dict[int, Optional[tuple]] = {}

        def stub(indices: List[int]) -> int:
            """Replace the entries at `indices` (consecutive steps) by one note; the tokens it saves."""
            first, last = entries[indices[0]][1], entries[indices[-1]][1]
            size = sum(cost(i) for i in indices)
            calls = [str(event_text(by_row[entries[i][1]]) or "")[:60] for i in indices
                     if entries[i][0] == "row" and by_row[entries[i][1]].type.name == "tool_call"]
            text = (f"[Agent steps were left out here to keep the context within max_context_tokens: "
                    f"{len(indices)} events, {size} tokens"
                    + (f"; their calls: {'; '.join(calls[:3])}{' ...' if len(calls) > 3 else ''}" if calls else "")
                    + f". Read event rows {first}-{last} from the context database, {conn.path}, if you need them.]")
            item = self.format.make_section(text, LEFT_OUT)
            made_id = conn.make_item(item, self.tokenizer, properties=channel.of(channel_of(read)), name=LEFT_OUT,
                                     source=f"rows {first}-{last}")
            note = conn.made_items([made_id])[made_id][2]
            replaced[indices[0]] = ("made", first, item, (made_id, note))
            for i in indices[1:]:
                replaced[i] = None
            return size - note

        note_size = 4 * self.tokenizer.count(f"[Agent steps were left out here ... {conn.path} ...]")
        for step in sorted(steps, key=lambda st: -sum(cost(i) for i in st)):
            if tokens <= cfg.max_context_tokens or sum(cost(i) for i in step) < 5 * note_size:
                break                                    # a note per step only for a step far larger than it
            tokens -= stub(step)
        left = [st for st in steps if st[0] not in replaced]
        if tokens > cfg.max_context_tokens and len(left) > 1:
            run, saved = [], 0
            for st in left[:-1]:                         # the oldest first; the newest step stays
                run.append(st)
                saved = sum(cost(i) for s_ in run for i in s_) - note_size // 4
                if tokens - saved <= cfg.max_context_tokens:
                    break
            run_indices = [i for s_ in run for i in s_]
            if all(b == a + 1 or replaced.get(a + 1, 0) is None for a, b in zip(run_indices, run_indices[1:])):
                tokens -= stub(run_indices)
        return [replaced.get(i, e) for i, e in enumerate(entries) if replaced.get(i, e) is not None], tokens

    def latest_request(self, refs: list, rows, types: TypeIds, channel_id) -> int:
        """The position in the context of this channel's latest user message
        (the end, if it has none)."""
        own = [r.row_id for r in rows if channel_of(r) == channel_id and history.opens_turn(r, types, self.groups)]
        if not own:
            return len(refs)
        return next((i for i, ref in enumerate(refs) if ref.row_id == own[-1]), len(refs))

    def parallel_requests(self, conn, types: TypeIds, channel_id, after_row: int) -> List[tuple]:
        """(made_id, item, tokens) for each user message stored in another
        channel after `after_row`, oldest first."""
        out = []
        for r in conn.rows(after_row, types.of(*self.groups.user), differ=channel.of(channel_id)):
            other = channel_of(r)
            if other is None or other == channel_id:
                continue
            text = self.config.parallel_message.format(text=event_text(r) or "", channel=other, db_path=conn.path,
                                                       channel_column=property_column(CHANNEL))
            item = self.format.make_section(text, PARALLEL_REQUEST)
            made_id = conn.make_item(item, self.tokenizer, properties=channel.of(channel_id), name=PARALLEL_REQUEST,
                                     source=f"request {r.row_id}")
            out.append((made_id, item, conn.made_items([made_id])[made_id][2]))
        return out

    def interleave(self, tail, made_here: List[tuple], types: TypeIds) -> List[tuple]:
        """The tail's rows, as ("row", row_id, payload, tokens), and the
        messages and notices made for outside events, together in row
        order: each where its event was stored, which -- the pollers being
        asked at read time -- is where the model first saw it."""
        entries = [("row", r.row_id, r.payload, r.tokens) for r in tail] + list(made_here)
        return sorted(entries, key=lambda e: e[1])

    def outside(self, conn, types: TypeIds, channel_id, cut: int, name: str) -> list:
        """The events of type `name` the channel can see from `cut` on -- the
        verbatim part of the context; those a build has condensed past are
        not looked at -- in row order."""
        return conn.rows(after_row=max(cut - 1, 0), match=channel.of(channel_id), type_ids=types.of(name))

    def shown_messages(self, conn, types: TypeIds, channel_id, cut: int) -> List[tuple]:
        """("made", row_id, item, (made_id, tokens)) for each stream message
        of the verbatim part: a developer message worded by the config,
        stored as a made item so the read log shows what was sent; keyed by
        the event's row id so it sorts into its place in the history."""
        out = []
        for r in self.outside(conn, types, channel_id, cut, CONTEXT_STREAM):
            payload = r.payload if isinstance(r.payload, dict) else {}
            text = self.config.message.format(stream=payload.get("stream", ""), author=payload.get("author", ""),
                                              text=payload.get("text", ""), timestamp=shown(payload.get("timestamp")))
            item = self.format.make_section(text, "context_stream")
            made_id = conn.make_item(item, self.tokenizer, properties=channel.of(channel_id),
                                      name="context_stream", source=f"message {r.row_id}")
            out.append(("made", r.row_id, item, (made_id, conn.made_items([made_id])[made_id][2])))
        return out

    def notices(self, conn, types: TypeIds, channel_id, cut: int, verbatim,
                read_properties=None) -> List[tuple]:
        """("made", row_id, item, (made_id, tokens)): one notice per poll, for
        the environment updates of the verbatim part -- in the read's working
        directory (`cwd`), when both have one -- it found whose subject
        a verbatim row before them refers to -- the model had seen the
        subject, then it changed -- and that are not the agent's own doing:
        no tool call or output that came in with them
        (`history.batch_start`: what the agent ran since its previous model
        call, while the change happened) names the subject. It names them
        (up to `notice_names`), or counts them. Keyed by the first update's
        row id, so it sorts into its place in the history: where the model
        first saw it. On the read after the poll, it is the newest thing in
        the context; on later ones it is history, and whatever the model did
        about it (read the file again) comes after it. Each is a made item."""
        updates = self.outside(conn, types, channel_id, cut, ENVIRONMENT_UPDATE)
        if not updates:
            return []
        texts = [(v.row_id, v.type.id, event_text(v)) for v in verbatim]
        first: Dict[str, Optional[int]] = {}                 # subject -> the first row that refers to it
        polls: Dict[int, dict] = {}                          # batch start -> {subject: (row id, subject, payload)}
        for r in updates:
            payload = r.payload if isinstance(r.payload, dict) else {}
            subject = payload.get("subject")
            if not isinstance(subject, str) or not subject or not same_place(r, read_properties):
                continue                                     # another directory's file of that name
            if subject not in first:
                first[subject] = min((row for row, _, text in texts if mentions(text, subject)), default=None)
            if first[subject] is None or first[subject] > r.row_id:
                continue
            start = history.batch_start(conn, channel_id, r.row_id)
            if self.own_change(texts, types, start, r.row_id, subject):
                continue                                     # the agent's own doing
            polls.setdefault(start, {})[subject] = (r.row_id, subject, payload)   # a subject once: its latest
        out = []
        for by_subject in polls.values():
            found = sorted(by_subject.values(), key=lambda f: f[0])
            cfg = self.config
            if len(found) == 1:
                row, subject, payload = found[0]
                text = cfg.notice.format(**self.notice_fields(conn, texts, types, channel_id, row, subject, payload))
            elif len(found) <= cfg.notice_names:
                text = cfg.notice_named.format(subjects=", ".join(subject for _, subject, _ in found))
            else:
                text = cfg.notice_counted.format(count=len(found))
            item = self.format.make_section(text, "environment_update")
            rows = [row for row, _, _ in found]
            made_id = conn.make_item(item, self.tokenizer, properties=channel.of(channel_id), name="environment_update",
                                      source="update " + ",".join(map(str, rows)))
            out.append(("made", rows[0], item, (made_id, conn.made_items([made_id])[made_id][2])))
        return out

    def notice_fields(self, conn, texts, types: TypeIds, channel_id, row_id: int, subject: str,
                      payload: dict) -> dict:
        """What a one-file notice is worded from (`notice`): {what}, {subject}, {timestamp}, and
        {repeat}: the config's `notice_repeat` when an earlier change to the same file was already
        notified in this conversation (one before this update in the verbatim part, whose subject the
        conversation had mentioned by then), else ""."""
        earlier = conn.execute(
            "SELECT e.row_id FROM events e JOIN event_types t USING (event_type_id) WHERE t.name = ? "
            "AND e.row_id < ? AND json_extract(e.payload_json, '$.subject') = ?",
            (ENVIRONMENT_UPDATE, row_id, subject)).fetchall()
        first = min((row for row, _, text in texts if mentions(text, subject)), default=None)
        repeat = self.config.notice_repeat if any(first is not None and first < r for (r,) in earlier) else ""
        return {"what": payload.get("what") or f"{subject} changed", "subject": subject,
                "timestamp": shown(payload.get("timestamp")), "repeat": repeat}

    def own_change(self, texts, types: TypeIds, start: int, row_id: int, subject: str) -> bool:
        """Whether the update at `row_id` is the agent's own doing: a tool CALL that came in with it
        (rows after `start`, the channel's last read before it) names the subject and could have
        written it (`writes`). A call that only read the file, or an output that shows it, does not
        hide someone else's change."""
        calls = types.of("tool_call")
        return any(start < row < row_id and tid in calls and mentions(text, subject) and writes(text, subject)
                   for row, tid, text in texts)

    # ---- the rest is the sections: segmentation, ranking, builds, adoption

    def choose(self, conn, types: TypeIds, rows, latest, last_read, at_user: bool,
               read: Read) -> Tuple[Optional[dict], List[int]]:
        """(the build in use, its section items' made_ids in order), or
        (None, []). A ready build newer than the last read's is switched to
        when `at_user` -- at a user message, or when the context is over
        max_context_tokens -- and laid out then (`adopt`)."""
        if at_user and tables.waiting(latest, last_read):
            made = self.adopt(conn, types, rows, latest, read)
            if made is not None:
                return tables.get_build(conn, latest["build_id"]), made          # its cut as adoption set it
        used = tables.basis_of(last_read)
        if used is None:
            return None, []
        # the messages, notices and parallel requests of the last read are remade each time; only the
        # sections are reused
        made = [r.made_id for r in last_read["refs"] if r.made_id is not None]
        names = conn.made_items(made)
        return tables.get_build(conn, used), [m for m in made
                                              if names[m][0] not in ("context_stream", "environment_update", PARALLEL_REQUEST,
                                                                     LEFT_OUT)]

    def adopt(self, conn, types: TypeIds, rows, build: dict, read: Read) -> Optional[List[int]]:
        """Lay `build`'s analysis out as sections and store them as made
        items; None (and the build settled `nothing`) if they would not be
        smaller than the history they replace."""
        cfg, tok, groups, ch = self.config, self.tokenizer, self.groups, channel_of(read)
        _, turns = history.split(rows, types, groups, tok)
        with_cleaned(conn, [t.entries[0] for t in turns])
        tasks = tasks_tool.locate(tables.tasks_for(conn, ch), turns)
        if not tasks:
            tables.settle(conn, build["build_id"], "nothing", error="no tasks at adoption")
            return None
        foreign, turns_by_channel = self.other_tasks(conn, types, ch)
        turns_by_channel[ch] = turns
        before = tasks[:-2]
        earlier = layout.earlier_messages(before, turns, cfg, tok)
        shown = {id(before[i]) for i in earlier[1]}
        by_key = {(tables.key(t.channel_id), t.task_index): t for t in before + foreign}
        ranked = [by_key[tuple(k)] for k in build["ranking"] if tuple(k) in by_key]
        ranked = [t for t in ranked if id(t) not in shown]
        mark = build["parallel_mark"]
        others = [(c, e) for c, e in history.other_requests(conn, types, groups, tok, ch) if e.row_id <= mark]
        with_cleaned(conn, [e for _, e in others])
        sections = layout.build_sections(turns, tasks, ranked, earlier, others, turns_by_channel, ch, cfg, tok,
                                         conn.path, build["through_row"], mark)
        cut = self.cut_for(rows, types, tasks[-1], sections, conn.path)
        if cut != sections.open_from_row:
            sections = layout.build_sections(turns, tasks, ranked, earlier, others, turns_by_channel, ch, cfg, tok,
                                             conn.path, build["through_row"], mark, cut_row=cut)
        if len(tasks) < 2 and sections.open_from_row == tasks[-1].first_row:
            tables.settle(conn, build["build_id"], "nothing", error="fewer than two tasks, and no cut inside the one")
            return None
        if sections.open_from_row != build["open_from_row"]:
            tables.set_cut(conn, build["build_id"], sections.open_from_row)
        if cfg.require_smaller:
            why = self.not_smaller(sections, rows, turns, types)
            if why:
                tables.settle(conn, build["build_id"], "nothing", error=why)
                self.log(f"build {build['build_id']} not adopted: {why}")
                return None
        source = f"build {build['build_id']}"
        made = [conn.make_item(self.format.make_section(text, name), tok, properties=channel.of(ch), name=name,
                               source=source)
                for name, text in sections.sections]
        return made

    def cut_for(self, rows, types: TypeIds, running, sections, db_path) -> int:
        """Where the verbatim part should start: the running task's start -- or, when the sections, the
        pinned rows and the running task from there would be over max_context_tokens, after the last
        event: the running task is then all in "This task so far", and only what comes after it is
        verbatim."""
        cfg, tok = self.config, self.tokenizer
        _, body = history.arrange(rows, types, self.groups)
        task_rows = [r for r in body if r.row_id >= running.first_row]
        if not task_rows:
            return running.first_row
        held = sum(tok.count(text) for _, text in sections.sections) - tok.count(layout.overview(cfg, db_path))
        pinned_ids = types.of(*self.groups.pinned)
        pinned = self.newest_within([r for r in body if r.row_id < running.first_row and r.type.id in pinned_ids],
                                    cfg.keep_pinned_tokens)
        whole = held + sum(r.tokens for r in pinned) + sum(r.tokens for r in task_rows)
        return running.first_row if whole <= cfg.max_context_tokens else task_rows[-1].row_id + 1

    def not_smaller(self, sections, rows, turns, types: TypeIds) -> Optional[str]:
        pinned = types.of(*self.groups.pinned)
        replaced = sum(r.tokens for r in rows
                       if turns[0].first_row <= r.row_id < sections.open_from_row and r.type.id not in pinned)
        size = sum(self.tokenizer.count(text) for _, text in sections.sections)
        if size >= replaced:
            return f"sections ({size} tokens) not smaller than the history they replace ({replaced})"
        return None

    def start_due(self, conn, types: TypeIds, read: Read, rows, latest, in_use, size: int, over: bool = False) -> str:
        """Start what is due in the background: "build", "check" or "" (the build thresholds) -- at a
        user message, or at any read when the context is `over` max_context_tokens: a build then,
        or the one already running ("build", to wait for)."""
        cfg, ch = self.config, channel_of(read)
        if self.jobs is None:                      # no background work
            return ""
        if latest and latest["status"] == "running" and time.time() - latest["started_at"] < cfg.build_timeout:
            return "build" if over else ""
        if latest and latest["status"] == "ready" and (not in_use or latest["build_id"] != in_use["build_id"]):
            return ""
        if not over and size < cfg.min_context_tokens and not cfg.build_every_request:
            return ""
        if over or cfg.build_every_request:
            build_id = tables.claim_build(conn, ch, cfg.build_timeout, tables.LIMIT if over else tables.REQUEST)
            if build_id is None:
                return ""
            try:
                self.jobs.start(read.gatherer_id, channel.of(ch), "build", build_id)
            except OSError as exc:
                tables.fail_build(conn, build_id, f"could not start the worker: {exc}")
                return ""
            return "build"
        if not cfg.check_boundaries:
            return ""
        if in_use:
            since_row = in_use["open_from_row"] - 1
        elif latest and latest["status"] in ("failed", "nothing"):
            since_row = latest["through_row"] or 0
        else:
            since_row = 0
        into_task = sum(1 for r in rows if r.row_id > since_row and history.opens_turn(r, types, self.groups))
        if into_task <= cfg.boundary_cooldown:
            return ""
        row_id = rows[-1].row_id
        if not tables.claim_boundary(conn, row_id, ch):
            return ""
        try:
            self.jobs.start(read.gatherer_id, channel.of(ch), "check", row_id)
        except OSError as exc:
            tables.record_boundary(conn, row_id, False, f"could not start the worker: {exc}", ch)
            return ""
        return "check"

    def wait(self, conn, channel_id, row_id: int, started: str, seconds: float) -> bool:
        deadline = time.monotonic() + seconds
        while True:
            if started == "check":
                verdict = tables.boundary_verdict(conn, row_id)
                if verdict and verdict["new_task"] is False:
                    return False
                if verdict and verdict["new_task"] is True:
                    started = "build"
            if started == "build":
                build = tables.latest_build(conn, channel_id)
                if build and build["status"] == "ready":
                    return True
                if build and build["status"] in ("failed", "nothing"):
                    return False
            if time.monotonic() >= deadline:
                return False
            time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))

    def other_tasks(self, conn, types: TypeIds, channel_id) -> Tuple[List, Dict]:
        found, turns_by_channel = [], {}
        for other in tables.channels_with_tasks(conn):
            if other == channel_id or other is None:
                continue
            _, turns = history.split(history.rows(conn, types, self.groups, other), types, self.groups, self.tokenizer)
            with_cleaned(conn, [t.entries[0] for t in turns])
            turns_by_channel[other] = turns
            found += tasks_tool.locate(tables.load_tasks(conn, other), turns)
        return found, turns_by_channel

    # ------------------------------------------------------------ the worker's jobs

    def build(self, gatherer_id: str, properties, build_id: int) -> Optional[dict]:
        """The analysis: segmentation, the summaries of the newly finished
        tasks, a ranking of every earlier task. Kept in `tasks` and on the
        build (tables.py). A build started because the context was over
        max_context_tokens (reason `limit`) closes the running task at the
        last user message: what came before is finished and summarised, and
        that message starts the running task (`limit_tasks`). Within the
        limit the channel's harness stated last (`within`)."""
        conn = self.gatherers.open(gatherer_id)
        try:
            last = conn.last_read(channel.of(channel_of(properties)))
        finally:
            conn.close()
        with self.within((last or {}).get("limit_tokens")):
            return self.build_within(gatherer_id, properties, build_id)

    def build_within(self, gatherer_id: str, properties, build_id: int) -> Optional[dict]:
        channel_id = channel_of(properties)
        cfg, tok, groups = self.config, self.tokenizer, self.groups
        conn = self.gatherers.open(gatherer_id)
        try:
            types = TypeIds.load(conn)
            rows = history.rows(conn, types, groups, channel_id)
            through_row = rows[-1].row_id if rows else 0
            mark = conn.high_water()
            preamble, turns = history.split(rows, types, groups, tok)
            limit = (tables.get_build(conn, build_id) or {}).get("reason") == tables.LIMIT
            if limit:
                if not turns:
                    return self.nothing(conn, build_id, through_row, "no turns")
                tasks, failed, fresh = self.limit_tasks(conn, channel_id, turns)
            else:
                # one turn, or one task, is built only when it is over the limit: a cut inside it is then due
                oversized = sum(r.tokens for r in rows) - sum(e.tokens for e in preamble) > cfg.max_context_tokens
                if len(turns) < 2 and not oversized:
                    return self.nothing(conn, build_id, through_row, "fewer than two turns")
                tasks, failed, fresh = segmentation.update(turns, tables.tasks_for(conn, channel_id), self.llm,
                                                           cfg.segmentation, tok)
            if failed:
                tables.fail_build(conn, build_id, "segmentation: no model call answered", through_row=through_row)
                return None
            for i, t in enumerate(tasks):
                t.channel_id, t.task_index = channel_id, i
            if not limit and len(tasks) < 2 and not (tasks and oversized):
                tables.save_tasks(conn, channel_id, tasks)
                return self.nothing(conn, build_id, through_row, "fewer than two tasks")
            with ThreadPoolExecutor(max_workers=1) as pool:
                summaries = pool.submit(summarize.summarize, fresh, turns, self.llm, cfg.summarizing) if fresh else None
                candidates = list(tasks[:-2])
                if cfg.parallel_related_tasks:
                    candidates += self.other_tasks(conn, types, channel_id)[0]
                ranked = ranking.rank(candidates, ranking.rank_target(turns, cfg.ranking), self.llm, cfg.ranking,
                                      own_channel=channel_id, top_n=len(candidates)) if candidates else []
                if summaries:
                    summaries.result()
            tables.save_cleaned(conn, build_id, cleaned_of(fresh, turns))
            tables.save_tasks(conn, channel_id, tasks)
            tables.settle(conn, build_id, "ready", through_row=through_row, open_from_row=tasks[-1].first_row,
                          ranking=[(tables.key(t.channel_id), t.task_index) for t in ranked], parallel_mark=mark)
            return tables.get_build(conn, build_id)
        finally:
            conn.close()

    def limit_tasks(self, conn, channel_id, turns) -> Tuple[List, bool, List]:
        """(the tasks, whether segmentation failed, the tasks to summarise) of a `limit` build: the
        last user message starts the running task, CURRENT_REQUEST, and everything before it is
        finished. Segmentation is given only the turns before it, so it names and describes tasks
        from exactly the turns they cover; the last task it returns -- open in its view -- is closed
        here and summarised with the others it finished. A second limit build in the same turn finds
        the running task already starting there and segments nothing again."""
        last = turns[-1]
        current = history.Task(CURRENT_REQUEST, last.user_text.strip()[:200], last.first_row, last.last_row,
                               last.index, last.index)
        stored = tasks_tool.locate(tables.tasks_for(conn, channel_id), turns)
        if len(turns) == 1:
            return [current], False, []
        if stored and stored[-1].first_row == last.first_row:      # an earlier limit build in this turn
            return stored[:-1] + [current], False, []
        tasks, failed, fresh = segmentation.update(turns[:-1], tables.tasks_for(conn, channel_id), self.llm,
                                                   self.config.segmentation, self.tokenizer)
        if failed:
            return tasks, True, fresh
        if tasks and all(t is not tasks[-1] for t in fresh):
            fresh = fresh + [tasks[-1]]                            # finished now: summarised with the rest
        return tasks + [current], False, fresh

    def nothing(self, conn, build_id: int, through_row: int, why: str) -> None:
        tables.settle(conn, build_id, "nothing", through_row=through_row, error=why)
        self.log(f"no build: {why}")
        return None

    def check(self, gatherer_id: str, properties, row_id: int) -> bool:
        """The boundary tool's verdict on the user message `row_id`, recorded;
        on a yes, a build is claimed and run; no usable answer counts as a
        no. Returns what was decided."""
        channel_id = channel_of(properties)
        cfg, tok, groups = self.config, self.tokenizer, self.groups
        conn = self.gatherers.open(gatherer_id)
        try:
            types = TypeIds.load(conn)
            rows = history.rows(conn, types, groups, channel_id)
            _, turns = history.split(rows, types, groups, tok)
            stored = tasks_tool.locate(tables.tasks_for(conn, channel_id), turns)
            open_from = stored[-1].first_row if stored else (turns[0].first_row if turns else 0)
            open_turns = [t for t in turns if t.first_row >= open_from]
            if len(open_turns) > 1:
                verdict, why = boundary.is_new_task(open_turns, stored[:-1], turns, self.llm, cfg.boundary)
                if verdict is None:
                    verdict, why = False, f"{why}; treated as a continuation"
            else:
                verdict, why = False, "first turn of the open task"
            tables.record_boundary(conn, row_id, verdict, why, channel_id)
            if not verdict:
                return False
            build_id = tables.claim_build(conn, channel_id, cfg.build_timeout, tables.BOUNDARY)
        finally:
            conn.close()
        if build_id is not None:
            self.build(gatherer_id, channel.of(channel_id), build_id)
        return True

    def bulk_loaded(self, conn, gatherer_id: str, properties) -> Any:
        return self.build(gatherer_id, properties, tables.new_build(conn, channel_of(properties)))
