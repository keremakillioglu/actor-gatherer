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
from typing import Dict, List, Optional, Set, Tuple

from ag.ag_interface import Tokenizer, property_column
from ag.ag_policies.tools.channel import CHANNEL
from .config import ProactiveContextManagerConfig
from ..tools.history import Entry, Task, Turn
from ..tools.render import fit, fit_task, label, render_messages

@dataclass
class Sections:
    """What `build_sections` produces: the section texts, and where the
    verbatim part starts (the running task's start, or the cut)."""
    sections: List[Tuple[str, str]] = field(default_factory=list)
    open_from_row: int = 0
    through_row: int = 0
    parallel_mark: int = 0


OVERVIEW_HEADER = "# How this history is organised"
REQUESTS_HEADER = "# Every earlier request"
EARLIER_HEADER = "# Earlier messages"
RELATED_HEADER = "# Related earlier tasks"
PREVIOUS_HEADER = "# Previous task"
SO_FAR_HEADER = "# This task so far"
SO_FAR_NOTE = ("The task you are in the middle of, from its request to your latest step, condensed to "
               "fit. Carry on from where it leaves off; anything after it is verbatim.")
CLIPPED = "\n\n[...the middle of this section is left out to fit its budget...]\n\n"

OVERVIEW = """\
This session has run for longer than fits here, so the history before the current task
has been put together as the sections below, oldest and least detailed first. The
current task follows them as it happened -- or, if it has run long, its earlier steps are
in the last section, This task so far, and the rest follows as it happened.

The user's messages in these sections are PRUNED: the boilerplate that wraps a request --
a notice repeated on every message, a standard instruction about how or where to deliver
the answer -- is removed, and the words of the request itself are kept exactly. The exact
original of every message is in the `events` table, under the same `[id N]`; the pruned
text is in the `cleaned_messages` table (`row_id` = that N).

1. **Every earlier request** — every message the user sent in this line of work, in
   order, as written (pruned of boilerplate, as above). Complete: nothing is left out or summarised, but what
   was DONE about each request is not here. It also carries the requests made in the
   session's parallel channels, under their own heading. They are tasks given by the same
   user, on the same material. A definition, convention, correction or exclusion the
   user stated there applies to THIS work, and governs the request you are answering
   now as much as one from this channel.
2. **Earlier messages** — the tasks leading up to recent work, whole: the user and
   assistant messages, no tool calls.
3. **Related earlier tasks** — whole tasks from further back, here or in a parallel
   channel, chosen for their bearing on the current work. Re-chosen as the work moves
   on, which is why section 1 keeps every request regardless.
4. **Previous task** — the task worked on just before the current one, in full,
   including its tool calls and their output.
5. **This task so far** — present only when the current task has run long: its request
   and its steps up to a point, condensed to fit. Everything after that point follows
   as it happened.

A task in 2, 3 or 4 still has its requests in section 1. That is deliberate.

Requests the user made in a parallel channel after these sections were put together are
not in them: each is a separate message, right before the request you are answering. They
have the same standing as the parallel requests in section 1.

HOW TO READ A TASK. Each opens with its name, one sentence on what it did, and then any
of four labelled lines recording what the user ESTABLISHED in it. Those lines are
standing decisions from earlier in this same session, and apply to the request you are
answering now unless it overrides them.

  handling: <what it governs> — how an object must be treated: read, filtered,
    cleaned, counted, joined, built, run, edited or named. Apply it wherever your
    work touches what it governs, even if the request does not mention it.
  term: <the word> — what that word means in this session. Use this meaning.
  about: <an object> — a fact the user stated about that object. Treat it as true.
  standing: <what it applies to> — a decision the user said to keep using. If what
    it applies to covers this request, follow it.

Where two conflict, the more specific scope wins, and a later turn overrides an earlier
one."""

DB_HINT = """

Every item is labelled `[id N]`. The full history -- including everything these
sections leave out -- is in the SQLite database

    {db_path}

table `events`, one row per event, `ORDER BY row_id` for order: `row_id` (the N of
`[id N]`), `{channel_column}` (NULL = shared by every channel), `event_type_id` (a row of
`event_types`: its `name` -- user_message / agent_message / tool_call /
tool_output / context / agent_reasoning, your own reasoning, encrypted), `text` (what the
event says: a message's words, a call's name and arguments, an output; NULL for one with
nothing to read) and `payload_json` (the event itself, in full). Anything you cannot find
here is worth looking for there before concluding it did not happen:

    sqlite3 {db_path} "SELECT e.row_id, t.name, coalesce(e.text, e.payload_json) FROM events e JOIN event_types t USING (event_type_id) WHERE e.row_id BETWEEN A AND B ORDER BY e.row_id;\""""


def overview(cfg: ProactiveContextManagerConfig, db_path: Optional[str]) -> str:
    text = f"{OVERVIEW_HEADER}\n\n{OVERVIEW}"
    if cfg.db_hint and db_path:
        text += DB_HINT.format(db_path=db_path, channel_column=property_column(CHANNEL))
    return text


def every_earlier_request(turns: List[Turn], stop_row: int, other: List[Tuple[Optional[str], Entry]],
                          cfg: ProactiveContextManagerConfig, tok: Tokenizer) -> str:
    """This channel's user requests before `stop_row`, then the other
    channels' requests."""
    lines = [REQUESTS_HEADER, "", "Every request the user made in this line of work, in "
             "order, as they wrote them."]
    used = tok.count("\n".join(lines))
    mine = [t.entries[0] for t in turns if t.first_row < stop_row]
    for n, e in enumerate(mine):
        line = f"{label(e)} USER: {e.text}"
        cost = tok.count(line)
        if used + cost > cfg.all_task_tokens:
            left = mine[n:]
            lines.append(f"[{len(left)} later requests omitted: ids {left[0].row_id}-"
                         f"{left[-1].row_id} — read them from the `events` table]")
            break
        lines.append(line)
        used += cost
    block = index_block(other, cfg.parallel_index_tokens, tok)
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
        note = "" if task.channel_id == own_channel else \
            f" — from parallel channel {str(task.channel_id)[:8]}"
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
# channel's latest request (the policy's `parallel_requests`). The requests
# themselves come from `tools/history.other_requests`.

INDEX_HEADER = "## Requests made in parallel sessions"


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
            lines.append(f"[{len(left)} later requests omitted: ids "
                         f"{left[0][1].row_id}-{left[-1][1].row_id} — read them from the `events` table]")
            break
        lines.append(line)
        used += cost
    return "\n".join(lines)


def build_sections(turns: List[Turn], tasks: List[Task], ranked: List[Task],
                   earlier: Tuple[str, Set[int]], other_requests, turns_by_channel: Dict,
                   own_channel, cfg: ProactiveContextManagerConfig, tok: Tokenizer, db_path: Optional[str],
                   through_row: int, parallel_mark: int, cut_row: Optional[int] = None) -> Sections:
    """The sections for a channel with at least one task.

    `ranked` are the related-task candidates, most relevant first (the policy
    has already left out the running, previous and earlier-messages tasks). `earlier` is
    `earlier_messages(tasks[:-2], ...)`. `cut_row`, a row inside the running task, moves the
    verbatim part's start there: the steps before it become "This task so far". Every section
    is within its budget (`clip`); the overview, the agent's view of how the sections work, is
    the sections' fixed preamble and is not counted.
    """
    running = tasks[-1]
    previous = tasks[-2] if len(tasks) > 1 else None
    cut = max(cut_row or running.first_row, running.first_row)
    earlier_text, earlier_set = earlier
    reproduced = ([previous.first_row] if previous else [running.first_row]) + \
        [tasks[i].first_row for i in earlier_set]
    out = Sections(open_from_row=cut, through_row=through_row, parallel_mark=parallel_mark)
    requests = every_earlier_request(turns, min(reproduced), other_requests, cfg, tok)
    out.sections.append(("requests", overview(cfg, db_path) + "\n\n" +
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
