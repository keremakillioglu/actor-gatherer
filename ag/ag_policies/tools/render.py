"""Rendering history as text for sections.

Every rendered item carries
`[id N]`, N being its `row_id` in the `events` table, so the agent can look up
anything a section leaves out.
"""

from typing import List

from ag.ag_interface import Tokenizer
from .groups import AGENT_MESSAGE, TOOL_CALL, TOOL_OUTPUT, USER_MESSAGE
from .history import Entry, Task, Turn
from .sequences import ends_inward
from .tasks import full_entries, message_entries

TOOL_CHARS = 2000
RETENTION_LABELS = (("object_handling", "handling", "applies_to", "spec"),
                    ("terminology", "term", "applies_to", "spec"),
                    ("metadata", "about", "object", "value"),
                    ("carry_forward", "standing", "applies_to", "spec"))


def label(e: Entry) -> str:
    return f"[id {e.row_id}]"


def speaker(e: Entry) -> str:
    """The speaker label: USER or AGENT by type; anything else by its type name."""
    if e.is_user:
        return "USER"
    if e.is_message:
        return "AGENT"
    return (e.type or "item").upper()


def render_entry(e: Entry) -> str:
    if e.type == TOOL_CALL:
        return f"{label(e)} [tool call] {e.text[:TOOL_CHARS]}"
    if e.type == TOOL_OUTPUT:
        return f"{label(e)} [tool output] {e.text[:TOOL_CHARS]}"
    return f"{label(e)} {speaker(e)}: {e.text}"


def task_header(task: Task, note: str = "") -> str:
    lines = [f"## {task.name} (turns {task.start_turn}-{task.end_turn}){note}"]
    if task.description:
        lines.append(task.description)
    for field, name, key, value in RETENTION_LABELS:
        for x in task.retention.get(field) or []:
            lines.append(f"   {name}: {x[key]} — {x[value]}")
    return "\n".join(lines)


def render_full(task: Task, turns: List[Turn], note: str = "") -> str:
    return "\n\n".join([task_header(task, note)] + [render_entry(e) for e in full_entries(task, turns)])


def render_messages(task: Task, turns: List[Turn], note: str = "") -> str:
    return "\n\n".join([task_header(task, note)] + [render_entry(e) for e in message_entries(task, turns)])


# ---------------------------------------------------------------- fit_task

def _kind(e: Entry) -> str:
    if e.is_tool:
        return "tool"
    return "user" if e.is_user else "agent"


def _gap(skipped: List[Entry]) -> str:
    counts = {"tool": 0, "user": 0, "agent": 0}
    for e in skipped:
        counts[_kind(e)] += 1
    names = {"tool": "tool call/output", "user": "user message", "agent": "agent message"}
    parts = [f"{n} {names[k]}{'s' if n != 1 else ''}" for k, n in counts.items() if n]
    ids = f"ids {skipped[0].row_id}-{skipped[-1].row_id}" if len(skipped) > 1 else f"id {skipped[0].row_id}"
    return f"(...omitted: {', '.join(parts)}; {ids} — read them from the `events` table)"


def _render(header: str, entries: List[Entry], keep: set) -> str:
    blocks, skipped = [header], []
    for i, e in enumerate(entries):
        if i in keep:
            if skipped:
                blocks.append(_gap(skipped))
                skipped = []
            blocks.append(render_entry(e))
        else:
            skipped.append(e)
    if skipped:
        blocks.append(_gap(skipped))
    return "\n\n".join(blocks)


def fit(header: str, entries: List[Entry], budget: int, tok: Tokenizer) -> str:
    """`header` and `entries` within `budget` tokens, trimming the middle.

    Kept in this order, each pass stopping at the first item that does not
    fit: user messages from both ends inward, then agent messages from both
    ends inward, then tool items from the start. Kept items stay in their
    original order; each run of dropped ones becomes one line naming what was
    dropped and its id range. If the rendering is still over budget (the gap
    lines cost too), items are given back -- tools last-in first, then agent,
    then user messages -- keeping at least one.
    """
    whole = "\n\n".join([header] + [render_entry(e) for e in entries])
    if tok.count(whole) <= budget:
        return whole
    cost = [tok.count(render_entry(e)) for e in entries]
    used = tok.count(header)
    keep, order = set(), []
    passes = [ends_inward([i for i, e in enumerate(entries) if _kind(e) == "user"]),
              ends_inward([i for i, e in enumerate(entries) if _kind(e) == "agent"]),
              [i for i, e in enumerate(entries) if _kind(e) == "tool"]]
    for indices in passes:
        for i in indices:
            if used + cost[i] > budget:
                break
            keep.add(i)
            order.append(i)
            used += cost[i]
    text = _render(header, entries, keep)
    while tok.count(text) > budget and len(keep) > 1:
        give_back = next((i for i in reversed(order) if _kind(entries[i]) == "tool"), None)
        if give_back is None:
            give_back = next((i for i in reversed(order) if _kind(entries[i]) == "agent"), order[-1])
        keep.discard(give_back)
        order.remove(give_back)
        text = _render(header, entries, keep)
    return text


def fit_task(task: Task, turns: List[Turn], budget: int, tok: Tokenizer, full: bool = True,
             note: str = "") -> str:
    entries = full_entries(task, turns) if full else message_entries(task, turns)
    return fit(task_header(task, note), entries, budget, tok)
