"""One read: the context the agent's next model call gets (`assemble_context`), in this order -- the harness's own
set-up, the gatherer guide, the history sections of the build in use (`choose_build`; a ready one is laid out as
sections at its adoption, `adopt_build`) or, with none, the requests made before the session began, the pinned rows,
and the running task word for word, with the gatherer's messages among it.

The gatherer's messages: what ag adds to an agent's context besides the conversation's own rows -- the gatherer
guide, the history sections, the requests made in parallel, file-change notices, messages from a stream, notes of a
change of groups and left-out notes. Each is a made item, named by its kind (the names below) and stored so the read
log shows what was sent (`tables.make_message`); its words come from prompts.py. A read makes every one again but the history
sections, which are laid out once per build and reused (`REMADE_EVERY_READ`), and places each at its own row among the
conversation's (`interleave_messages`).

All the model gets with a call -- the sections, the pinned rows, the running
task with the gatherer's messages among it, the history's preamble, the sections'
overview, and what the harness sends besides the context (its system prompt
and tools, `Read.fixed_tokens`) -- is kept at or under max_context_tokens,
and is what min_context_tokens is checked against. Above it, on any read
(not only at a user message), a build is started -- or the running one
awaited -- and the read waits for it; adopted, it cuts the running task
after its last event when the context would not otherwise fit (`cut_for`):
the running task, condensed, is "This task so far", and only what comes
after it is verbatim. The budgets add up under the limit (the config
refuses them otherwise), every section keeps to its own, and the pinned rows
to keep_pinned_tokens, the newest kept. What still does not fit -- a step
larger than the room the build leaves -- is left out with a note naming its
rows (`stubbed`)."""

from typing import Any, Dict, List, NamedTuple, Optional, Tuple

from ag.ag_interface import Ref, event_text, property_column
from ag.ag_interface.policy import Read, TypeIds
from ag.ag_policies.tools import channel, history
from ag.ag_policies.tools import tasks as tasks_tool
from ag.ag_policies.tools.channel import CHANNEL, channel_of
from ag.ag_policies.tools.groups import TOOL_CALL, TOOL_OUTPUT
from ..db import tables
from ..db.tables import GUIDE, GROUP_CHANGE, LEFT_OUT, PARALLEL_BEFORE, PARALLEL_REQUEST
from ..events import CALL_ID, CONTEXT_STREAM, ENVIRONMENT_UPDATE
from . import sections
from .external_events import ExternalEvents
from .prompts import LEFT_OUT_CALLS, LEFT_OUT_NOTE
from .parallel_sessions import GROUP
from .summaries import CURRENT_REQUEST, Summaries

# The made items a read makes again every time -- the messages, notices, parallel requests, notes and the guide: of
# the last read's made items, only the sections are reused (`choose_build`).
REMADE_EVERY_READ = (CONTEXT_STREAM, ENVIRONMENT_UPDATE, PARALLEL_REQUEST, PARALLEL_BEFORE, LEFT_OUT, GUIDE, GROUP_CHANGE)
                                # over o200k_base); a provider's count further over ag's is something ag does not see,
                                # not its own items counted short, and is left to `is_provider_over_limit`
                                # over o200k_base); a provider's count further over ag's is something ag does not see,
                                # not its own items counted short, and is left to `is_provider_over_limit`
AGENT_STEP = ("agent_message", "tool_call", "agent_reasoning")   # what an agent step may start with


class Draft(NamedTuple):
    """A read's context as laid out from one choice of build (`choose_build`): the build in use and its sections'
    made_ids, and what `assemble_context` made of them -- `size`, all the model gets; `own`, the part the policy arranges."""
    build: Optional[dict]
    made: List[int]
    items: list
    refs: list
    size: int
    own: int


class Assembly(Summaries, ExternalEvents):
    """The read's part, which takes in every other part of the policy."""

    def draft_context(self, conn, types: TypeIds, rows, latest, last_read, at_user: bool, read: Read) -> Draft:
        """The context laid out from the build `choose_build` picks -- switching to `latest`, a newer ready
        one, when `at_user` -- by `assemble_context`."""
        build, made = self.choose_build(conn, types, rows, latest, last_read, at_user, read)
        return Draft(build, made, *self.assemble_context(conn, rows, build, made, types, read))

    def assemble_context(self, conn, rows, build: Optional[dict], made: List[int], types: TypeIds,
                 read: Read, stub: bool = False) -> Tuple[list, list, int, int]:
        """(items, refs, tokens, own): the sectioned context -- preamble, the
        gatherer guide (`make_guide_message`), the section items, the pinned rows of the condensed span (the newest that
        fit keep_pinned_tokens), the running task verbatim (or the whole
        history before a build; after a build that cut the running task,
        only what came after it) -- with every stream message of the
        verbatim part shown in that last, verbatim run, at its row's place,
        and a notice at the place of each environment update of the verbatim
        part whose subject the agent's tool calls before it opened (`make_file_change_notices`). Messages and notices
        are made items; the events are never returned. Then the requests made
        to the other channels (`make_parallel_requests`): each where it was first
        shown, a new one before this channel's latest user message -- or,
        mid-turn, at the end (`get_request_positions`).

        `tokens` is all the model gets with the context, what min_ and
        max_context_tokens are checked against: the context, and what the
        harness sends besides it (`read.fixed_tokens`, its system prompt and
        tools). `own` is the part the policy arranges, logged as the read's
        size: all of it but the harness's, the history's preamble, the guide and the
        sections' fixed overview. With `stub`, over the limit, agent steps of
        the verbatim part are replaced by notes naming their rows (`stub_old_steps`):
        the read's last resort, once it has built what it could."""
        cfg = self.config
        preamble, body = history.arrange(rows, types, self.groups)
        if build is None:
            cut = 0
            pinned, tail = [], body
            made_items = {}
        else:
            cut = build["open_from_row"]
            pinned_ids = types.of(*self.groups.pinned)
            pinned = self.get_newest_rows([r for r in body if r.row_id < cut and r.type.id in pinned_ids],
                                        cfg.keep_pinned_tokens)
            tail = [r for r in body if r.row_id >= cut]
            made_items = conn.made_items(made)
        guide = self.make_guide_message(conn, channel_of(read), types)
        before, since = self.make_earlier_requests_block(conn, types, rows, channel_of(read)) if build is None else ([], 0)
        items = ([r.payload for r in preamble] + [g[1] for g in guide] + [b[1] for b in before]
                 + [made_items[m][1] for m in made] + [r.payload for r in pinned])
        refs = ([Ref(row_id=r.row_id) for r in preamble] + [Ref(made_id=g[0]) for g in guide]
                + [Ref(made_id=b[0]) for b in before]
                + [Ref(made_id=m) for m in made] + [Ref(row_id=r.row_id) for r in pinned])
        fixed = self.tokenizer.count(sections.overview(cfg, tables.is_join(build))) if made else 0
        tokens = (sum(r.tokens for r in pinned) + sum(made_items[m][2] for m in made) - fixed
                  + sum(b[2] for b in before))
        made_here = (self.make_stream_messages(conn, types, channel_of(read), cut)
                     + self.make_file_change_notices(conn, types, channel_of(read), cut, preamble + pinned + tail, read.properties)
                     + self.make_group_change_notes(conn, types, channel_of(read), cut))
        entries = list(self.interleave_messages(tail, made_here, types))
        shown = self.make_parallel_requests(conn, types, channel_of(read), build["parallel_mark"] if build else since)
        tokens += sum(cost[1] if kind == "made" else cost for kind, _, _, cost in entries) + sum(c for _, _, c, _ in shown)
        outside = (sum(r.tokens for r in preamble) + sum(g[2] for g in guide) + fixed
                   + read.fixed_tokens)                                          # the model gets these too
        tokens += outside
        if stub and self.get_provider_count(tokens) > cfg.max_context_tokens:
            entries, tokens = self.stub_old_steps(conn, entries, tokens, types, read)
        for kind, row_id, item, cost in entries:
            items.append(item)
            refs.append(Ref(row_id=row_id) if kind == "row" else Ref(made_id=cost[0]))
        if shown:
            places = self.get_request_positions(conn, refs, len(refs) - len(entries), rows, types, channel_of(read), shown)
            for at, i in sorted(((at, i) for i, at in enumerate(places)), reverse=True):
                made_id, item, _, _ = shown[i]              # the last first: the earlier places stay put,
                items.insert(at, item)                       # and the oldest at one place comes first
                refs.insert(at, Ref(made_id=made_id))
        return items, refs, tokens, tokens - outside

    def make_guide_message(self, conn, channel_id, types: Optional[TypeIds] = None) -> List[tuple]:
        """[(made_id, item, tokens)] of the gatherer guide for the channel's reads, or [] with none
        configured. One made item while its text stays the same: the last one made for the channel,
        if it is that text, else a new one. A database whose channels have groups (`group` records:
        the home's one) has its hint say how to keep to the channel's own."""
        seen = self.get_hidden_sessions(conn, types, channel_id) if types is not None and types.of(GROUP) else None
        text = sections.guide(self.config, conn.path, seen.own if seen is not None and seen.groups else None,
                            sorted(seen.reads) if seen is not None else ())
        if not text:
            return []
        item = self.format.make_section(text, GUIDE)
        col = property_column(CHANNEL)
        found = conn.execute(f"SELECT made_id FROM _made_items WHERE name = ? AND ifnull({col}, '') = ? "
                             f"ORDER BY made_id DESC LIMIT 1", (GUIDE, tables.get_channel_key(channel_id))).fetchone()
        made_id = found[0] if found else None
        if made_id is None or conn.made_items([made_id])[made_id][1] != item:
            made_id = conn.make_item(item, self.tokenizer, properties=channel.of(channel_id), name=GUIDE)
        return [(made_id, item, conn.made_items([made_id])[made_id][2])]

    # ---- the build a read uses

    def choose_build(self, conn, types: TypeIds, rows, latest, last_read, at_user: bool,
               read: Read) -> Tuple[Optional[dict], List[int]]:
        """(the build in use, its section items' made_ids in order), or
        (None, []). A ready build newer than the last read's is switched to
        when `at_user` -- at a user message, when the context is over
        max_context_tokens, or at a later call of the turn a new task's build was
        made for (`is_build_for_this_turn`) -- and laid out then (`adopt_build`)."""
        if at_user and tables.is_waiting(latest, last_read):
            made = self.adopt_build(conn, types, rows, latest, read)
            if made is not None:
                return tables.get_build(conn, latest["build_id"]), made          # its cut as adoption set it
        used = tables.get_basis(last_read)
        if used is None:
            return None, []
        made = [r.made_id for r in last_read["refs"] if r.made_id is not None]
        names = conn.made_items(made)
        return tables.get_build(conn, used), [m for m in made if names[m][0] not in REMADE_EVERY_READ]

    def is_build_for_this_turn(self, build: Optional[dict], rows, types: TypeIds) -> bool:
        """Whether `build` is a new task's build made at this turn's own user message: its check found
        the new task there, and the read at it went on without it (the build took longer than the read
        waited). It is taken up at the turn's next call, not at the next user message: the sections
        replace only what came before the turn, and the turn itself stays verbatim, as it was."""
        if not build or build.get("reason") != tables.BOUNDARY or build["status"] != "ready":
            return False
        opening = next((r.row_id for r in reversed(rows) if history.opens_turn(r, types, self.groups)), None)
        return opening is not None and build["through_row"] == opening

    def adopt_build(self, conn, types: TypeIds, rows, build: dict, read: Read) -> Optional[List[int]]:
        """Lay `build` out as sections and store them as made
        items; None (and the build settled `nothing`) if they would not be
        smaller than the history they replace."""
        cfg, tok, groups, ch = self.config, self.tokenizer, self.groups, channel_of(read)
        _, turns = history.split(rows, types, groups, tok)
        tables.apply_cleaned_texts(conn, [t.entries[0] for t in turns])
        joining = tables.is_join(build)
        if joining:                                  # its own history, all of it, is the running task
            tasks = [self.get_join_task(turns, ch)] if turns else []
        else:
            tasks = tasks_tool.locate(tables.get_tasks(conn, ch), turns)
        if not tasks:
            tables.settle_build(conn, build["build_id"], "nothing", error="no tasks at adoption")
            return None
        foreign, turns_by_channel = self.get_other_sessions_tasks(conn, types, ch, read.stopped)
        if read.stopped():                           # the harness hung up meanwhile (Esc): laid out at the next read
            return None
        turns_by_channel[ch] = turns
        before = tasks[:-2]
        earlier = sections.earlier_messages(before, turns, cfg, tok)
        shown = {id(before[i]) for i in earlier[1]}
        by_key = {(tables.get_channel_key(t.channel_id), t.task_index): t for t in before + foreign}
        ranked = [by_key[tuple(k)] for k in build["ranking"] if tuple(k) in by_key]
        ranked = [t for t in ranked if id(t) not in shown]
        mark = build["parallel_mark"]
        unseen = self.get_hidden_sessions(conn, types, ch)
        others = [(c, e) for c, e in history.other_requests(conn, types, groups, tok, ch,
                                                            keep=lambda r: channel_of(r) not in unseen and self.is_user_request(r))
                  if e.row_id <= mark]
        tables.apply_cleaned_texts(conn, [e for _, e in others])
        laid_out = sections.build_sections(turns, tasks, ranked, earlier, others, turns_by_channel, ch, cfg, tok,
                                         conn.path, build["through_row"], mark, joined=joining)
        cut = self.get_verbatim_start(rows, types, tasks[-1], laid_out, conn.path, read.fixed_tokens, joining)
        if cut != laid_out.open_from_row:
            laid_out = sections.build_sections(turns, tasks, ranked, earlier, others, turns_by_channel, ch, cfg, tok,
                                             conn.path, build["through_row"], mark, cut_row=cut, joined=joining)
        if not joining and len(tasks) < 2 and laid_out.open_from_row == tasks[-1].first_row:
            tables.settle_build(conn, build["build_id"], "nothing", error="fewer than two tasks, and no cut inside the one")
            return None
        if laid_out.open_from_row != build["open_from_row"]:
            tables.set_cut(conn, build["build_id"], laid_out.open_from_row)
        # compacted: not sent whole again; joined: the sections replace nothing of its own, they add the others' work;
        # regrouped: they replace sections made from another group's work
        if cfg.require_smaller and build.get("reason") not in (tables.COMPACTION, tables.JOIN, tables.REGROUPED):
            why = self.get_not_smaller_reason(laid_out, rows, turns, types)
            if why:
                tables.settle_build(conn, build["build_id"], "nothing", error=why)
                self.log(f"build {build['build_id']} not adopted: {why}")
                return None
        source = f"build {build['build_id']}"
        made = [conn.make_item(self.format.make_section(text, name), tok, properties=channel.of(ch), name=name,
                               source=source)
                for name, text in laid_out.sections]
        return made

    @staticmethod
    def get_join_task(turns, channel_id) -> history.Task:
        """The one task of a channel that joined: all its turns, running."""
        first, last = turns[0], turns[-1]
        task = history.Task(CURRENT_REQUEST, first.user_text.strip()[:200], first.first_row, last.last_row,
                            first.index, last.index)
        task.channel_id = channel_id
        return task

    def get_not_smaller_reason(self, laid_out, rows, turns, types: TypeIds) -> Optional[str]:
        """Why the sections `laid_out` are not worth adopting -- they are no smaller than the history they replace
        (require_smaller) -- or None."""
        pinned = types.of(*self.groups.pinned)
        replaced = sum(r.tokens for r in rows
                       if turns[0].first_row <= r.row_id < laid_out.open_from_row and r.type.id not in pinned)
        size = sum(self.tokenizer.count(text) for _, text in laid_out.sections)
        if size >= replaced:
            return f"sections ({size} tokens) not smaller than the history they replace ({replaced})"
        return None

    # ---- the gatherer's messages at their rows

    def interleave_messages(self, tail, made_here: List[tuple], types: TypeIds) -> List[tuple]:
        """The tail's rows, as ("row", row_id, payload, tokens), and the
        messages and notices made for outside events, together in row
        order: each where its event was stored, which -- the pollers being
        asked at read time -- is where the model first saw it. But never
        between a tool call and its output (`get_call_output_pairs`): one stored there
        goes right after the output. A call and its output come in with one
        request, so nothing is stored between them -- until the harness hangs
        up on the call that sent the output (the output withdrawn: its newest
        user row) and sends it again changed (Claude Code, resumed, puts a
        note of its own inside it): stored again as a new row, after what came
        in meanwhile. The API refuses a tool call with anything but its
        result right after it."""
        entries = [("row", r.row_id, r.payload, r.tokens) for r in tail] + list(made_here)
        spans = self.get_call_output_pairs(tail, types)

        def place(e) -> tuple:
            if e[0] == "row":
                return (e[1], 0, e[1])
            at = e[1]
            moved = True
            while moved:                                     # past every exchange it falls in, nested or chained
                ends = [end for start, end in spans if start < at < end]
                moved = bool(ends)
                at = max(ends) if ends else at
            return (at, 0 if at == e[1] else 1, e[1])        # moved: right after the output, in its own order
        return sorted(entries, key=place)

    @staticmethod
    def get_call_output_pairs(tail, types: TypeIds) -> List[Tuple[int, int]]:
        """(call row, output row) of each tool call of `tail` whose output is in it too, paired by the call id
        the harness's adaptor gives both (CALL_ID); a row without one pairs with nothing."""
        calls_ids, outputs_ids = types.of(TOOL_CALL), types.of(TOOL_OUTPUT)
        calls: Dict[Any, int] = {}
        spans = []
        for r in tail:
            call = (r.properties or {}).get(CALL_ID)
            if call is None:
                continue
            if r.type.id in calls_ids:
                calls.setdefault(call, r.row_id)
            elif r.type.id in outputs_ids and call in calls:
                spans.append((calls[call], r.row_id))
        return spans

    # ---- over the limit: where the word-for-word part starts, and which steps become left-out notes

    def get_verbatim_start(self, rows, types: TypeIds, running, laid_out, db_path, fixed_tokens: int = 0,
                joining: bool = False) -> int:
        """Where the verbatim part should start: the running task's start -- or, when the sections, the
        pinned rows and the running task from there, with what the model gets besides them (the
        history's preamble, the harness's `fixed_tokens`), would be over max_context_tokens as the provider
        counts them (`get_provider_count`), after the last event: the running task is then all in "This task so
        far", and only what comes after it is verbatim."""
        cfg, tok = self.config, self.tokenizer
        preamble, body = history.arrange(rows, types, self.groups)
        task_rows = [r for r in body if r.row_id >= running.first_row]
        if not task_rows:
            return running.first_row
        overview = tok.count(sections.overview(cfg, joining))
        held = sum(tok.count(text) for _, text in laid_out.sections) - overview
        pinned_ids = types.of(*self.groups.pinned)
        pinned = self.get_newest_rows([r for r in body if r.row_id < running.first_row and r.type.id in pinned_ids],
                                    cfg.keep_pinned_tokens)
        whole = held + sum(r.tokens for r in pinned) + sum(r.tokens for r in task_rows) \
            + sum(r.tokens for r in preamble) + overview + tok.count(sections.guide(cfg, db_path)) + fixed_tokens
        return running.first_row if self.get_provider_count(whole) <= cfg.max_context_tokens else task_rows[-1].row_id + 1

    @staticmethod
    def get_newest_rows(rows: list, budget: int) -> list:
        """The newest of `rows` whose tokens add up to at most `budget`, in order."""
        kept, used = [], 0
        for r in reversed(rows):
            if used + r.tokens > budget:
                break
            kept.append(r)
            used += r.tokens
        return kept[::-1]

    def get_step_starts(self, rows) -> List[int]:
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

    def stub_old_steps(self, conn, entries: list, tokens: int, types: TypeIds, read: Read) -> Tuple[list, int]:
        """`entries` brought within max_context_tokens, as far as replacing agent steps of the verbatim
        part by notes naming their rows gets there: first each step far larger than its note, largest
        first (a huge tool output); then, if still over, the oldest steps together, by one note,
        until it fits -- the newest step is kept. A step's tool calls go with their outputs, so what
        remains is still a valid conversation; user messages are never replaced."""
        cfg = self.config
        by_row = {r.row_id: r for r in history.rows(conn, types, self.groups, channel_of(read))}
        rows = [(i, rid) for i, (kind, rid, _, _) in enumerate(entries) if kind == "row" and rid in by_row]
        starts = set(self.get_step_starts([by_row[rid] for _, rid in rows]))
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
            listed = "; ".join(calls[:3]) + (" ..." if len(calls) > 3 else "")
            text = LEFT_OUT_NOTE.format(count=len(indices), tokens=size,
                                        calls=LEFT_OUT_CALLS.format(calls=listed) if calls else "",
                                        first=first, last=last, db_path=conn.path)
            made_id, item, note = tables.make_message(conn, self.format, self.tokenizer, channel_of(read), text, LEFT_OUT, f"rows {first}-{last}")
            replaced[indices[0]] = ("made", first, item, (made_id, note))
            for i in indices[1:]:
                replaced[i] = None
            return size - note

        note_size = 4 * self.tokenizer.count(f"[Agent steps were left out here ... {conn.path} ...]")
        for step in sorted(steps, key=lambda st: -sum(cost(i) for i in st)):
            if self.get_provider_count(tokens) <= cfg.max_context_tokens or sum(cost(i) for i in step) < 5 * note_size:
                break                                    # a note per step only for a step far larger than it
            tokens -= stub(step)
        left = [st for st in steps if st[0] not in replaced]
        if self.get_provider_count(tokens) > cfg.max_context_tokens and len(left) > 1:
            run, saved = [], 0
            for st in left[:-1]:                         # the oldest first; the newest step stays
                run.append(st)
                saved = sum(cost(i) for s_ in run for i in s_) - note_size // 4
                if self.get_provider_count(tokens - saved) <= cfg.max_context_tokens:
                    break
            run_indices = [i for s_ in run for i in s_]
            if all(b == a + 1 or replaced.get(a + 1, 0) is None for a, b in zip(run_indices, run_indices[1:])):
                tokens -= stub(run_indices)
        return [replaced.get(i, e) for i, e in enumerate(entries) if replaced.get(i, e) is not None], tokens
