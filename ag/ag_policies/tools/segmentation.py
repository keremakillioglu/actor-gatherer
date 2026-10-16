"""Cut a history into TASKS: runs of consecutive turns serving one objective.

One model call per window of
turns, each shown the tasks found so far so a continuing task keeps its name;
a task over `task_chunk_tokens` is subdivided by another call, recursively.

Tasks are `history.Task`s, kept by row range (see there).
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple

from ag.ag_interface import LLM, Tokenizer
from .groups import AGENT_MESSAGE, TOOL_CALL
from .answers import find_objects
from .log import warn
from .history import Task, Turn
from .tasks import locate, task_tokens
from .turns import by_turn

@dataclass
class Params:
    """What segmentation is told: how to cut, and which model to ask."""
    task_chunk_tokens: int = 6000         # no task larger (user+agent message tokens)
    max_subdivide_depth: int = 3
    chunk_window_tokens: int = 30000      # rendered turns per call
    chunk_prior_tasks: int = 20           # earlier tasks shown to each call (0 = all)
    summarize: bool = True                # whether `update` names tasks to summarize
    model: str = ""
    effort: str = "high"
    timeout: int = 900


PROMPT = """\
You are segmenting a past agent session into high level TASKS so it can be reloaded later.

A TASK is a run of CONSECUTIVE turns that serve one high level objective. A new task starts
when the user's objective changes. Turns that continue, refine, correct, follow up or somehow otherwise
relate to the previous turns belong to the SAME task. Do not create a task per turn.
A task should be at least multiple turns but not too long. Infer the granularity of task based on the messages
but don't be over conservative (i.e., don't assign every turn to its own task).


{prior}
# Turns to segment

Each turn below is labelled `### turn <n>`. Turn numbers are global to the
session, not to this excerpt.

{window}

# What to return

Return ONLY a JSON object, no prose and no code fence:

{{"tasks": [
  {{"name": "<3-6 word name>",
   "description": "<one or two sentences: the objective, and what was done>",
   "start_turn": <first turn number>,
   "end_turn": <last turn number>}}
]}}

Rules:
- Cover EVERY turn shown above exactly once. Tasks must be contiguous and in
  order: each task's start_turn is the previous task's end_turn + 1.
- The first task must start at turn {first}.
- The last task must end at turn {last}.
- If a task listed under "Tasks already identified" continues into this excerpt,
  reuse its exact name and extend it — do not invent a near-duplicate name.
"""

SUBDIVIDE_PROMPT = """\
A single task from a past session is too large and must be divided into smaller
TASKS. Divide it where the objective genuinely shifts — a new sub-goal, a change
of target or question — NOT at an arbitrary midpoint. Each sub-task should stand
on its own: a reader given only its turns should understand what was being done.

# The task being divided

**{name}** — {description}

It spans turns {first} to {last} and is {size} message tokens; the limit is
{limit}, so it needs at least two sub-tasks, and more if that is what its
structure calls for.

# Its turns

{window}

# What to return

Return ONLY a JSON object, no prose and no code fence:

{{"tasks": [
  {{"name": "<3-6 word name>",
   "description": "<one or two sentences: the sub-objective, and what was done>",
   "start_turn": <first turn number>,
   "end_turn": <last turn number>}}
]}}

Rules:
- Cover EVERY turn from {first} to {last} exactly once, contiguously and in order.
- The first sub-task starts at turn {first}; the last ends at turn {last}.
- Return at least two sub-tasks. If the turns truly serve one indivisible
  objective, return exactly one and it will be kept whole.
- Give each sub-task its OWN name — do not reuse the parent's name verbatim.
"""

TURN_CHARS = 4000

# The prompt asks for "name" and "description"; models sometimes use another
# word for either, which would otherwise leave the task unnamed.
NAME_KEYS = ("name", "title", "task_name", "task")
DESCRIPTION_KEYS = ("description", "summary", "objective", "desc")



# ---------------------------------------------------------------- rendering

def render_turn(turn: Turn) -> str:
    """How segmentation sees a turn: the user's text, the agent's LAST reply,
    and how many tool calls it made. No tool content."""
    replies = [e.text for e in turn.entries[1:] if e.type == AGENT_MESSAGE and e.text.strip()]
    calls = sum(1 for e in turn.entries if e.type == TOOL_CALL)
    lines = [f"### turn {turn.index}", f"USER: {turn.user_text[:TURN_CHARS]}"]
    if replies:
        lines.append(f"AGENT: {replies[-1][:TURN_CHARS]}")
    if calls:
        lines.append(f"({calls} tool call{'s' if calls != 1 else ''})")
    return "\n".join(lines)


def window(turns: List[Turn], start: int, budget: int, tok: Tokenizer) -> List[Turn]:
    """Turns from position `start` while their rendering fits `budget`; at
    least one."""
    chosen, used = [], 0
    for turn in turns[start:]:
        cost = tok.count(render_turn(turn))
        if chosen and used + cost > budget:
            break
        chosen.append(turn)
        used += cost
    return chosen


def render_prior(prior: List[Task], limit: int) -> str:
    if not prior:
        return ""
    shown = prior[-limit:] if limit else prior
    lines = ["# Tasks already identified", ""]
    lines += [f"- **{t.name}** (turns {t.start_turn}-{t.end_turn}): {t.description}"
              for t in shown]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- parsing

def parse_tasks(text: str, first: int, last: int) -> List[dict]:
    """Tasks from a model answer: the first JSON object with "tasks", wherever
    it is, that has any usable -- a draft before the answer (tasks without
    their turns) is passed over; entries malformed or outside [first, last]
    dropped; sorted by start."""
    for data in find_objects(text, "tasks"):
        out = _tasks_of(data, first, last)
        if out:
            return out
    return []


def _tasks_of(data: dict, first: int, last: int) -> List[dict]:
    out = []
    for t in data.get("tasks") or []:
        if not isinstance(t, dict):
            continue
        try:
            s, e = int(t["start_turn"]), int(t["end_turn"])
        except (KeyError, TypeError, ValueError):
            continue
        if first <= s <= e <= last:
            name = next((t[k] for k in NAME_KEYS if isinstance(t.get(k), str) and t[k].strip()), "")
            desc = next((t[k] for k in DESCRIPTION_KEYS if isinstance(t.get(k), str) and t[k].strip()), "")
            out.append({"name": name.strip() or f"turns {s}-{e}", "description": desc.strip(),
                        "start_turn": s, "end_turn": e})
    return sorted(out, key=lambda t: t["start_turn"])


# ---------------------------------------------------------------- tasks

def make_task(name: str, description: str, start: int, end: int, turns: dict) -> Task:
    span = [turns[i] for i in range(start, end + 1) if i in turns]
    return Task(name=name, description=description,
                first_row=span[0].first_row, last_row=span[-1].last_row,
                start_turn=start, end_turn=end,
                tokens=sum(t.message_tokens for t in span))


def _contiguous(found: List[dict], first: int, last: int) -> List[dict]:
    """Force the tasks to cover first..last in order, with no gaps."""
    out, expect = [], first
    for t in found:
        t = dict(t, start_turn=expect)
        if t["end_turn"] < t["start_turn"]:
            continue
        out.append(t)
        expect = t["end_turn"] + 1
        if expect > last:
            break
    return out


def subdivide(task: Task, turns: List[Turn], llm: LLM, cfg: Params,
              depth: int = 0) -> List[Task]:
    """`task`, or its sub-tasks if it is over `task_chunk_tokens`."""
    size = task_tokens(task, turns)
    if size <= cfg.task_chunk_tokens:
        return [task]
    if task.start_turn == task.end_turn or depth >= cfg.max_subdivide_depth:
        warn(f"task '{task.name}' is {size} tokens (limit {cfg.task_chunk_tokens}); kept whole")
        return [task]
    index = by_turn(turns)
    span = [index[i] for i in range(task.start_turn, task.end_turn + 1) if i in index]
    prompt = SUBDIVIDE_PROMPT.format(
        name=task.name, description=task.description, first=task.start_turn,
        last=task.end_turn, size=size, limit=cfg.task_chunk_tokens,
        window="\n\n".join(render_turn(t) for t in span))
    answer = llm.complete(prompt, model=cfg.model, effort=cfg.effort,
                          timeout=cfg.timeout, purpose="subdivide")
    found = _contiguous(parse_tasks(answer, task.start_turn, task.end_turn),
                        task.start_turn, task.end_turn)
    if len(found) < 2:
        return [task]
    found[-1]["end_turn"] = task.end_turn
    parts = []
    for t in found:
        sub = make_task(t["name"], t["description"], t["start_turn"], t["end_turn"], index)
        parts.extend(subdivide(sub, turns, llm, cfg, depth + 1))
    return parts


def merge_continuations(tasks: List[Task]) -> List[Task]:
    """Join adjacent tasks with the same name; keep the longer description."""
    out: List[Task] = []
    for task in tasks:
        prev = out[-1] if out else None
        if prev and prev.name == task.name and task.start_turn == prev.end_turn + 1:
            prev.end_turn, prev.last_row = task.end_turn, task.last_row
            prev.tokens += task.tokens
            if len(task.description) > len(prev.description):
                prev.description = task.description
            continue
        out.append(task)
    return out


def segment(turns: List[Turn], llm: LLM, cfg: Params, tok: Tokenizer,
            prior: Optional[List[Task]] = None) -> tuple:
    """Tasks covering `turns`, in order, and whether every call failed.

    `prior` are tasks already found before these turns; they are shown to each
    call so a task that continues keeps its name, and are not returned.
    Returns `(tasks, all_failed)`: when no model call produced anything the
    tasks are one placeholder per window, and the caller should not keep them.
    """
    prior = list(prior or [])
    index = by_turn(turns)
    found: List[Task] = []
    cursor, answered = 0, False
    while cursor < len(turns):
        chunk = window(turns, cursor, cfg.chunk_window_tokens, tok)
        first, last = chunk[0].index, chunk[-1].index
        prompt = PROMPT.format(prior=render_prior(prior + found, cfg.chunk_prior_tasks),
                               window="\n\n".join(render_turn(t) for t in chunk),
                               first=first, last=last)
        answer = llm.complete(prompt, model=cfg.model, effort=cfg.effort,
                              timeout=cfg.timeout, purpose="segment")
        parsed = parse_tasks(answer, first, last)
        if parsed:
            answered = True
        else:
            parsed = [{"name": f"turns {first}-{last}",
                       "description": "(automatic: task segmentation failed here)",
                       "start_turn": first, "end_turn": last}]
        more_after = chunk[-1] is not turns[-1]
        if more_after and len(parsed) > 1:
            parsed = parsed[:-1]          # reconsider its turns with the next window
        for t in _contiguous(parsed, first, last):
            task = make_task(t["name"], t["description"], t["start_turn"], t["end_turn"], index)
            found.extend(subdivide(task, turns, llm, cfg))
        found = merge_continuations(found)
        done = found[-1].end_turn if found else first
        next_turn = max(done + 1, first + 1)
        cursor = next((i for i, t in enumerate(turns) if t.index >= next_turn), len(turns))
    # A merge can take a task back over the limit.
    tasks = []
    for task in merge_continuations(found):
        tasks.extend(subdivide(task, turns, llm, cfg))
    return tasks, not answered


def update(turns: List[Turn], stored: List[Task], llm: LLM, cfg: Params,
           tok: Tokenizer) -> Tuple[List[Task], bool, List[Task]]:
    """(the channel's tasks covering `turns`, whether segmentation failed, the
    tasks still to summarize).

    `stored` are the tasks a previous run found. All but the last are kept as
    they are; the last was still open then, so it is segmented again with
    everything after it. The new tasks want a summary -- except the last,
    which is still open and will be segmented again next time; it is
    summarized once it is finished. On failure (no model call answered) the
    tasks are not to be kept.
    """
    kept = locate(stored, turns)[:-1]
    start = kept[-1].end_turn + 1 if kept else 1
    new_turns = [t for t in turns if t.index >= start]
    new, failed = segment(new_turns, llm, cfg, tok, prior=kept) if new_turns else ([], False)
    if failed:
        return kept, True, []
    return kept + new, False, new[:-1] if cfg.summarize else []
