"""Keeping the context under its token limit. A harness that states its own limit with a call has the config scaled
to it for that call (`use_limit`, config.within_limit).

All the model gets with a call -- the sections, the pinned rows, the running
task with the gatherer's messages among it, the history's preamble, the sections'
overview, and what the harness sends besides the context (its system prompt
and tools, `Read.fixed_tokens`) -- is kept at or under max_context_tokens,
and is what min_context_tokens is checked against. Above it, on any read
(not only at a user message), a build is started -- or the running one
awaited -- and the read waits for it; adopted, it cuts the running task
after its last event when the context would not otherwise fit (`get_verbatim_start`):
the running task, condensed, is "This task so far", and only what comes
after it is verbatim. The budgets add up under the limit (the config
refuses them otherwise), every section keeps to its own, and the pinned rows
to keep_pinned_tokens, the newest kept. What still does not fit -- a step
larger than the room the build leaves -- is left out with a note naming its
rows (`stub_old_steps`).

Every one of these checks counts as the provider does (`get_provider_count`): the
hooks replace ag's counts by the provider's as they learn them, and what is
still ag's is scaled by how far the provider's own count of the channel's last
call ran over ag's (`get_provider_drift`). The build that a provider's count over the
limit starts so decides by that same count where to cut and what to leave out,
and does not keep the running task whole because ag's own count says it fits
(2026-11-01: an Antigravity actor, Gemini counting 20% over ag, started a build
at every call for minutes, each keeping the cut where it was)."""

from contextlib import contextmanager
from typing import Dict, List, Optional, Tuple

from ag.ag_interface import event_text
from ag.ag_interface.policy import Read, TypeIds
from ag.ag_policies.tools import history
from ag.ag_policies.tools.channel import channel_of
from . import layout
from .config import ProactiveContextManagerConfig, within_limit
from .gatherer_messages import LEFT_OUT, GathererMessages
from .wording import LEFT_OUT_CALLS, LEFT_OUT_NOTE

DRIFT_MAX = 1.5                 # the most `get_provider_drift` scales ag's count by: tokenizers differ by up to ~25% (Gemini's
                                # over o200k_base); a provider's count further over ag's is something ag does not see,
                                # not its own items counted short, and is left to `is_provider_over_limit`
                                # over o200k_base); a provider's count further over ag's is something ag does not see,
                                # not its own items counted short, and is left to `is_provider_over_limit`
AGENT_STEP = ("agent_message", "tool_call", "agent_reasoning")   # what an agent step may start with


class ContextLimit(GathererMessages):
    max_given: bool                                   # the gatherer set max_context_tokens: no harness's limit wins
    _limited: Dict[int, ProactiveContextManagerConfig]
    drift: float

    @contextmanager
    def use_limit(self, limit: Optional[int]):
        """`self.config` as a harness's own limit makes it (`config.within_limit`), while in
        the block: one read, or one build. Not when the gatherer sets max_context_tokens, or
        none is stated. (A policy is made for each request the server answers, and each job the
        worker runs: no other thread reads its config meanwhile.)"""
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

    @staticmethod
    def get_provider_drift(last: Optional[dict]) -> float:
        """How far over ag's count the provider counted a call: `last`'s own count (`real_tokens`, reported after
        it) over ag's count of all it sent (`sent_tokens`), at most DRIFT_MAX -- 1 when either is not known, or the
        provider counted no more than ag. The hooks set the provider's counts in place of ag's as they learn them (counting.py),
        and what is still ag's (new steps not counted yet; a harness with no count endpoint, all of it) is short
        by about this much."""
        real, sent = (last or {}).get("real_tokens"), (last or {}).get("sent_tokens")
        if not isinstance(real, int) or not isinstance(sent, int) or sent <= 0 or real <= sent:
            return 1.0
        return min(real / sent, DRIFT_MAX)

    def get_provider_count(self, tokens: int) -> int:
        """`tokens`, ag's count, as the provider would count them: scaled by `drift` (the channel's last call's,
        set at each read and build) -- what max_ and min_context_tokens are checked against, so a build decides
        by the count that started it."""
        return tokens if self.drift <= 1.0 else int(tokens * self.drift)

    def is_over_limit(self, size: int, last: Optional[dict], build: Optional[dict], ch) -> bool:
        """Whether a read's context of `size` tokens is over max_context_tokens: by ag's count, as the provider
        would count it, or by the provider's own count of the last call, which this read extends (`is_provider_over_limit`)."""
        return self.get_provider_count(size) > self.config.max_context_tokens or self.is_provider_over_limit(last, build, ch)

    def is_provider_over_limit(self, last: Optional[dict], build: Optional[dict], ch) -> bool:
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

    def get_verbatim_start(self, rows, types: TypeIds, running, sections, db_path, fixed_tokens: int = 0,
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
        overview = tok.count(layout.overview(cfg, joining))
        held = sum(tok.count(text) for _, text in sections.sections) - overview
        pinned_ids = types.of(*self.groups.pinned)
        pinned = self.get_newest_rows([r for r in body if r.row_id < running.first_row and r.type.id in pinned_ids],
                                    cfg.keep_pinned_tokens)
        whole = held + sum(r.tokens for r in pinned) + sum(r.tokens for r in task_rows) \
            + sum(r.tokens for r in preamble) + overview + tok.count(layout.guide(cfg, db_path)) + fixed_tokens
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
            made_id, item, note = self.make_message(conn, channel_of(read), text, LEFT_OUT, f"rows {first}-{last}")
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
