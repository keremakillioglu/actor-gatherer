"""What gets summarized, and when. A build splits a session's history into tasks, summarizes each one newly
finished, and ranks every earlier task -- its own, and its group's other sessions' -- against the work now; the
history sections are laid out from that (sections.py). The new-task check asks the model whether a user message
starts a new task. Both run in the worker (utils/jobs.py); what starts each is here (`start_due_work`,
`rebuild_for_new_group`).

A channel with no build of its own, in a gatherer where another channel has a ready one
(`tables.joinable`), JOINS at its first user message: a `join` build ranks the other
channels' tasks against its request and marks their requests as seen, and the read waits
for it. Its sections are the other channels' requests and related tasks, its own history
all the running task, verbatim -- so a new session starts from what the gatherer's others
did, and their requests before the mark are an index within its budget, not a message each.

A user message the boundary check finds starts a new task gets its build: the read waits
for it up to build_wait_seconds. One that takes longer is taken up at the turn's next call
(`for_this_turn`), not left for the next user message: the turn itself stays verbatim, so
the switch replaces only the history before it."""

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, List, Optional, Tuple

from ag.ag_interface.policy import Read, TypeIds
from ag.ag_policies.tools import boundary, channel, history, ranking, segmentation, summarize
from ag.ag_policies.tools import tasks as tasks_tool
from ag.ag_policies.tools.channel import channel_of
from ..db import tables
from ..utils.jobs import BackgroundJobs
from .parallel_sessions import ParallelSessions

CURRENT_REQUEST = "Current request"   # the running task a `limit` build starts at the last user message


def get_cleaned_requests(tasks, turns) -> dict:
    """{events row_id: cleaned text} for the user messages the summaries of `tasks` cleaned -- each
    entry's turn mapped to its user message's row -- taken out of the tasks' retention (they are
    kept in their own table, not with the task's rules)."""
    by_index = {turn.index: turn for turn in turns}
    out = {}
    for task in tasks:
        for cleaned in (task.retention or {}).pop(summarize.CLEANED, None) or []:
            turn = by_index.get(cleaned.get("turn"))
            if turn is not None and task.start_turn <= turn.index <= task.end_turn and cleaned.get("text", "").strip():
                out[turn.first_row] = cleaned["text"]
    return out


class Summaries(BackgroundJobs, ParallelSessions):

    def start_due_work(self, conn, types: TypeIds, read: Read, rows, latest_build, in_use, size: int, over_limit: bool = False) -> str:
        """Start what is due in the background: "build", "check", "join" or "" (the build thresholds) --
        at a user message, or at any read when the context is `over_limit` max_context_tokens: a build then,
        or the one already running ("build", to wait for). A channel with no build at all (`latest_build`
        None: neither its own nor the no-channel pool's) joins, when another channel has one: a
        `join` build, whatever the context's size, which the read waits for."""
        config, channel_id = self.config, channel_of(read)
        if self.jobs is None:                      # no background work
            return ""
        if latest_build is None and tables.is_joinable(conn, channel_id, self.get_hidden_sessions(conn, types, channel_id).is_in_shown_group):
            return "join" if self.start_build(conn, read, tables.JOIN) is not None else ""
        if latest_build and latest_build["status"] == "running" and time.time() - latest_build["started_at"] < config.build_timeout:
            return "build" if over_limit else ""
        if latest_build and latest_build["status"] == "ready" and (not in_use or latest_build["build_id"] != in_use["build_id"]):
            return ""
        if not over_limit and self.get_provider_count(size) < config.min_context_tokens and not config.build_every_request:
            return ""
        if over_limit or config.build_every_request:
            return "build" if self.start_build(conn, read, tables.LIMIT if over_limit else tables.REQUEST) is not None else ""
        if not config.check_boundaries:
            return ""
        if in_use:
            since_row = in_use["open_from_row"] - 1
        elif latest_build and latest_build["status"] in ("failed", "nothing"):
            since_row = latest_build["through_row"] or 0
        else:
            since_row = 0
        into_task = sum(1 for row in rows if row.row_id > since_row and history.opens_turn(row, types, self.groups))
        # a build a reader asked for, made mid-task, may have moved the running task's start (and so the
        # cooldown's count): the first user message after it is asked about all the same, so a change of
        # topic gets a build of its own -- its ranking made for the new request, not for the old one
        after_asked = bool(in_use) and in_use.get("reason") == tables.ASKED \
            and not tables.has_checked_since(conn, channel_id, in_use.get("through_row") or 0)
        if into_task <= config.boundary_cooldown and not after_asked:
            return ""
        row_id = rows[-1].row_id
        if not tables.claim_boundary(conn, row_id, channel_id):
            return ""
        try:
            self.jobs.start(read.gatherer_id, channel.of(channel_id), "check", row_id)
        except OSError as exc:
            tables.record_boundary(conn, row_id, False, f"could not start the worker: {exc}", channel_id)
            return ""
        return "check"

    def rebuild_for_new_group(self, conn, types: TypeIds, read: Read, rows, latest_build, in_use) -> bool:
        """After a change of the channel's group (`has_group_changed`): its sections built again from its group's work, and
        waited for (up to build_timeout) -- a `join` again, for a channel whose context came from one, or that has no
        build and can join its new group (`tables.is_joinable`); a `regrouped` build, for one with a build of its own in
        use. Whether one is ready; nothing is started without background work, or while a build runs."""
        config, channel_id = self.config, channel_of(read)
        if self.jobs is None:
            return False
        joining = tables.is_join(in_use) or (in_use is None and latest_build is None)
        if joining and not tables.is_joinable(conn, channel_id, self.get_hidden_sessions(conn, types, channel_id).is_in_shown_group):
            return False
        if not joining and in_use is None:          # a build of its own, not taken up yet: adopted at its user message
            return False
        reason = tables.JOIN if joining else tables.REGROUPED
        build_id = self.start_build(conn, read, reason)
        if build_id is None:
            return False
        self.log(f"[{channel_id}] its group changed: a {reason} build ({build_id})")
        return self.wait_for_build(conn, channel_id, rows[-1].row_id, "build", config.build_timeout, read.stopped)

    # ---- the worker's jobs

    def build(self, gatherer_id: str, properties, build_id: int) -> Optional[dict]:
        """The build: segmentation, the summaries of the newly finished
        tasks, a ranking of every earlier task. Kept in `tasks` and on the
        build (tables.py). A build started because the context was over
        max_context_tokens (reason `limit`) closes the running task at the
        last user message: what came before is finished and summarised, and
        that message starts the running task (`get_limit_build_tasks`). Within the
        limit the channel's harness stated last (`use_limit`). One that raises
        is settled `failed` first (`record_failure`)."""
        try:
            conn = self.gatherers.open(gatherer_id)
            try:
                last_read = conn.last_read(channel.of(channel_of(properties)))
            finally:
                conn.close()
            self.drift = self.get_provider_drift(last_read)
            with self.use_limit((last_read or {}).get("limit_tokens")):
                return self.run_build(gatherer_id, properties, build_id)
        except Exception as exc:
            self.record_failure(gatherer_id, properties, "build", build_id, exc)
            raise

    def run_build(self, gatherer_id: str, properties, build_id: int) -> Optional[dict]:
        channel_id = channel_of(properties)
        config, tokenizer, groups = self.config, self.tokenizer, self.groups
        conn = self.gatherers.open(gatherer_id)
        try:
            types = TypeIds.load(conn)
            rows = history.rows(conn, types, groups, channel_id)
            through_row = rows[-1].row_id if rows else 0
            parallel_mark = conn.high_water()
            preamble, turns = history.split(rows, types, groups, tokenizer)
            reason = (tables.get_build(conn, build_id) or {}).get("reason")
            if reason == tables.JOIN:
                return self.run_join(conn, types, channel_id, turns, build_id, through_row, parallel_mark)
            limit = reason in (tables.LIMIT, tables.COMPACTION)
            if limit:
                if not turns:
                    return self.settle_empty(conn, build_id, through_row, "no turns")
                tasks, failed, fresh = self.get_limit_build_tasks(conn, channel_id, turns)
            else:
                # one turn, or one task, is built only when it is over the limit: a cut inside it is then due --
                # all the model gets, with what the harness sends besides it (as its last call stated)
                fixed_tokens = (conn.last_read(channel.of(channel_id)) or {}).get("fixed_tokens") or 0
                oversized = self.get_provider_count(sum(row.tokens for row in rows) + fixed_tokens) > config.max_context_tokens
                if len(turns) < 2 and not oversized:
                    return self.settle_empty(conn, build_id, through_row, "fewer than two turns")
                tasks, failed, fresh = segmentation.update(turns, tables.get_tasks(conn, channel_id), self.llm,
                                                           config.segmentation, tokenizer)
            if failed:
                tables.fail_build(conn, build_id, "segmentation: no model call answered", through_row=through_row)
                return None
            for i, task in enumerate(tasks):
                task.channel_id, task.task_index = channel_id, i
            if not limit and len(tasks) < 2 and not (tasks and oversized):
                tables.save_tasks(conn, channel_id, tasks)
                return self.settle_empty(conn, build_id, through_row, "fewer than two tasks")
            with ThreadPoolExecutor(max_workers=1) as pool:
                summaries = pool.submit(summarize.summarize, fresh, turns, self.llm, config.summarizing) if fresh else None
                candidates = list(tasks[:-2])
                if config.parallel_related_tasks:
                    candidates += self.get_other_sessions_tasks(conn, types, channel_id)[0]
                ranked = ranking.rank(candidates, ranking.rank_target(turns, config.ranking), self.llm, config.ranking,
                                      own_channel=channel_id, top_n=len(candidates)) if candidates else []
                if summaries:
                    summaries.result()
            tables.save_cleaned(conn, build_id, get_cleaned_requests(fresh, turns))
            tables.save_tasks(conn, channel_id, tasks)
            tables.settle_build(conn, build_id, "ready", through_row=through_row, open_from_row=tasks[-1].first_row,
                          ranking=[(tables.get_channel_key(task.channel_id), task.task_index) for task in ranked], parallel_mark=parallel_mark)
            return tables.get_build(conn, build_id)
        finally:
            conn.close()

    def run_join(self, conn, types: TypeIds, channel_id, turns, build_id: int, through_row: int,
                   parallel_mark: int) -> Optional[dict]:
        """A channel's join: no segmentation -- its own history is all the running task -- and the
        other channels' tasks ranked against it (when parallel_related_tasks), their requests up to
        `parallel_mark` seen. Its tasks are not saved: the channel's first build of its own segments from
        nothing."""
        config = self.config
        if not turns:
            return self.settle_empty(conn, build_id, through_row, "no turns")
        candidates = self.get_other_sessions_tasks(conn, types, channel_id)[0] if config.parallel_related_tasks else []
        ranked = ranking.rank(candidates, ranking.rank_target(turns, config.ranking), self.llm, config.ranking,
                              own_channel=channel_id, top_n=len(candidates)) if candidates else []
        tables.settle_build(conn, build_id, "ready", through_row=through_row, open_from_row=turns[0].first_row,
                      ranking=[(tables.get_channel_key(task.channel_id), task.task_index) for task in ranked], parallel_mark=parallel_mark)
        return tables.get_build(conn, build_id)

    def get_limit_build_tasks(self, conn, channel_id, turns) -> Tuple[List, bool, List]:
        """(the tasks, whether segmentation failed, the tasks to summarise) of a `limit` build: the
        last user message starts the running task, CURRENT_REQUEST, and everything before it is
        finished. Segmentation is given only the turns before it, so it names and describes tasks
        from exactly the turns they cover; the last task it returns -- open in its view -- is closed
        here and summarised with the others it finished. A second limit build in the same turn finds
        the running task already starting there and segments nothing again."""
        last_turn = turns[-1]
        current = history.Task(CURRENT_REQUEST, last_turn.user_text.strip()[:200], last_turn.first_row, last_turn.last_row,
                               last_turn.index, last_turn.index)
        stored = tasks_tool.locate(tables.get_tasks(conn, channel_id), turns)
        if len(turns) == 1:
            return [current], False, []
        if stored and stored[-1].first_row == last_turn.first_row:      # an earlier limit build in this turn
            return stored[:-1] + [current], False, []
        tasks, failed, fresh = segmentation.update(turns[:-1], tables.get_tasks(conn, channel_id), self.llm,
                                                   self.config.segmentation, self.tokenizer)
        if failed:
            return tasks, True, fresh
        if tasks and all(task is not tasks[-1] for task in fresh):
            fresh = fresh + [tasks[-1]]                            # finished now: summarised with the rest
        return tasks + [current], False, fresh

    def settle_empty(self, conn, build_id: int, through_row: int, why: str) -> None:
        tables.settle_build(conn, build_id, "nothing", through_row=through_row, error=why)
        self.log(f"no build: {why}")
        return None

    def check(self, gatherer_id: str, properties, row_id: int) -> bool:
        """The boundary tool's verdict on the user message `row_id`, recorded;
        on a yes, a build is claimed and run; no usable answer counts as a
        no. Returns what was decided. One that raises has its verdict recorded
        as "no" first (`record_failure`)."""
        try:
            return self.run_check(gatherer_id, properties, row_id)
        except Exception as exc:
            self.record_failure(gatherer_id, properties, "check", row_id, exc)
            raise

    def run_check(self, gatherer_id: str, properties, row_id: int) -> bool:
        channel_id = channel_of(properties)
        config, tokenizer, groups = self.config, self.tokenizer, self.groups
        conn = self.gatherers.open(gatherer_id)
        try:
            types = TypeIds.load(conn)
            rows = history.rows(conn, types, groups, channel_id)
            _, turns = history.split(rows, types, groups, tokenizer)
            stored = tasks_tool.locate(tables.get_tasks(conn, channel_id), turns)
            open_from = stored[-1].first_row if stored else (turns[0].first_row if turns else 0)
            open_turns = [turn for turn in turns if turn.first_row >= open_from]
            if len(open_turns) > 1:
                verdict, why = boundary.is_new_task(open_turns, stored[:-1], turns, self.llm, config.boundary)
                if verdict is None:
                    verdict, why = False, f"{why}; treated as a continuation"
            else:
                verdict, why = False, "first turn of the open task"
            tables.record_boundary(conn, row_id, verdict, why, channel_id)
            if not verdict:
                return False
            build_id = tables.claim_build(conn, channel_id, config.build_timeout, tables.BOUNDARY)
        finally:
            conn.close()
        if build_id is not None:
            self.build(gatherer_id, channel.of(channel_id), build_id)
        return True

    def bulk_loaded(self, conn, gatherer_id: str, properties) -> Any:
        return self.build(gatherer_id, properties, tables.create_build(conn, channel_of(properties)))
