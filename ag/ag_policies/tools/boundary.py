"""Does the message that just arrived start a new task?

A yes / no: segmentation re-cuts the whole open task at every build, so a
boundary missed earlier is found there; this only decides whether to build
NOW rather than wait for the context to grow. One model call. Any failure
reads as "continuation", the cheaper mistake.

The definition of a task is deliberately the segmentation prompt's, in its
own words: the two have to agree, or a live session would be cut more finely
than the history it is appended to.
"""

from dataclasses import dataclass
from typing import List, Optional

from ag.ag_interface import LLM
from .answers import find_object
from .history import Task, Turn

@dataclass
class Params:
    """What the boundary check is told: what to show, and which model to ask."""
    tasks_shown: int = 2                  # finished tasks shown, for contrast
    block_chars: int = 6000               # per task block in the prompt
    model: str = ""
    effort: str = "low"
    timeout: int = 60


BOUNDARY_SYSTEM = (
    "You decide whether a user's new message belongs to the task an agent is "
    "already working on, or starts a new one. You return only JSON."
)

BOUNDARY_PROMPT = """\
# What to decide

Below you will find the task an agent is working on, the task or two before it,
and a numbered list of the requests in the running task, ending with the message
that has just arrived. Decide whether that last message STARTS A NEW TASK or
continues the running one.

A TASK is a run of CONSECUTIVE turns that serve one high level objective. A new
task starts when the user's objective changes. Turns that continue, refine,
correct, follow up or somehow otherwise relate to the previous turns belong to
the SAME task. Do not make a task per turn: working through several aspects of
one subject -- different cuts, different groupings, different metrics over the
same area -- is ONE task, even though each question is different from the last.

Judge the requests themselves. Boilerplate that every message carries -- an id,
a file to write the answer to, a data directory -- says nothing either way, and
a new id or a new output file is NOT evidence of a new task.

Return ONLY a JSON object, no prose and no code fence:

  {{"new_task": true or false, "why": "<one clause>"}}

When two readings are equally good, answer false. Treating a follow-up as a new
task throws away the detail it depends on; treating a new task as a follow-up
only costs some room.

{tasks}
# The requests in the running task, in order

{numbered}
"""


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else "(...earlier part omitted...)\n" + text[-limit:]


def render_previous(previous: List[Task], turns: List[Turn], cfg: Params) -> str:
    """The finished tasks before the running one, newest last: name,
    description and their requests."""
    blocks = []
    labels = ["# The task before that", "# The task before it"]
    for n, task in enumerate(reversed(previous[-cfg.tasks_shown:])):
        label = labels[1] if n == 0 else labels[0]
        requests = [t.user_text for t in turns if task.start_turn <= t.index <= task.end_turn]
        body = f"## {task.name}\n{task.description}\n\n" + "\n\n".join(f"USER: {r}" for r in requests)
        blocks.append(f"{label}\n\n{_clip(body, cfg.block_chars)}")
    blocks.reverse()
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def parse_verdict(text: str) -> Optional[bool]:
    """True / False from the answer, None if it has no usable verdict."""
    data = find_object(text or "", "new_task")
    if data is None:
        return None
    value = data.get("new_task")
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.strip().lower() in ("true", "yes"):
            return True
        if value.strip().lower() in ("false", "no"):
            return False
    return None


def is_new_task(open_turns: List[Turn], previous: List[Task], turns: List[Turn],
                llm: LLM, cfg: Params) -> tuple:
    """(verdict, why) for the last of `open_turns`, given the running task's
    earlier requests and the finished tasks before it: True (a new task),
    False (a continuation), or None when the model gave no usable answer.
    What None means for the context is the caller's decision."""
    numbered = "\n\n".join(f"[{n}] {_clip(t.user_text, cfg.block_chars)}"
                           for n, t in enumerate(open_turns, 1))
    prompt = BOUNDARY_PROMPT.format(tasks=render_previous(previous, turns, cfg), numbered=numbered)
    answer = llm.complete(prompt, system=BOUNDARY_SYSTEM, model=cfg.model,
                          effort=cfg.effort, timeout=cfg.timeout, purpose="boundary")
    verdict = parse_verdict(answer)
    if verdict is None:
        return None, "no usable verdict"
    data = find_object(answer, "new_task") or {}
    return verdict, str(data.get("why") or "")
