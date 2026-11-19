"""Builds, as a read sees them: when one is started and how long the read waits for it, which build a read uses,
and how a ready one is laid out as the history sections (adopted). What a build computes, in the worker, is
analysis.py's.

A channel with no build of its own, in a gatherer where another channel has a ready one
(`tables.joinable`), JOINS at its first user message: a `join` build ranks the other
channels' tasks against its request and marks their requests as seen, and the read waits
for it. Its sections are the other channels' requests and related tasks, its own history
all the running task, verbatim -- so a new session starts from what the gatherer's others
did, and their requests before the mark are an index within its budget, not a message each.

A user message the boundary check finds starts a new task gets its build: the read waits
for it up to build_wait_seconds. One that takes longer is taken up at the turn's next call
(`is_build_for_this_turn`), not left for the next user message: the turn itself stays verbatim, so
the switch replaces only the history before it."""

import time
from typing import Callable, List, Optional, Tuple

from ag.ag_interface.policy import Read, TypeIds
from ag.ag_policies.tools import channel, history
from ag.ag_policies.tools import tasks as tasks_tool
from ag.ag_policies.tools.channel import channel_of
from . import layout, tables
from .analysis import CURRENT_REQUEST
from .context_limit import ContextLimit
from .gatherer_messages import REMADE_EVERY_READ
from .session_groups import SessionGroups


class Builds(ContextLimit, SessionGroups):

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
        used = tables.basis_of(last_read)
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
        """Lay `build`'s analysis out as sections and store them as made
        items; None (and the build settled `nothing`) if they would not be
        smaller than the history they replace."""
        cfg, tok, groups, ch = self.config, self.tokenizer, self.groups, channel_of(read)
        _, turns = history.split(rows, types, groups, tok)
        tables.apply_cleaned_texts(conn, [t.entries[0] for t in turns])
        joining = tables.is_join(build)
        if joining:                                  # its own history, all of it, is the running task
            tasks = [self.get_join_task(turns, ch)] if turns else []
        else:
            tasks = tasks_tool.locate(tables.tasks_for(conn, ch), turns)
        if not tasks:
            tables.settle(conn, build["build_id"], "nothing", error="no tasks at adoption")
            return None
        foreign, turns_by_channel = self.get_other_sessions_tasks(conn, types, ch, read.stopped)
        if read.stopped():                           # the harness hung up meanwhile (Esc): laid out at the next read
            return None
        turns_by_channel[ch] = turns
        before = tasks[:-2]
        earlier = layout.earlier_messages(before, turns, cfg, tok)
        shown = {id(before[i]) for i in earlier[1]}
        by_key = {(tables.key(t.channel_id), t.task_index): t for t in before + foreign}
        ranked = [by_key[tuple(k)] for k in build["ranking"] if tuple(k) in by_key]
        ranked = [t for t in ranked if id(t) not in shown]
        mark = build["parallel_mark"]
        unseen = self.get_hidden_sessions(conn, types, ch)
        others = [(c, e) for c, e in history.other_requests(conn, types, groups, tok, ch,
                                                            keep=lambda r: channel_of(r) not in unseen and self.is_user_request(r))
                  if e.row_id <= mark]
        tables.apply_cleaned_texts(conn, [e for _, e in others])
        sections = layout.build_sections(turns, tasks, ranked, earlier, others, turns_by_channel, ch, cfg, tok,
                                         conn.path, build["through_row"], mark, joined=joining)
        cut = self.get_verbatim_start(rows, types, tasks[-1], sections, conn.path, read.fixed_tokens, joining)
        if cut != sections.open_from_row:
            sections = layout.build_sections(turns, tasks, ranked, earlier, others, turns_by_channel, ch, cfg, tok,
                                             conn.path, build["through_row"], mark, cut_row=cut, joined=joining)
        if not joining and len(tasks) < 2 and sections.open_from_row == tasks[-1].first_row:
            tables.settle(conn, build["build_id"], "nothing", error="fewer than two tasks, and no cut inside the one")
            return None
        if sections.open_from_row != build["open_from_row"]:
            tables.set_cut(conn, build["build_id"], sections.open_from_row)
        # compacted: not sent whole again; joined: the sections replace nothing of its own, they add the others' work;
        # regrouped: they replace sections made from another group's work
        if cfg.require_smaller and build.get("reason") not in (tables.COMPACTION, tables.JOIN, tables.REGROUPED):
            why = self.get_not_smaller_reason(sections, rows, turns, types)
            if why:
                tables.settle(conn, build["build_id"], "nothing", error=why)
                self.log(f"build {build['build_id']} not adopted: {why}")
                return None
        source = f"build {build['build_id']}"
        made = [conn.make_item(self.format.make_section(text, name), tok, properties=channel.of(ch), name=name,
                               source=source)
                for name, text in sections.sections]
        return made

    @staticmethod
    def get_join_task(turns, channel_id) -> history.Task:
        """The one task of a channel that joined: all its turns, running."""
        first, last = turns[0], turns[-1]
        task = history.Task(CURRENT_REQUEST, first.user_text.strip()[:200], first.first_row, last.last_row,
                            first.index, last.index)
        task.channel_id = channel_id
        return task

    def get_not_smaller_reason(self, sections, rows, turns, types: TypeIds) -> Optional[str]:
        """Why `sections` are not worth adopting -- they are no smaller than the history they replace
        (require_smaller) -- or None."""
        pinned = types.of(*self.groups.pinned)
        replaced = sum(r.tokens for r in rows
                       if turns[0].first_row <= r.row_id < sections.open_from_row and r.type.id not in pinned)
        size = sum(self.tokenizer.count(text) for _, text in sections.sections)
        if size >= replaced:
            return f"sections ({size} tokens) not smaller than the history they replace ({replaced})"
        return None

    def start_due_work(self, conn, types: TypeIds, read: Read, rows, latest, in_use, size: int, over: bool = False) -> str:
        """Start what is due in the background: "build", "check", "join" or "" (the build thresholds) --
        at a user message, or at any read when the context is `over` max_context_tokens: a build then,
        or the one already running ("build", to wait for). A channel with no build at all (`latest`
        None: neither its own nor the no-channel pool's) joins, when another channel has one: a
        `join` build, whatever the context's size, which the read waits for."""
        cfg, ch = self.config, channel_of(read)
        if self.jobs is None:                      # no background work
            return ""
        if latest is None and tables.joinable(conn, ch, self.get_hidden_sessions(conn, types, ch).is_in_shown_group):
            return "join" if self.start_build(conn, read, tables.JOIN) is not None else ""
        if latest and latest["status"] == "running" and time.time() - latest["started_at"] < cfg.build_timeout:
            return "build" if over else ""
        if latest and latest["status"] == "ready" and (not in_use or latest["build_id"] != in_use["build_id"]):
            return ""
        if not over and self.get_provider_count(size) < cfg.min_context_tokens and not cfg.build_every_request:
            return ""
        if over or cfg.build_every_request:
            return "build" if self.start_build(conn, read, tables.LIMIT if over else tables.REQUEST) is not None else ""
        if not cfg.check_boundaries:
            return ""
        if in_use:
            since_row = in_use["open_from_row"] - 1
        elif latest and latest["status"] in ("failed", "nothing"):
            since_row = latest["through_row"] or 0
        else:
            since_row = 0
        into_task = sum(1 for r in rows if r.row_id > since_row and history.opens_turn(r, types, self.groups))
        # a build a reader asked for, made mid-task, may have moved the running task's start (and so the
        # cooldown's count): the first user message after it is asked about all the same, so a change of
        # topic gets a build of its own -- its ranking made for the new request, not for the old one
        after_asked = bool(in_use) and in_use.get("reason") == tables.ASKED \
            and not tables.checked_since(conn, ch, in_use.get("through_row") or 0)
        if into_task <= cfg.boundary_cooldown and not after_asked:
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

    def rebuild_for_new_group(self, conn, types: TypeIds, read: Read, rows, latest, in_use) -> bool:
        """After a change of the channel's group (`has_group_changed`): its sections built again from its group's work, and
        waited for (up to build_timeout) -- a `join` again, for a channel whose context came from one, or that has no
        build and can join its new group (`tables.joinable`); a `regrouped` build, for one with a build of its own in
        use. Whether one is ready; nothing is started without background work, or while a build runs."""
        cfg, ch = self.config, channel_of(read)
        if self.jobs is None:
            return False
        joining = tables.is_join(in_use) or (in_use is None and latest is None)
        if joining and not tables.joinable(conn, ch, self.get_hidden_sessions(conn, types, ch).is_in_shown_group):
            return False
        if not joining and in_use is None:          # a build of its own, not taken up yet: adopted at its user message
            return False
        reason = tables.JOIN if joining else tables.REGROUPED
        build_id = self.start_build(conn, read, reason)
        if build_id is None:
            return False
        self.log(f"[{ch}] its group changed: a {reason} build ({build_id})")
        return self.wait_for_build(conn, ch, rows[-1].row_id, "build", cfg.build_timeout, read.stopped)

    def compacted(self, conn, read: Read) -> str:
        """The harness compacted its own history (Claude Code's /compact, or its own at its limit): build
        now -- a `compaction` build, which closes the running task as one over the limit does, and is
        adopted at the next read whatever its size -- and wait for it, up to build_timeout. What it came
        to: "ready", "failed", "nothing", "timeout"; "" with no background work."""
        with self.use_limit(read.limit):
            cfg, ch = self.config, channel_of(read)
            if self.jobs is None:
                return ""
            build_id = tables.claim_build(conn, ch, cfg.build_timeout, tables.COMPACTION)
            if build_id is None:                    # one is running: let it finish, then build again
                self.wait_for_build(conn, ch, read.row_id, "build", cfg.build_timeout, read.stopped)
                build_id = None if read.stopped() else \
                    tables.claim_build(conn, ch, cfg.build_timeout, tables.COMPACTION)
            if build_id is None:
                return "timeout"
            if self.start_worker(conn, read, build_id) is not None:
                return "failed"
            self.wait_for_build(conn, ch, read.row_id, "build", cfg.build_timeout, read.stopped)
            build = tables.get_build(conn, build_id) or {}
            return build.get("status") if build.get("status") in ("ready", "failed", "nothing") else "timeout"

    def requested(self, conn, read: Read, min_messages: int = 0) -> dict:
        """A build a reader asked for from outside any call (the dashboard's History view): an ordinary
        build (reason `asked`), started in the background and not waited for -- once the channel has at
        least `min_messages` user messages since the last its builds went through (since its start,
        before any) -- a join aside: it splits nothing of the channel's own history. Adopted as any build is: at the channel's next user message. What came of it:
        {"started": build_id, "messages": n}; {"running": build_id}, one already is; {"few": n}, only n
        such messages since; {"failed": why}; {} with no background work."""
        cfg, ch = self.config, channel_of(read)
        if self.jobs is None:
            return {}
        latest = tables.latest_build(conn, ch)
        if latest and latest["status"] == "running" and time.time() - latest["started_at"] < cfg.build_timeout:
            return {"running": latest["build_id"]}
        types = TypeIds.load(conn)
        since = conn.execute("SELECT max(through_row) FROM _builds WHERE channel_key = ? AND coalesce(reason, '') != ?",
                             (tables.key(ch), tables.JOIN)).fetchone()[0] or 0
        n = sum(1 for r in history.rows(conn, types, self.groups, ch)
                if r.row_id > since and history.opens_turn(r, types, self.groups))
        if n < min_messages:
            return {"few": n}
        build_id = tables.claim_build(conn, ch, cfg.build_timeout, tables.ASKED)
        if build_id is None:                         # another started one meanwhile
            return {"running": (tables.latest_build(conn, ch) or {}).get("build_id")}
        failed = self.start_worker(conn, read, build_id)
        if failed is not None:
            return {"failed": failed}
        self.log(f"[{ch}] build {build_id} asked for, {n} user messages since the last")
        return {"started": build_id, "messages": n}

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

    def wait_for_build(self, conn, channel_id, row_id: int, started: str, seconds: float,
             stopped: Callable[[], bool] = lambda: False) -> bool:
        """Whether the build the read started (or the one its check found a new task for) is ready
        within `seconds` -- for a check that finds a new task, within build_wait_seconds, if longer:
        the check answers in seconds, the build it starts takes tens of them. Not once the harness has
        given up on the call (`stopped`: its user pressed Esc): nothing will be sent, so the read goes on
        without it at once -- the check and the build carry on in the background."""
        begun = time.monotonic()
        deadline = begun + seconds
        started = "build" if started == "join" else started
        while True:
            if stopped():
                self.log(f"[{channel_id}] the harness hung up on the call: not waiting for the {started} "
                         f"({time.monotonic() - begun:.1f} s in)")
                return False
            if started == "check":
                verdict = tables.boundary_verdict(conn, row_id)
                if verdict and verdict["new_task"] is False:
                    return False
                if verdict and verdict["new_task"] is True:
                    started = "build"
                    deadline = max(deadline, begun + self.config.build_wait_seconds)
            if started == "build":
                build = tables.latest_build(conn, channel_id)
                if build and build["status"] == "ready":
                    return True
                if build and build["status"] in ("failed", "nothing"):
                    return False
            if time.monotonic() >= deadline:
                return False
            time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
