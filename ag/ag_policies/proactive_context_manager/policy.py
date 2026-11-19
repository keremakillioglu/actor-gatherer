"""The proactive context manager: earlier history as sections built in the
background, aware of what happens outside the conversation and of the
requests the user makes to the session's other channels.

Every context opens, after the harness's own set-up, with the GATHERER GUIDE
(`gatherer_guide`, `sections.guide`): what ag adds to the context -- the sections, the
parallel requests, notices, stream messages, left-out notes -- and where the full history
is. On every read, with or without a build; one made item, the same while its text is.

The package, in three folders beside this file:

    core/    the context management itself: assembly.py (one read), summaries.py (what gets summarized, and
             when), sections.py, parallel_sessions.py, external_events.py and prompts.py
    utils/   what it runs on: tokens.py (counting as the provider does), jobs.py (background work)
    db/      what it keeps: tables.py, report.py

and config.py (what can be tuned) and events.py (the event types it expects).
"""

from typing import Dict, Optional

from ag.ag_interface import LLM, Format, Tokenizer
from ag.ag_interface.policy import Context, Policy, Read, TypeIds
from ag.ag_policies.tools import channel, history
from ag.ag_policies.tools.channel import channel_of
from ag.ag_policies.tools.options import config_from
from .config import ProactiveContextManagerConfig
from .core.assembly import Assembly, Draft
from .db import tables
from .events import EVENT_TYPES


class ProactiveContextManager(Assembly, Policy):
    """The policy: its parts' methods (core/assembly.py's `Assembly` takes in every other part), then `Policy`'s
    defaults for whatever no part defines (hence `Policy` last)."""

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
        self.drift = 1.0                            # get_provider_count's, set for each read and each build

    @property
    def groups(self):
        return self.config.groups

    def init(self, conn) -> None:
        """`tasks`, `_builds` and `_boundaries` (tables.py), if absent."""
        tables.create(conn)

    def append(self, conn, db: str, offset: int) -> None:
        """Another gatherer's tables appended (Policy.append; tables.append)."""
        tables.append(conn, db, offset)

    def read(self, conn, read: Read) -> Context:
        """The context for the channel's next model call: the sectioned
        context, with the stream messages of the verbatim part shown where
        they arrived, and a notice for every environment update the
        verbatim part refers to. Within the harness's own limit, when the
        call states one (`use_limit`)."""
        with self.use_limit(read.limit):
            cfg, ch = self.config, channel_of(read)
            types = TypeIds.load(conn)
            rows = history.rows(conn, types, self.groups, ch)
            if not rows:
                return Context()
            at_user = history.opens_turn(rows[-1], types, self.groups)
            latest = tables.get_latest_build(conn, ch)
            last = conn.last_read(channel.of(ch))
            self.drift = self.get_provider_drift(last)
            draft = self.draft_context(conn, types, rows, latest, last, at_user or self.is_build_for_this_turn(latest, rows, types), read)
            if last and self.has_group_changed(conn, types, ch, last.get("row_id") or 0) \
                    and self.rebuild_for_new_group(conn, types, read, rows, latest, draft.build):
                latest = tables.get_latest_build(conn, ch)
                draft = self.draft_context(conn, types, rows, latest, last, True, read)
            over = self.is_over_limit(draft.size, last, draft.build, ch)
            if over and not at_user and tables.is_waiting(latest, last):        # a ready build: taken now, not at the user
                draft = self.draft_context(conn, types, rows, latest, last, True, read)
                over = self.is_over_limit(draft.size, last, draft.build, ch)
            if at_user or over:
                latest = tables.get_latest_build(conn, ch)
                started = self.start_due_work(conn, types, read, rows, latest, draft.build, draft.size, over)
                # over the limit, or joining, the read waits for its build however long it takes (up to build_timeout)
                seconds = cfg.build_timeout if (over and started == "build") or started == "join" else cfg.sync_seconds
                if started and seconds > 0 and self.wait_for_build(conn, ch, rows[-1].row_id, started, seconds, read.stopped):
                    latest = tables.get_latest_build(conn, ch)
                    draft = self.draft_context(conn, types, rows, latest, last, True, read)
            if self.get_provider_count(draft.size) > cfg.max_context_tokens:   # still over: the steps that do not fit, left out
                draft = Draft(draft.build, draft.made, *self.assemble_context(conn, rows, draft.build, draft.made, types, read, stub=True))
            if self.get_provider_count(draft.size) > cfg.max_context_tokens:
                self.log(f"[{ch}] context {draft.size} tokens ({self.get_provider_count(draft.size)} as the provider counts), "
                         f"over max_context_tokens={cfg.max_context_tokens}")
            self.last_tokens = draft.own                    # the part of it the policy arranges
            return Context(draft.items, draft.refs, str(draft.build["build_id"]) if draft.build else None, tokens=draft.own,
                           budget=cfg.max_context_tokens)
