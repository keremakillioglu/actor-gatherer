"""The proactive context manager: earlier history as sections built in the
background, aware of what happens outside the conversation and of the
requests the user makes to the session's other channels.

Every context opens, after the harness's own set-up, with the GATHERER GUIDE
(`gatherer_guide`, `layout.guide`): what ag adds to the context -- the sections, the
parallel requests, notices, stream messages, left-out notes -- and where the full history
is. On every read, with or without a build; one made item, the same while its text is.

ProactiveContextManager is made of parts, one class per question, each in its own file:

    policy.py             the entry points, and one read from start to finish (`read`, `draft_context`,
                          `assemble_context`)
    context_limit.py      keeping the context under its token limit
    external_events.py    file-change notices and messages from a stream
    parallel_requests.py  the user's requests to the session's other channels
    session_groups.py     which sessions share work, and telling a session its group changed
    gatherer_messages.py  the gatherer's messages: their names, making one, placing them among the rows
    builds.py             during a read: starting builds and checks, waiting for them, adopting a ready one
    analysis.py           in the worker: what a build computes, and the boundary check

besides the package's other files: layout.py (a build's sections, as text), tables.py (what is stored), wording.py
(every text ag writes for the agent), config.py (what can be tuned) and events.py (the event types).
"""

from typing import Dict, List, NamedTuple, Optional, Tuple

from ag.ag_interface import LLM, Format, Ref, Tokenizer, property_column
from ag.ag_interface.policy import Context, Policy, Read, TypeIds
from ag.ag_policies.tools import channel, history
from ag.ag_policies.tools.channel import CHANNEL, channel_of
from ag.ag_policies.tools.options import config_from
from . import layout, tables
from .analysis import Analysis
from .builds import Builds
from .config import ProactiveContextManagerConfig
from .events import EVENT_TYPES
from .external_events import ExternalEvents
from .gatherer_messages import GUIDE
from .parallel_requests import ParallelRequests
from .session_groups import GROUP


class Draft(NamedTuple):
    """A read's context as laid out from one choice of build (`choose_build`): the build in use and its sections'
    made_ids, and what `assemble_context` made of them -- `size`, all the model gets; `own`, the part the policy arranges."""
    build: Optional[dict]
    made: List[int]
    items: list
    refs: list
    size: int
    own: int


class ProactiveContextManager(Builds, Analysis, ExternalEvents, ParallelRequests, Policy):
    """The policy: its parts' methods, then `Policy`'s defaults for whatever no part defines (hence `Policy` last)."""

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
        self.drift = 1.0                            # by_provider's, set for each read and each build

    @property
    def groups(self):
        return self.config.groups

    def init(self, conn) -> None:
        """`tasks`, `_builds` and `_boundaries` (tables.py), if absent."""
        tables.create(conn)

    def append(self, conn, db: str, offset: int) -> None:
        """Another gatherer's tables appended (Policy.append; tables.append)."""
        tables.append(conn, db, offset)

    # ------------------------------------------------------------ one read

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
            latest = tables.build_for(conn, ch)
            last = conn.last_read(channel.of(ch))
            self.drift = self.get_provider_drift(last)
            draft = self.draft_context(conn, types, rows, latest, last, at_user or self.is_build_for_this_turn(latest, rows, types), read)
            if last and self.has_group_changed(conn, types, ch, last.get("row_id") or 0) \
                    and self.rebuild_for_new_group(conn, types, read, rows, latest, draft.build):
                latest = tables.build_for(conn, ch)
                draft = self.draft_context(conn, types, rows, latest, last, True, read)
            over = self.is_over_limit(draft.size, last, draft.build, ch)
            if over and not at_user and tables.is_waiting(latest, last):        # a ready build: taken now, not at the user
                draft = self.draft_context(conn, types, rows, latest, last, True, read)
                over = self.is_over_limit(draft.size, last, draft.build, ch)
            if at_user or over:
                latest = tables.build_for(conn, ch)
                started = self.start_due_work(conn, types, read, rows, latest, draft.build, draft.size, over)
                # over the limit, or joining, the read waits for its build however long it takes (up to build_timeout)
                seconds = cfg.build_timeout if (over and started == "build") or started == "join" else cfg.sync_seconds
                if started and seconds > 0 and self.wait_for_build(conn, ch, rows[-1].row_id, started, seconds, read.stopped):
                    latest = tables.build_for(conn, ch)
                    draft = self.draft_context(conn, types, rows, latest, last, True, read)
            if self.get_provider_count(draft.size) > cfg.max_context_tokens:   # still over: the steps that do not fit, left out
                draft = Draft(draft.build, draft.made, *self.assemble_context(conn, rows, draft.build, draft.made, types, read, stub=True))
            if self.get_provider_count(draft.size) > cfg.max_context_tokens:
                self.log(f"[{ch}] context {draft.size} tokens ({self.get_provider_count(draft.size)} as the provider counts), "
                         f"over max_context_tokens={cfg.max_context_tokens}")
            self.last_tokens = draft.own                    # the part of it the policy arranges
            return Context(draft.items, draft.refs, str(draft.build["build_id"]) if draft.build else None, tokens=draft.own,
                           budget=cfg.max_context_tokens)

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
        fixed = self.tokenizer.count(layout.overview(cfg, tables.is_join(build))) if made else 0
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
        text = layout.guide(self.config, conn.path, seen.own if seen is not None and seen.groups else None,
                            sorted(seen.reads) if seen is not None else ())
        if not text:
            return []
        item = self.format.make_section(text, GUIDE)
        col = property_column(CHANNEL)
        found = conn.execute(f"SELECT made_id FROM _made_items WHERE name = ? AND ifnull({col}, '') = ? "
                             f"ORDER BY made_id DESC LIMIT 1", (GUIDE, tables.key(channel_id))).fetchone()
        made_id = found[0] if found else None
        if made_id is None or conn.made_items([made_id])[made_id][1] != item:
            made_id = conn.make_item(item, self.tokenizer, properties=channel.of(channel_id), name=GUIDE)
        return [(made_id, item, conn.made_items([made_id])[made_id][2])]
