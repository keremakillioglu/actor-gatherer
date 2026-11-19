"""Running builds and checks in the background: claiming one (a session has one at a time), starting the worker
(`start_worker`), waiting for it (`wait_for_build`), a build asked for from outside a read (`request_build`), and what
a job that raises leaves behind (`record_failure`). What a build and a check compute, and when one is started, is
core/summaries.py's."""

import time
from typing import Callable, Optional

from ag.ag_interface.policy import COMPACTION, READER, Read, TypeIds
from ag.ag_policies.tools import channel, history
from ag.ag_policies.tools.channel import channel_of
from ..db import tables
from .tokens import Tokens


class BackgroundJobs(Tokens):

    def request_build(self, conn, read: Read, why: str, *, wait: bool = False, min_messages: int = 0) -> dict:
        """Build now, asked from outside a read (`Policy.request_build`), within the harness's own limit when the
        call states one (`use_limit`):

        - COMPACTION: the harness compacted its own history (Claude Code's /compact, or its own at its limit) --
          a `compaction` build, which closes the running task as one over the limit does, and is adopted at the
          next read whatever its size (`start_compaction_build`).
        - READER: a reader outside any call (the dashboard's History view) -- an ordinary build, once the channel
          has at least `min_messages` user messages its builds have not gone through (`start_reader_build`).

        With `wait`, until the build settles, up to build_timeout. What came of it: {"started": build_id, ...},
        with its "status" ("ready", "failed", "nothing" or "timeout") when waited for; or what the start came to
        instead (`start_compaction_build`, `start_reader_build`); {} with no background work, or for a `why` it
        does not know."""
        with self.use_limit(read.limit):
            if self.jobs is None:
                return {}
            if why == COMPACTION:
                outcome = self.start_compaction_build(conn, read)
            elif why == READER:
                outcome = self.start_reader_build(conn, read, min_messages)
            else:
                return {}
            if wait and "started" in outcome:
                self.wait_for_build(conn, channel_of(read), read.row_id, "build", self.config.build_timeout,
                                    read.stopped)
                status = (tables.get_build(conn, outcome["started"]) or {}).get("status")
                outcome["status"] = status if status in ("ready", "failed", "nothing") else "timeout"
            return outcome

    def start_compaction_build(self, conn, read: Read) -> dict:
        """A `compaction` build started: {"started": build_id}. One already running is waited for first, then
        built again: {"status": "timeout"} when it does not finish in time (or the harness gives up on the
        call); {"failed": why} when the worker cannot be started."""
        config, channel_id = self.config, channel_of(read)
        build_id = tables.claim_build(conn, channel_id, config.build_timeout, tables.COMPACTION)
        if build_id is None:                    # one is running: let it finish, then build again
            self.wait_for_build(conn, channel_id, read.row_id, "build", config.build_timeout, read.stopped)
            build_id = None if read.stopped() else \
                tables.claim_build(conn, channel_id, config.build_timeout, tables.COMPACTION)
        if build_id is None:
            return {"status": "timeout"}
        failed = self.start_worker(conn, read, build_id)
        return {"failed": failed} if failed is not None else {"started": build_id}

    def start_reader_build(self, conn, read: Read, min_messages: int = 0) -> dict:
        """An ordinary build (reason `asked`) started for a reader, not waited for -- once the channel has at
        least `min_messages` user messages since the last its builds went through (since its start, before any)
        -- a join aside: it splits nothing of the channel's own history. Adopted as any build is: at the
        channel's next user message. What came of it: {"started": build_id, "messages": n}; {"running":
        build_id}, one already is; {"few": n}, only n such messages since; {"failed": why}."""
        config, channel_id = self.config, channel_of(read)
        latest_build = tables.get_own_latest_build(conn, channel_id)
        if latest_build and latest_build["status"] == "running" and time.time() - latest_build["started_at"] < config.build_timeout:
            return {"running": latest_build["build_id"]}
        types = TypeIds.load(conn)
        built_through = conn.execute("SELECT max(through_row) FROM _builds WHERE channel_key = ? AND coalesce(reason, '') != ?",
                             (tables.get_channel_key(channel_id), tables.JOIN)).fetchone()[0] or 0
        new_messages = sum(1 for row in history.rows(conn, types, self.groups, channel_id)
                if row.row_id > built_through and history.opens_turn(row, types, self.groups))
        if new_messages < min_messages:
            return {"few": new_messages}
        build_id = tables.claim_build(conn, channel_id, config.build_timeout, tables.ASKED)
        if build_id is None:                         # another started one meanwhile
            return {"running": (tables.get_own_latest_build(conn, channel_id) or {}).get("build_id")}
        failed = self.start_worker(conn, read, build_id)
        if failed is not None:
            return {"failed": failed}
        self.log(f"[{channel_id}] build {build_id} asked for, {new_messages} user messages since the last")
        return {"started": build_id, "messages": new_messages}

    def start_build(self, conn, read: Read, reason: str) -> Optional[int]:
        """A build of the read's channel claimed for `reason` and started in the worker: its id, or None --
        one is running already (`tables.claim_build`), or the worker could not be started (`start_worker`)."""
        build_id = tables.claim_build(conn, channel_of(read), self.config.build_timeout, reason)
        if build_id is None or self.start_worker(conn, read, build_id) is not None:
            return None
        return build_id

    def start_worker(self, conn, read: Read, build_id: int) -> Optional[str]:
        """The claimed build `build_id` started in the worker: None, or why it could not be (the build is then
        settled `failed`)."""
        try:
            self.jobs.start(read.gatherer_id, channel.of(channel_of(read)), "build", build_id)
        except OSError as exc:
            tables.fail_build(conn, build_id, f"could not start the worker: {exc}")
            return str(exc)
        return None

    def wait_for_build(self, conn, channel_id, row_id: int, started_work: str, wait_seconds: float,
             stopped: Callable[[], bool] = lambda: False) -> bool:
        """Whether the build the read started (or the one its check found a new task for) is ready
        within `wait_seconds` -- for a check that finds a new task, within build_wait_seconds, if longer:
        the check answers in seconds, the build it starts takes tens of them. Not once the harness has
        given up on the call (`stopped`: its user pressed Esc): nothing will be sent, so the read goes on
        without it at once -- the check and the build carry on in the background."""
        begun = time.monotonic()
        deadline = begun + wait_seconds
        started_work = "build" if started_work == "join" else started_work
        while True:
            if stopped():
                self.log(f"[{channel_id}] the harness hung up on the call: not waiting for the {started_work} "
                         f"({time.monotonic() - begun:.1f} s in)")
                return False
            if started_work == "check":
                verdict = tables.get_boundary_verdict(conn, row_id)
                if verdict and verdict["new_task"] is False:
                    return False
                if verdict and verdict["new_task"] is True:
                    started_work = "build"
                    deadline = max(deadline, begun + self.config.build_wait_seconds)
            if started_work == "build":
                build = tables.get_own_latest_build(conn, channel_id)
                if build and build["status"] == "ready":
                    return True
                if build and build["status"] in ("failed", "nothing"):
                    return False
            if time.monotonic() >= deadline:
                return False
            time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))

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
