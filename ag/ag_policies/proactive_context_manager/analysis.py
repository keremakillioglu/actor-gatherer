"""What a build computes, in the worker: segmentation, the summaries of the newly finished tasks and a ranking of
every earlier task, kept in `tasks` and on the build (tables.py) -- or, for a join, only a ranking of the other
sessions' tasks. And the boundary check: whether a user message starts a new task. The worker calls `build` and
`check`, the job names builds.py starts them under; one that raises records what its failure leaves behind
itself (`record_failure`), and the worker only logs it."""

from concurrent.futures import ThreadPoolExecutor
from typing import Any, List, Optional, Tuple

from ag.ag_interface.policy import TypeIds
from ag.ag_policies.tools import boundary, channel, history, ranking, segmentation, summarize
from ag.ag_policies.tools import tasks as tasks_tool
from ag.ag_policies.tools.channel import channel_of
from . import tables
from .context_limit import ContextLimit
from .session_groups import SessionGroups

CURRENT_REQUEST = "Current request"   # the running task a `limit` build starts at the last user message


def get_cleaned_requests(tasks, turns) -> dict:
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


class Analysis(ContextLimit, SessionGroups):

    def build(self, gatherer_id: str, properties, build_id: int) -> Optional[dict]:
        """The analysis: segmentation, the summaries of the newly finished
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
                last = conn.last_read(channel.of(channel_of(properties)))
            finally:
                conn.close()
            self.drift = self.get_provider_drift(last)
            with self.use_limit((last or {}).get("limit_tokens")):
                return self.run_build(gatherer_id, properties, build_id)
        except Exception as exc:
            self.record_failure(gatherer_id, properties, "build", build_id, exc)
            raise

    def run_build(self, gatherer_id: str, properties, build_id: int) -> Optional[dict]:
        channel_id = channel_of(properties)
        cfg, tok, groups = self.config, self.tokenizer, self.groups
        conn = self.gatherers.open(gatherer_id)
        try:
            types = TypeIds.load(conn)
            rows = history.rows(conn, types, groups, channel_id)
            through_row = rows[-1].row_id if rows else 0
            mark = conn.high_water()
            preamble, turns = history.split(rows, types, groups, tok)
            reason = (tables.get_build(conn, build_id) or {}).get("reason")
            if reason == tables.JOIN:
                return self.run_join(conn, types, channel_id, turns, build_id, through_row, mark)
            limit = reason in (tables.LIMIT, tables.COMPACTION)
            if limit:
                if not turns:
                    return self.settle_empty(conn, build_id, through_row, "no turns")
                tasks, failed, fresh = self.get_limit_build_tasks(conn, channel_id, turns)
            else:
                # one turn, or one task, is built only when it is over the limit: a cut inside it is then due --
                # all the model gets, with what the harness sends besides it (as its last call stated)
                fixed = (conn.last_read(channel.of(channel_id)) or {}).get("fixed_tokens") or 0
                oversized = self.get_provider_count(sum(r.tokens for r in rows) + fixed) > cfg.max_context_tokens
                if len(turns) < 2 and not oversized:
                    return self.settle_empty(conn, build_id, through_row, "fewer than two turns")
                tasks, failed, fresh = segmentation.update(turns, tables.get_tasks(conn, channel_id), self.llm,
                                                           cfg.segmentation, tok)
            if failed:
                tables.fail_build(conn, build_id, "segmentation: no model call answered", through_row=through_row)
                return None
            for i, t in enumerate(tasks):
                t.channel_id, t.task_index = channel_id, i
            if not limit and len(tasks) < 2 and not (tasks and oversized):
                tables.save_tasks(conn, channel_id, tasks)
                return self.settle_empty(conn, build_id, through_row, "fewer than two tasks")
            with ThreadPoolExecutor(max_workers=1) as pool:
                summaries = pool.submit(summarize.summarize, fresh, turns, self.llm, cfg.summarizing) if fresh else None
                candidates = list(tasks[:-2])
                if cfg.parallel_related_tasks:
                    candidates += self.get_other_sessions_tasks(conn, types, channel_id)[0]
                ranked = ranking.rank(candidates, ranking.rank_target(turns, cfg.ranking), self.llm, cfg.ranking,
                                      own_channel=channel_id, top_n=len(candidates)) if candidates else []
                if summaries:
                    summaries.result()
            tables.save_cleaned(conn, build_id, get_cleaned_requests(fresh, turns))
            tables.save_tasks(conn, channel_id, tasks)
            tables.settle_build(conn, build_id, "ready", through_row=through_row, open_from_row=tasks[-1].first_row,
                          ranking=[(tables.get_channel_key(t.channel_id), t.task_index) for t in ranked], parallel_mark=mark)
            return tables.get_build(conn, build_id)
        finally:
            conn.close()

    def run_join(self, conn, types: TypeIds, channel_id, turns, build_id: int, through_row: int,
                   mark: int) -> Optional[dict]:
        """A channel's join: no segmentation -- its own history is all the running task -- and the
        other channels' tasks ranked against it (when parallel_related_tasks), their requests up to
        `mark` seen. Its tasks are not saved: the channel's first build of its own segments from
        nothing."""
        cfg = self.config
        if not turns:
            return self.settle_empty(conn, build_id, through_row, "no turns")
        candidates = self.get_other_sessions_tasks(conn, types, channel_id)[0] if cfg.parallel_related_tasks else []
        ranked = ranking.rank(candidates, ranking.rank_target(turns, cfg.ranking), self.llm, cfg.ranking,
                              own_channel=channel_id, top_n=len(candidates)) if candidates else []
        tables.settle_build(conn, build_id, "ready", through_row=through_row, open_from_row=turns[0].first_row,
                      ranking=[(tables.get_channel_key(t.channel_id), t.task_index) for t in ranked], parallel_mark=mark)
        return tables.get_build(conn, build_id)

    def get_limit_build_tasks(self, conn, channel_id, turns) -> Tuple[List, bool, List]:
        """(the tasks, whether segmentation failed, the tasks to summarise) of a `limit` build: the
        last user message starts the running task, CURRENT_REQUEST, and everything before it is
        finished. Segmentation is given only the turns before it, so it names and describes tasks
        from exactly the turns they cover; the last task it returns -- open in its view -- is closed
        here and summarised with the others it finished. A second limit build in the same turn finds
        the running task already starting there and segments nothing again."""
        last = turns[-1]
        current = history.Task(CURRENT_REQUEST, last.user_text.strip()[:200], last.first_row, last.last_row,
                               last.index, last.index)
        stored = tasks_tool.locate(tables.get_tasks(conn, channel_id), turns)
        if len(turns) == 1:
            return [current], False, []
        if stored and stored[-1].first_row == last.first_row:      # an earlier limit build in this turn
            return stored[:-1] + [current], False, []
        tasks, failed, fresh = segmentation.update(turns[:-1], tables.get_tasks(conn, channel_id), self.llm,
                                                   self.config.segmentation, self.tokenizer)
        if failed:
            return tasks, True, fresh
        if tasks and all(t is not tasks[-1] for t in fresh):
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
        cfg, tok, groups = self.config, self.tokenizer, self.groups
        conn = self.gatherers.open(gatherer_id)
        try:
            types = TypeIds.load(conn)
            rows = history.rows(conn, types, groups, channel_id)
            _, turns = history.split(rows, types, groups, tok)
            stored = tasks_tool.locate(tables.get_tasks(conn, channel_id), turns)
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

    def record_failure(self, gatherer_id: str, properties, job: str, job_id: int, exc: Exception) -> None:
        """What a job leaves behind when it raises, so no claim stays held: a build is settled `failed`, a
        check's verdict is "no". Never raises itself: the job's own error is the one that goes on."""
        error = f"{type(exc).__name__}: {exc}"
        try:
            conn = self.gatherers.open(gatherer_id)
            try:
                if job == "build":
                    tables.fail_build(conn, job_id, error)
                elif job == "check":
                    tables.record_boundary(conn, job_id, False, f"check failed: {error}", channel_of(properties))
            finally:
                conn.close()
        except Exception as inner:  # noqa: BLE001 - the job's own error is the one to report
            self.log(f"{job} {job_id}: its failure could not be recorded: {inner!r}")

    def bulk_loaded(self, conn, gatherer_id: str, properties) -> Any:
        return self.build(gatherer_id, properties, tables.create_build(conn, channel_of(properties)))
