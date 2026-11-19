"""Every parameter of the proactive context manager, with its default: when it builds,
the budgets of its sections, the models the tools call, and how a stream
message, a request made in another channel and an environment update are shown
(`message`, `parallel_message`, `notice`), and the guide that opens every
context (`gatherer_guide`). The models default to the LLM's own
(`llm.model`, see tools/options.py).

The tools declare what they are told as their own `Params`
(`tools/segmentation.Params`, ...); the properties at the end build those
from the flat fields here, so one config states everything and the tools
know nothing of it.
"""

from dataclasses import dataclass, field, replace
from typing import Tuple

from ..tools import boundary as boundary_tool
from ..tools import ranking as ranking_tool
from ..tools import segmentation as segmentation_tool
from ..tools import summarize as summarize_tool
from ..tools.groups import Groups
from .core import prompts


@dataclass
class ProactiveContextManagerConfig:
    # All the model gets with a call -- the sections, the pinned rows and the running task
    # (its verbatim events since the cut, with the notices, stream messages and other
    # channels' requests among them), the history's preamble, the sections' overview, and
    # what the harness sends besides the context (its system prompt and tools) -- is at most
    # max_context_tokens, as the provider counts it (utils/tokens.py's `get_provider_count`: ag's counts, which the
    # hooks replace by the provider's, scaled by how far the provider's count of the channel's last call
    # ran over them): above it, on any read, a build is started, waited for, and cuts
    # the running task so the context is below it again. At a user message, X being that size:
    #     X <  min_context_tokens   no build
    #     min <= X                  ask the model whether this message starts a new
    #                               task (tools/boundary.py); build if so
    # A build whose context would still be over the limit cuts the running task after its
    # last event: all of it so far becomes "This task so far" (keep_so_far_tokens), and
    # only what comes after is verbatim. What the budgets (below) leave under the limit
    # is the headroom the running task grows into before the next build:
    # their sum + keep_pinned_tokens < max_context_tokens.
    #
    # A harness that states its own limit with a call (where it compacts by itself, or
    # where its model's window ends: the `limit` of a read) sets max_context_tokens for that
    # call's channel to harness_limit_fraction of it, unless the gatherer's options set
    # max_context_tokens; below the default, the budgets and min_context_tokens shrink with
    # it in proportion (`within_limit`). The fraction leaves room for one step's growth: the
    # harness checks its limit right after an answer, before ag's next read can act.
    min_context_tokens: int = 15000
    max_context_tokens: int = 200000
    harness_limit_fraction: float = 0.9
    keep_pinned_tokens: int = 5000        # the pinned rows of the condensed span (the newest kept)
    build_every_request: bool = False     # build at every user message (tests, experiments)
    sync_seconds: float = 15.0            # how long a read waits for the worker it started
                                          # (over the limit: up to build_timeout)
    build_wait_seconds: float = 45.0      # once the check finds a new task, how long the read waits for
                                          # that build, from when it began waiting (such builds took
                                          # 15-28 s); one still running is taken up at a later call
                                          # of the same turn
    check_boundaries: bool = True         # at or over min_context_tokens, ask; False = no build there
    boundary_cooldown: int = 2            # user messages into the open task before asking
    boundary_tasks_shown: int = 2         # finished tasks shown to the check, for contrast
    boundary_block_chars: int = 6000      # per task block in the check's prompt
    build_timeout: int = 3600             # a running build older than this is dead
    require_smaller: bool = True          # refuse to adopt a build whose sections are not
                                          # smaller than the history they replace

    # Segmentation.
    task_chunk_tokens: int = 6000         # no task larger (user+agent message tokens)
    max_subdivide_depth: int = 3
    chunk_window_tokens: int = 30000      # rendered turns per segmentation call
    chunk_prior_tasks: int = 20           # earlier tasks shown to each call (0 = all)
    summarize: bool = True                # record what each task established
    summarize_workers: int = 0            # 0 = one thread per task

    # Budgets, in tokens.
    keep_previous_task_tokens: int = 15000
    keep_temporal_relevant_tokens: int = 15000
    keep_task_relevant_tokens: int = 15000
    all_task_tokens: int = 30000          # this channel's earlier requests
    parallel_index_tokens: int = 10000    # other channels' requests in the index
    keep_so_far_tokens: int = 15000       # the running task, condensed, when a build cuts it ("so far")

    # Ranking.
    parallel_related_tasks: bool = True   # other channels' tasks may be ranked in
    rank_turns: int = 3                   # last turns that say what the work is now
    rank_top_n: int = 0                   # 0 = the tool sizes it from the budget when not told
    rank_legroom: int = 40                # % more candidates than fit
    task_tokens_fallback: int = 700

    # Models.
    segment_model: str = ""
    segment_effort: str = "high"
    segment_timeout: int = 900
    summarize_model: str = ""            # "" = segment_model; summaries (and cleaned requests) are written by it
    summarize_effort: str = ""           # "" = segment_effort
    rank_model: str = ""
    rank_effort: str = "low"
    rank_timeout: int = 180
    boundary_model: str = ""
    boundary_effort: str = "low"
    boundary_timeout: int = 60

    # Events: how the policy groups the event types it works from (tools/groups.py).
    groups: Groups = field(default_factory=Groups)

    # Tell the agent where its full history is (in the gatherer guide, below).
    db_hint: bool = True

    # The text of each, and what it says, is in core/prompts.py.
    gatherer_guide: str = prompts.GATHERER_GUIDE

    message: str = prompts.STREAM_MESSAGE

    notice: str = prompts.NOTICE
    notice_repeat: str = prompts.NOTICE_REPEAT
    notice_named: str = prompts.NOTICE_NAMED
    notice_counted: str = prompts.NOTICE_COUNTED
    notice_names: int = 5

    parallel_message: str = prompts.PARALLEL_MESSAGE

    group_moved: str = prompts.GROUP_MOVED
    group_joined: str = prompts.GROUP_JOINED
    group_left: str = prompts.GROUP_LEFT
    group_alone: str = prompts.GROUP_ALONE
    group_back: str = prompts.GROUP_BACK
    group_own: str = prompts.GROUP_OWN
    reads_added: str = prompts.READS_ADDED
    reads_removed: str = prompts.READS_REMOVED

    # A user message of another channel that opens a line, in its first characters, with one of these is not
    # shown to this one (core/parallel_sessions.py's `is_user_request`): a message the actors of the gatherer sent each other through the
    # dashboard (`ag actors`, ag_dashboard/coordination.py's envelopes), the receiver's to act on, not a request of the
    # user's. () = every one shown.
    unshared_openings: Tuple[str, ...] = ("Message from the coordinator agent", "Message from the gatherer agent", "Message from actor ",
                                          "Update (you asked with `ag actors when`")

    def __post_init__(self):
        held = self.section_budgets + self.keep_pinned_tokens
        if held >= self.max_context_tokens:
            raise ValueError(
                f"the budgets do not fit max_context_tokens={self.max_context_tokens}: sections "
                f"{self.section_budgets} + keep_pinned_tokens {self.keep_pinned_tokens} = {held}, which leaves "
                f"no headroom before the next build")
        if self.min_context_tokens >= self.max_context_tokens:
            raise ValueError(
                f"min_context_tokens={self.min_context_tokens} is not under max_context_tokens="
                f"{self.max_context_tokens}: the context never reaches it, so the policy would never check "
                f"whether a user message starts a new task")

    @property
    def section_budgets(self) -> int:
        """Every section's budget, added up: the most the sections can hold."""
        return (self.all_task_tokens + self.parallel_index_tokens + self.keep_temporal_relevant_tokens
                + self.keep_task_relevant_tokens + self.keep_previous_task_tokens
                + self.keep_so_far_tokens)

    # ---- what each tool is told, from the fields above

    @property
    def segmentation(self) -> segmentation_tool.Params:
        return segmentation_tool.Params(task_chunk_tokens=self.task_chunk_tokens, max_subdivide_depth=self.max_subdivide_depth,
                                   chunk_window_tokens=self.chunk_window_tokens, chunk_prior_tasks=self.chunk_prior_tasks,
                                   summarize=self.summarize, model=self.segment_model, effort=self.segment_effort,
                                   timeout=self.segment_timeout)

    @property
    def summarizing(self) -> summarize_tool.Params:
        return summarize_tool.Params(workers=self.summarize_workers, model=self.summarize_model or self.segment_model,
                                effort=self.summarize_effort or self.segment_effort, timeout=self.segment_timeout)

    @property
    def boundary(self) -> boundary_tool.Params:
        return boundary_tool.Params(tasks_shown=self.boundary_tasks_shown, block_chars=self.boundary_block_chars,
                               model=self.boundary_model, effort=self.boundary_effort, timeout=self.boundary_timeout)

    @property
    def ranking(self) -> ranking_tool.Params:
        return ranking_tool.Params(turns=self.rank_turns, top_n=self.rank_top_n, legroom=self.rank_legroom,
                              budget_tokens=self.keep_task_relevant_tokens, task_tokens_fallback=self.task_tokens_fallback,
                              model=self.rank_model, effort=self.rank_effort, timeout=self.rank_timeout)


#: What shrinks with max_context_tokens when a harness's limit puts it below the config's own.
SCALED = ("min_context_tokens", "keep_pinned_tokens", "all_task_tokens", "parallel_index_tokens",
          "keep_temporal_relevant_tokens", "keep_task_relevant_tokens", "keep_previous_task_tokens",
          "keep_so_far_tokens")


def within_limit(config: ProactiveContextManagerConfig, limit: int) -> ProactiveContextManagerConfig:
    """`config` for a harness whose own limit is `limit` tokens: max_context_tokens is
    harness_limit_fraction of it; when that is below cfg's, the budgets and
    min_context_tokens shrink in the same proportion, so they fit as they did.

    Raises:
        ValueError: the limit leaves too little to fit them.
    """
    target = int(limit * config.harness_limit_fraction)
    if target == config.max_context_tokens:
        return config
    if target > config.max_context_tokens:
        return replace(config, max_context_tokens=target)
    factor = target / config.max_context_tokens
    return replace(config, max_context_tokens=target, **{field: int(getattr(config, field) * factor) for field in SCALED})
