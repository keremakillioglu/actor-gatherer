"""Rank earlier tasks by how much each bears on what the work is now.

One model call, ids only, at most `top_n` of them; candidates it leaves out follow in session
order, and on any failure the order is simply the session's.
"""

from dataclasses import dataclass
from typing import List, Optional

from ag.ag_interface import LLM
from .answers import find_object
from .history import Task, Turn
from .turns import messages

@dataclass
class Params:
    """What ranking is told: what the work is now, how many to ask for, which model."""
    turns: int = 3                        # last turns that say what the work is now
    top_n: int = 0                        # 0 = sized from budget_tokens (when the caller does not say)
    legroom: int = 40                     # % more candidates than fit
    budget_tokens: int = 15000            # what the caller will show: sizes the default top_n
    task_tokens_fallback: int = 700
    model: str = ""
    effort: str = "low"
    timeout: int = 180


RANK_SYSTEM = (
    "You rank a past session's tasks by how much each one bears on what the user "
    "is asking now. You return only JSON."
)


RANK_TEMPLATE = """\
# What to do

Below you will find a request, and a list of tasks from earlier in the same
session. Return the {top_n} tasks that bear most on that request, best first. Do
not return the rest: only that many are ever used, and ordering the tail costs
more than it is worth.

Rank them by how likely each is to carry a definition, convention, correction,
formula, exclusion or piece of context that changes how the request should be
answered. Terminology matters most: a task that defines or constrains a term
used in the request ranks high even if its subject was different.

RANK A TASK HIGH IF IT MAY CARRY AN INSTRUCTION OR CONTEXT THAT SHOULD BE
APPLIED TO THIS REQUEST -- a standing decision, a rule the user said to keep
using, a correction to how something is measured, read or joined. Such a task
ranks high EVEN IF ITS OWN SUBJECT LOOKS UNRELATED to the request: what matters
is whether what it settled still governs, not what it was working on at the
time. A `[carries: ...]` note on a task lists what it established; if any of
those bears on the request, that task belongs near the top.

RANK HIGHEST OF ALL a task whose `[carries: ...]` note shows the user gave an
instruction meant to APPLY TO FUTURE WORK -- "from here on", "use this for X",
"always", a definition or default they set -- where that future work could
include this request. Check every `[carries: ...]` note against the request
before you rank: an instruction the user meant to keep applying outranks a task
that merely shares the request's subject matter.

Return ONLY a JSON object, no prose and no code fence:

  {{"ranking": [<task id>, <task id>, ...]}}

Ids only. A reason for each would be more than half the output of this call, and
nothing reads it: the section is built from the order alone. Most relevant
first, at most {top_n} of them, each id appearing once.

# {heading}

{current}

# Tasks from earlier in this session

{tasks}
"""


def rank_target(turns: List[Turn], cfg: Params) -> str:
    """The last `cfg.turns` turns (all if 0), as their user and agent messages."""
    lines = []
    for turn in turns[-cfg.turns:] if cfg.turns else turns:
        for e in messages(turn):
            lines.append(f"{'USER' if e.is_user else 'AGENT'}: {e.text}")
    return "\n\n".join(lines)


def _top_n(candidates: List[Task], cfg: Params) -> int:
    """How many to ask for: what fits the related-tasks budget, plus
    `cfg.legroom` percent; at least 5, at most the number of candidates."""
    if cfg.top_n:
        return min(cfg.top_n, len(candidates))
    sizes = [t.tokens for t in candidates if t.tokens]
    typical = (sum(sizes) / len(sizes)) if sizes else cfg.task_tokens_fallback
    fits = cfg.budget_tokens / max(1, typical)
    asked = int(fits * (1 + cfg.legroom / 100.0) + 0.999)
    return max(1, min(len(candidates), max(5, asked)))


def carries(task: Task) -> str:
    keys = []
    for field, key in (("object_handling", "applies_to"), ("terminology", "applies_to"),
                       ("metadata", "object"), ("carry_forward", "applies_to")):
        keys += [x[key] for x in task.retention.get(field) or []]
    return f" [carries: {'; '.join(keys)}]" if keys else ""


def listing(candidates: List[Task], own_channel) -> str:
    lines = []
    for n, t in enumerate(candidates, 1):
        where = "" if t.channel_id == own_channel else f" (parallel channel {str(t.channel_id)[:8]})"
        lines.append(f"- id {n}: **{t.name}** (turns {t.start_turn}-{t.end_turn}){where}: "
                     f"{t.description}{carries(t)}")
    return "\n".join(lines)


def parse_ranking(text: str, count: int) -> List[int]:
    """0-based candidate positions, in ranked order, each once."""
    data = find_object(text, "ranking")
    out = []
    for x in (data or {}).get("ranking") or []:
        if isinstance(x, dict):
            x = x.get("id")
        try:
            n = int(x) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= n < count and n not in out:
            out.append(n)
    return out


def rank(candidates: List[Task], target: str, llm: LLM, cfg: Params,
         own_channel=None, heading: str = "The task at hand", top_n: Optional[int] = None) -> List[Task]:
    """`candidates`, most relevant first. The model is asked for `top_n` of
    them (default: as many as the related-tasks budget fits, plus legroom);
    the rest follow in session order."""
    if len(candidates) <= 1:
        return list(candidates)
    n = min(top_n, len(candidates)) if top_n else _top_n(candidates, cfg)
    prompt = RANK_TEMPLATE.format(top_n=n, heading=heading, current=target,
                                  tasks=listing(candidates, own_channel))
    answer = llm.complete(prompt, system=RANK_SYSTEM, model=cfg.model,
                          effort=cfg.effort, timeout=cfg.timeout, purpose="rank")
    order = parse_ranking(answer, len(candidates))
    order += [i for i in range(len(candidates)) if i not in order]
    return [candidates[i] for i in order]
