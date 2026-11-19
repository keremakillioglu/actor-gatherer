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
            config, channel_id = self.config, channel_of(read)
            types = TypeIds.load(conn)
            rows = history.rows(conn, types, self.groups, channel_id)
            if not rows:
                return Context()
            is_new_user_message = history.opens_turn(rows[-1], types, self.groups)
            latest_build = tables.get_latest_build(conn, channel_id)
            last_read = conn.last_read(channel.of(channel_id))
            self.drift = self.get_provider_drift(last_read)
            may_switch_build = is_new_user_message or self.is_build_for_this_turn(latest_build, rows, types)
            draft = self.draft_context(conn, types, rows, latest_build, last_read, may_switch_build, read)
            if last_read and self.has_group_changed(conn, types, channel_id, last_read.get("row_id") or 0) \
                    and self.rebuild_for_new_group(conn, types, read, rows, latest_build, draft.build):
                latest_build = tables.get_latest_build(conn, channel_id)
                draft = self.draft_context(conn, types, rows, latest_build, last_read, True, read)
            over_limit = self.is_over_limit(draft.total_tokens, last_read, draft.build, channel_id)
            if over_limit and not is_new_user_message and tables.is_waiting(latest_build, last_read):        # a ready build: taken now, not at the user
                draft = self.draft_context(conn, types, rows, latest_build, last_read, True, read)
                over_limit = self.is_over_limit(draft.total_tokens, last_read, draft.build, channel_id)
            if is_new_user_message or over_limit:
                latest_build = tables.get_latest_build(conn, channel_id)
                started_work = self.start_due_work(conn, types, read, rows, latest_build, draft.build, draft.total_tokens, over_limit)
                # over the limit, or joining, the read waits for its build however long it takes (up to build_timeout)
                wait_seconds = config.build_timeout if (over_limit and started_work == "build") or started_work == "join" else config.sync_seconds
                if started_work and wait_seconds > 0 and self.wait_for_build(conn, channel_id, rows[-1].row_id, started_work, wait_seconds, read.stopped):
                    latest_build = tables.get_latest_build(conn, channel_id)
                    draft = self.draft_context(conn, types, rows, latest_build, last_read, True, read)
            if self.get_provider_count(draft.total_tokens) > config.max_context_tokens:   # still over: the steps that do not fit, left out
                draft = Draft(draft.build, draft.section_ids, *self.assemble_context(conn, rows, draft.build, draft.section_ids, types, read, stub=True))
            if self.get_provider_count(draft.total_tokens) > config.max_context_tokens:
                self.log(f"[{channel_id}] context {draft.total_tokens} tokens ({self.get_provider_count(draft.total_tokens)} as the provider counts), "
                         f"over max_context_tokens={config.max_context_tokens}")
            self.last_tokens = draft.policy_tokens                    # the part of it the policy arranges
            return Context(draft.items, draft.refs, str(draft.build["build_id"]) if draft.build else None, tokens=draft.policy_tokens,
                           budget=config.max_context_tokens)
