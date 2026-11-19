"""The proactive context manager's context sections, as text, from data already
loaded. Pure: no model calls, no database. The headings, the overview the
model reads, the database hint and the order of the sections are this
policy's; the rendering of entries and tasks it uses is the toolkit's
(`ag_policies/tools/render.py`).

With tasks T1..Tn, the last one, Tn, is still running and stays in the
context verbatim -- unless a build cut it, when its steps before the cut are
"This task so far"; everything before it becomes text at decreasing detail,
each section within its budget:

    # How this history is organised    what the sections are (and where the
    # Every earlier request            full history is), then every earlier
                                       user request, verbatim (all_task_tokens),
                                       and the other channels' requests up to
                                       the build (parallel_index_tokens)
    # Earlier messages                 whole tasks before Tn-1, newest first
                                       while they fit, as messages only
    # Related earlier tasks            whole tasks chosen by ranking, from
                                       this channel and the others, messages only
    # Previous task                    Tn-1 in full, tool activity included
    # This task so far                 Tn before the cut, when there is one"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

from ag.ag_interface import Tokenizer, property_column
from ag.ag_policies.tools.channel import CHANNEL
from ..config import ProactiveContextManagerConfig
from ag.ag_policies.tools.history import Entry, Task, Turn
from ag.ag_policies.tools.render import fit, fit_task, label, render_messages
from .prompts import (BEFORE_HEADER, BEFORE_NOTE, BEFORE_OMITTED, CLIPPED, DB_GROUPS_HINT, DB_GROUP_HINT, DB_HINT,
                      EARLIER_HEADER, FROM_PARALLEL, INDEX_HEADER, JOINED_OPENING, OPENING, OVERVIEW, OVERVIEW_HEADER,
                      PREVIOUS_HEADER, RELATED_HEADER, REQUESTS_HEADER, REQUESTS_INTRO, REQUESTS_OMITTED, SO_FAR_HEADER,
                      SO_FAR_NOTE)


@dataclass
class Sections:
    """What `build_sections` produces: the section texts, and where the
    verbatim part starts (the running task's start, or the cut)."""
    sections: List[Tuple[str, str]] = field(default_factory=list)
    open_from_row: int = 0
    through_row: int = 0
    parallel_mark: int = 0


def overview(cfg: ProactiveContextManagerConfig, joined: bool = False) -> str:
    """The sections' fixed preamble: how they are organised. `joined`: for a session that started
    from the gatherer's other sessions (a `join` build), which has no earlier history of its own."""
    return f"{OVERVIEW_HEADER}\n\n{JOINED_OPENING if joined else OPENING}\n\n{OVERVIEW}"


def guide(cfg: ProactiveContextManagerConfig, db_path: Optional[str], group: Optional[str] = None,
          reads: Sequence[str] = ()) -> str:
    """The gatherer guide that opens every context (`config.gatherer_guide`), with where the full
    history is when db_hint is set -- and, `group` given (a database every group's sessions share), how
    to keep to the session's own group there, or to the groups it is shown (`reads`: a coordinator agent's
    over several); "" for none."""
    if not cfg.gatherer_guide:
        return ""
    text = cfg.gatherer_guide.format(db_path=db_path or "", channel_column=property_column(CHANNEL))
    if cfg.db_hint and db_path:
        text += DB_HINT.format(db_path=db_path, channel_column=property_column(CHANNEL))
        if group is not None and reads:
            shown = [group, *[g for g in reads if g != group]]
            text += DB_GROUPS_HINT.format(groups=", ".join(f"`{g}`" for g in shown[1:]),
                                          listed=", ".join("'" + g.replace("'", "''") + "'" for g in shown),
                                          channel_column=property_column(CHANNEL))
        elif group is not None:
            text += DB_GROUP_HINT.format(group=group.replace("'", "''"), channel_column=property_column(CHANNEL))
    return text


def every_earlier_request(turns: List[Turn], stop_row: int, other: List[Tuple[Optional[str], Entry]],
                          cfg: ProactiveContextManagerConfig, tok: Tokenizer) -> str:
    """This channel's user requests before `stop_row`, then the other
    channels' requests -- within parallel_index_tokens, or, with none of this channel's own (a
    session that joined the gatherer), within all_task_tokens as well."""
    lines = [REQUESTS_HEADER, "", REQUESTS_INTRO]
    used = tok.count("\n".join(lines))
    mine = [t.entries[0] for t in turns if t.first_row < stop_row]
    for n, e in enumerate(mine):
        line = f"{label(e)} USER: {e.text}"
        cost = tok.count(line)
        if used + cost > cfg.all_task_tokens:
            left = mine[n:]
            lines.append(REQUESTS_OMITTED.format(count=len(left), first=left[0].row_id, last=left[-1].row_id))
            break
        lines.append(line)
        used += cost
    budget = cfg.parallel_index_tokens + (0 if mine else cfg.all_task_tokens - used)
    block = index_block(other, budget, tok)
    if block:
        lines += ["", block]
    return "\n".join(lines)


def earlier_messages(tasks: List[Task], turns: List[Turn], cfg: ProactiveContextManagerConfig,
                     tok: Tokenizer) -> Tuple[str, Set[int]]:
    """Whole tasks, newest first, messages only, while they fit; shown in
    session order. Stops at the first that does not fit. Returns the text and
    the positions of the tasks it holds."""
    chosen, used = [], 0
    for i in range(len(tasks) - 1, -1, -1):
        text = render_messages(tasks[i], turns)
        cost = tok.count(text)
        if used + cost > cfg.keep_temporal_relevant_tokens:
            break
        chosen.append((i, text))
        used += cost
    if not chosen:
        return "", set()
    chosen.reverse()
    return "\n\n".join([EARLIER_HEADER] + [t for _, t in chosen]), {i for i, _ in chosen}


def related_tasks(ranked: List[Task], turns_by_channel: Dict, own_channel,
                  cfg: ProactiveContextManagerConfig, tok: Tokenizer) -> str:
    """Whole ranked tasks, messages only, within budget: the first always
    (trimmed if it alone is over), then any that still fit. Shown in session order (by row)."""
    chosen, used = [], 0
    for task in ranked:
        note = "" if task.channel_id == own_channel else FROM_PARALLEL.format(channel=str(task.channel_id)[:8])
        text = render_messages(task, turns_by_channel[task.channel_id], note)
        cost = tok.count(text)
        if used + cost > cfg.keep_task_relevant_tokens:
            if chosen:
                continue
            # the most relevant task, alone over the budget: trimmed to fit, never shown whole
            text = fit_task(task, turns_by_channel[task.channel_id], cfg.keep_task_relevant_tokens, tok,
                            full=False, note=note)
            cost = tok.count(text)
            if cost > cfg.keep_task_relevant_tokens:
                continue
        chosen.append((task.first_row, text))
        used += cost
    if not chosen:
        return ""
    return "\n\n".join([RELATED_HEADER] + [t for _, t in sorted(chosen)])


def previous_task(task: Task, turns: List[Turn], cfg: ProactiveContextManagerConfig, tok: Tokenizer) -> str:
    return f"{PREVIOUS_HEADER}\n\n" + fit_task(task, turns, cfg.keep_previous_task_tokens, tok, full=True)


def so_far(task: Task, cut_row: int, turns: List[Turn], cfg: ProactiveContextManagerConfig, tok: Tokenizer) -> str:
    """The running task before `cut_row` -- every turn from its start, a turn begun after the build
    included -- in full, fitted to keep_so_far_tokens."""
    entries = [e for t in turns if t.index >= task.start_turn for e in t.entries
               if e.row_id < cut_row and e.text.strip() and (e.is_message or e.is_tool)]
    return fit(f"{SO_FAR_HEADER}\n\n{SO_FAR_NOTE}", entries, cfg.keep_so_far_tokens, tok)


def clip(text: str, budget: int, tok: Tokenizer) -> str:
    """`text` within `budget` tokens: as it is if it fits, else its start and end with the middle left
    out -- the last word on a section's budget, after the fitting that trims whole items (which keeps
    at least one, however long)."""
    if tok.count(text) <= budget:
        return text
    lo, hi = 0, len(text)
    while lo < hi:                                       # the most characters kept that still fit
        mid = (lo + hi + 1) // 2
        if tok.count(text[:mid // 2] + CLIPPED + text[len(text) - mid // 2:]) <= budget:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo // 2] + CLIPPED + text[len(text) - lo // 2:] if lo else ""


# ---------------------------------------------------------------- other channels
#
# A channel is one line of work; the session's other channels are parallel work
# by the same agent on the same material. What was established there -- a
# definition, a convention, a correction -- binds here too, so each context
# carries the other channels' requests: in the index, up to the build
# (`index_block`); those that arrived since are shown in place, before the
# channel's latest request, or mid-turn after its latest step (parallel_sessions.py's
# `make_parallel_requests`, `get_request_positions`). The requests
# themselves come from `tools/history.other_requests`.


def _line(e: Entry) -> str:
    return f"{label(e)} USER: {e.text}"


def index_block(requests: List[Tuple[Optional[str], Entry]], budget: int, tok: Tokenizer) -> str:
    """The other channels' requests for `# Every earlier request`: oldest
    first, until `budget`; the rest named as omitted."""
    if not requests or budget <= 0:
        return ""
    lines, used = [INDEX_HEADER, ""], tok.count(INDEX_HEADER)
    for n, (channel, e) in enumerate(requests):
        line = f"{_line(e)}  (channel {str(channel)[:8]})"
        cost = tok.count(line)
        if used + cost > budget:
            left = requests[n:]
            lines.append(REQUESTS_OMITTED.format(count=len(left), first=left[0][1].row_id, last=left[-1][1].row_id))
            break
        lines.append(line)
        used += cost
    return "\n".join(lines)


def requests_before(requests: List[Tuple[Optional[str], Entry]], budget: int, tok: Tokenizer) -> str:
    """The other channels' requests made before a session with no build of its own began, as one
    block within `budget`: the newest that fit, in order, after a line naming the earlier ones
    left out."""
    head = [BEFORE_HEADER, "", BEFORE_NOTE, ""]
    first, last = requests[0][1].row_id, requests[-1][1].row_id
    omitted = BEFORE_OMITTED.format(count=len(requests), first=first, last=last)
    used = tok.count("\n".join(head)) + tok.count(omitted)   # room for the line, however many it names
    kept = []
    for channel, e in reversed(requests):
        line = f"{_line(e)}  (channel {str(channel)[:8]})"
        cost = tok.count(line)
        if used + cost > budget:
            break
        kept.append(line)
        used += cost
    kept.reverse()
    left = len(requests) - len(kept)
    if left:
        head.append(BEFORE_OMITTED.format(count=left, first=first, last=requests[left - 1][1].row_id))
    return "\n".join(head + kept)


def build_sections(turns: List[Turn], tasks: List[Task], ranked: List[Task],
                   earlier: Tuple[str, Set[int]], other_requests, turns_by_channel: Dict,
                   own_channel, cfg: ProactiveContextManagerConfig, tok: Tokenizer, db_path: Optional[str],
                   through_row: int, parallel_mark: int, cut_row: Optional[int] = None,
                   joined: bool = False) -> Sections:
    """The sections for a channel with at least one task.

    `ranked` are the related-task candidates, most relevant first (the policy
    has already left out the running, previous and earlier-messages tasks). `earlier` is
    `earlier_messages(tasks[:-2], ...)`. `cut_row`, a row inside the running task, moves the
    verbatim part's start there: the steps before it become "This task so far". Every section
    is within its budget (`clip`); the overview, the agent's view of how the sections work, is
    the sections' fixed preamble and is not counted. `joined`: a session that started from the
    gatherer's other sessions (a `join` build) -- its one task is the running one, and the
    sections are the other channels' requests and tasks.
    """
    running = tasks[-1]
    previous = tasks[-2] if len(tasks) > 1 else None
    cut = max(cut_row or running.first_row, running.first_row)
    earlier_text, earlier_set = earlier
    reproduced = ([previous.first_row] if previous else [running.first_row]) + \
        [tasks[i].first_row for i in earlier_set]
    out = Sections(open_from_row=cut, through_row=through_row, parallel_mark=parallel_mark)
    requests = every_earlier_request(turns, min(reproduced), other_requests, cfg, tok)
    out.sections.append(("requests", overview(cfg, joined) + "\n\n" +
                         clip(requests, cfg.all_task_tokens + cfg.parallel_index_tokens, tok)))
    if earlier_text:
        out.sections.append(("earlier", clip(earlier_text, cfg.keep_temporal_relevant_tokens, tok)))
    related = related_tasks(ranked, turns_by_channel, own_channel, cfg, tok)
    if related:
        out.sections.append(("related", clip(related, cfg.keep_task_relevant_tokens, tok)))
    if previous is not None:
        out.sections.append(("previous", clip(previous_task(previous, turns, cfg, tok),
                                              cfg.keep_previous_task_tokens, tok)))
    if cut > running.first_row:
        out.sections.append(("so_far", clip(so_far(running, cut, turns, cfg, tok), cfg.keep_so_far_tokens, tok)))
    return out
