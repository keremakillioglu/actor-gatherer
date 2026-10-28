"""Claude Code's messages as the context manager's events -- the policy-specific
half of the claude harness, with `to_messages.py` (the way back).

    events = to_events(messages)        # what the hook's routing sends in a `rewrite`

What Claude Code's messages are is harness_kit's (harness_kit/claude.py): a message
is split into PIECES, one per content block -- the message with that block alone --
and each piece is read as a Part of a Kind: the user's words, the model's, its tool
calls and their results, or one of Claude Code's own notes. Which event type each
Kind becomes is the adaptor's (`HarnessAdaptor.event_types`):

    the user's words     USER_MESSAGE (a command they typed that Claude Code expands
                         into a prompt is theirs, and the prompt Claude Code's)
    the user's image     USER_MESSAGE
    a tool's result      TOOL_OUTPUT
    the model's words    AGENT_MESSAGE
    a tool call          TOOL_CALL
    thinking             AGENT_REASONING (0 tokens, no text: kept and sent back, never read)
    Claude Code's own    CONTEXT (its reminders, a command's caveats or output, a skill's
                         instructions, a subagent's report, a system message)

Anthropic messages have no ids, so to_events gives each piece one: a hash of its
content CHAINED to the id of the piece before it (`chain_ids`). Claude Code re-sends
its whole history, in order, on every call -- it never sees the context the model
was given -- so a piece gets the same id on every re-send and the history is stored
once; and a piece that repeats an earlier one word for word (a user's second
"continue", a tool re-added after its removal) follows other pieces, so it is an
event of its own, not the earlier one again. Claude Code moves its `cache_control`
markers from block to block between calls, so they are taken out of the piece (and
its hash): the same block is the same event wherever the marker sits.

When Claude Code rewrites history further back (its own compaction; or, resuming a
session, its notes at the start: the tools a connector announced mid-session listed
among the deferred ones instead), every chained id after the change would differ, and
the whole history after it would be stored again. A `Continuity` guards against that.
It holds the channel's last TAIL events as the gatherer stored them (the server's
`latest`, read on every call: nothing is remembered between calls, so a hook server
started again, or another one, carries on as well), and finds where they are in the
request by the ids themselves: an id is the hash of its piece and of the id before it,
so two stored events whose ids link pieces next to each other in the request are
there, in that order. The run of such links holding the channel's newest stored event,
the stored history's end, is where the request carries on (on nearly every call it
holds every stored event): the pieces after it are chained from there -- new, whatever
they repeat -- and only those, and the stored ones linked before them, are sent. Not
the last run in the request: Claude Code sends some of its notes again word for word
(resumed, that a connector's tools were removed, then added again), and those stored
earlier link to one another as well; taken for the end, they left the user's message
before them unsent. Notes stored twice are each taken where the longer run goes on.
Where the history's end is not in the request, Claude Code went back, and the case is
told apart (`Continuity.carry_on`) and logged by the hook: a rewind (the user's words
after a run, where the stored history went on otherwise: the fork), a compaction (its
summary in the request; never a run of the notes it sends again with it), its own notes
at the end rewritten, or none of these. Order is told by the links, not by the rows:
notes ag stored before the request they followed (`request_last`) still link where
Claude Code sends them. Without a link (the first call, Claude Code rewriting the pieces
at the end themselves), every piece's id is the chain from the request's start, which
the history re-sent unchanged reproduces.
One rewrite reaches a piece itself: when Claude Code joins two user messages in a row
into one -- a turn that got no answer and the user's next words, or the last message a
compaction summarizes and its instruction -- it adds a newline to the end of the first
one's last text block. A stored user text is found in that form too (`merged_key`); its
id is still checked against the piece as stored.
Nothing of the context manager is imported here.
"""

import hashlib
import json
from typing import Dict, Iterable, List, Optional, Set, Tuple

from harness_kit import Kind, claude as rules
from ag.integrations.tools.ag_orchestrator.adaptor import part_properties
from harness_kit.claude import (COMPACTED, HARNESS_MARKERS, OTHERS_WROTE, HARNESS_TEXTS, RETRY_NOTES,  # noqa: F401 - the rules, as
                                RETRY_OPENINGS, SKILL, TYPED_COMMAND, blocks_of, is_compacted_summary,  # this module
                                is_harness_text, pieces, text_of, typed_command, without_cache_control)  # had them

USER_MESSAGE, AGENT_MESSAGE, TOOL_CALL, TOOL_OUTPUT, CONTEXT = (
    "user_message", "agent_message", "tool_call", "tool_output", "context")
AGENT_REASONING = "agent_reasoning"
#: Every event type to_events makes, and nothing else.
OUTPUTS = (USER_MESSAGE, AGENT_MESSAGE, TOOL_CALL, TOOL_OUTPUT, CONTEXT, AGENT_REASONING)
#: Which event type each Kind of a piece becomes (the adaptor's `event_types`): the user's words (typed commands, a
#: message sent mid-turn, answers to what the harness asked as it worked) a user message; the model's words, reasoning
#: and calls, and the tools' results, their own; any other Kind -- the harness's own notes, a skill's instructions, a
#: subagent's report -- CONTEXT, carried as it is and never conversation.
EVENT_TYPES = {Kind.USER: USER_MESSAGE, Kind.USER_COMMAND: USER_MESSAGE, Kind.MID_TURN: USER_MESSAGE,
               Kind.ASK_REPLY: USER_MESSAGE, Kind.AGENT: AGENT_MESSAGE, Kind.REASONING: AGENT_REASONING,
               Kind.TOOL_CALL: TOOL_CALL, Kind.TOOL_RESULT: TOOL_OUTPUT}
#: The Kinds of the user's own words: what EVENT_TYPES makes a user message.
USER_KINDS = frozenset(k for k, t in EVENT_TYPES.items() if t == USER_MESSAGE)
#: The cases a Continuity falls back to where the stored history's end is not in the request (`carry_on`), as logged.
HOW_FELL_BACK = {"compaction": "Claude Code compacted its history", "rewind": "a rewind",
                 "rewritten": "Claude Code rewrote its own notes at the end", "unknown": "no compaction or rewind in it"}

HARNESS = rules.ClaudeCode()


def classify(item, event_types: Dict[str, str] = EVENT_TYPES) -> str:
    """The name of a piece's event type, by the piece alone (a command the user typed is Claude Code's here: its
    neighbours make it theirs, `types_of`). Never raises: anything it does not know is CONTEXT."""
    return event_types.get(rules.kind_of(item), CONTEXT)


def types_of(items: list, event_types: Dict[str, str] = EVENT_TYPES) -> Tuple[List[str], Set[int]]:
    """Each piece's event type, as its Part reads (`ClaudeCode.read`) -- a command the user typed that Claude Code
    expands into a prompt the user's message, and the prompt it expands to Claude Code's -- and the indexes of those
    prompts."""
    parts = HARNESS.read(items)
    return [event_types.get(p.kind, CONTEXT) for p in parts], {i for i, p in enumerate(parts) if p.detail.get("expands")}

TAIL = 20      # the channel's last stored events a Continuity looks for in the request


def piece_key(item) -> str:
    """The piece's JSON, keys sorted (cache_control already taken out): what makes two pieces the same."""
    return json.dumps(item, sort_keys=True, ensure_ascii=False)


def item_id(item, previous: str = "") -> str:
    """`sha256:` of the id of the piece before it (none: "") and the piece's JSON."""
    return key_id(piece_key(item), previous)


def key_id(key: str, previous: str = "") -> str:
    """item_id, of a piece's `piece_key`."""
    return "sha256:" + hashlib.sha256((previous + "\n" + key).encode("utf-8")).hexdigest()


def chain_ids(items: list) -> List[str]:
    """Each piece's id, chained from the request's start."""
    ids, previous = [], ""
    for item in items:
        previous = item_id(item, previous)
        ids.append(previous)
    return ids


def merged_key(item) -> Optional[str]:
    """The piece_key of a user's text piece as Claude Code sends it joined with the user message after
    it: the newline it adds to the end of the first one's last text block. None: not a user's text."""
    blocks = blocks_of(item) if isinstance(item, dict) and item.get("role") == "user" else []
    if len(blocks) != 1 or blocks[0].get("type") != "text" or not isinstance(blocks[0].get("text"), str):
        return None
    return piece_key({**item, "content": [{**blocks[0], "text": blocks[0]["text"] + "\n"}]})


class Continuity:
    """Where a request carries on from its channel's history as the gatherer stored it: `stored`, the
    channel's last TAIL events as (payload, id), oldest first (the server's `latest`)."""

    def __init__(self, stored: Iterable[Tuple[object, str]] = ()):
        self.known: Dict[str, List[str]] = {}       # piece_key, or its merged_key -> the ids it is stored with
        self.stored: Dict[str, str] = {}            # id -> the piece_key it is the hash of
        self.order: Dict[str, int] = {}             # id -> when it was stored among them: the newest highest
        self.own: Dict[str, bool] = {}              # id -> whether it is Claude Code's own note (CONTEXT)
        self.how: Optional[str] = None              # the case `carry_on` found for the last request
        self.at: Optional[int] = None               # and the index of the first piece new after the run, None: all
        for n, (payload, event_id) in enumerate(stored):
            key = piece_key(payload)
            self.stored[event_id], self.order[event_id], self.own[event_id] = key, n, classify(payload) == CONTEXT
            for k in dict.fromkeys(k for k in (key, merged_key(payload)) if k is not None):
                self.known.setdefault(k, []).append(event_id)

    def ids(self, items: list, parts: Optional[list] = None) -> Tuple[List[Optional[str]], int]:
        """(each piece's id, None for one not sent; the index of the first piece to send). The run of stored
        pieces where the request carries on (`carry_on`; `parts`, the pieces read, if the caller has them) keeps
        its ids and is sent, and the pieces after it are chained from it -- new, whatever they repeat. Without
        one, every id is chained from the request's start and every piece is sent."""
        keys = [piece_key(it) for it in items]
        found = self.carry_on(items, keys, parts)
        self.at = found[0] + len(found[1]) if found else None
        if found is None:
            return chain_ids(items), 0
        start, run = found
        ids: List[Optional[str]] = [None] * start + run
        for key in keys[start + len(run):]:
            ids.append(key_id(key, ids[-1]))
        return ids, start

    def carry_on(self, items: list, keys: List[str], parts: Optional[list]) -> Optional[Tuple[int, List[str]]]:
        """(the index of its first piece, its ids) of the run of stored pieces the request carries on from, case by
        case, the case in `how`; None: from nothing stored, all of it new. First the stored history's end:
          whole, end   the run holding the newest stored event -- of two, the longer, then the later; "whole" when it
                       holds every stored event, as on nearly every call.
        Without it in the request, Claude Code went back, and fell back to what it went back to:
          rewind       the user's words the stored history goes on without come right after a run -- the fork -- or
                       right before one stored after other words (`cut_off`): the fork with the newest stored event;
                       without one (a rewind to the first message), all of it is new.
          compaction   its summary is in the request, and no fork: the run with the newest stored event; without one,
                       all after the summary is new. In a compacted history, never a run of only the notes it sends
                       again with the summary (COMPACTION_REPEAT), whatever the case.
          rewritten    the stored events newer than any in the request are all Claude Code's own notes: it rewrote
                       them (rebuilding its request, its tools to be found by ToolSearch since: their notes made one),
                       or left them out -- the run with the newest stored event.
          unknown      none of these: the same; none of the stored in the request (a rewind further back than they
                       reach, Claude Code rewriting it all), all of it new."""
        self.how = "new"
        if not self.stored:
            return None
        runs = self.runs(keys)
        newest = max(self.order.values())
        rank = lambda r: (max(self.order[i] for i in r[1]), len(r[1]))         # noqa: E731 - ties: the later (max: the first)
        end = max((r for r in runs if rank(r)[0] == newest), key=rank, default=None)
        if end is not None:
            self.how = "whole" if len(end[1]) == len(self.stored) else "end"
            return end
        parts = parts if parts is not None else HARNESS.read(items)
        compacted = any(p.kind == Kind.COMPACTION_SUMMARY for p in parts)
        if compacted:
            runs = [r for r in runs if any(parts[i].kind != Kind.COMPACTION_REPEAT for i in range(r[0], r[0] + len(r[1])))]
        kept = [r for r in runs if not self.cut_off(parts, *r)]
        users = [i for i, p in enumerate(parts) if p.kind in USER_KINDS]
        starts = sorted(s for s, _ in runs) + [len(items)]

        def forks(r) -> bool:                    # the user's words after the run, before the next run
            after, upto = r[0] + len(r[1]), next(s for s in starts if s > r[0])
            return any(after <= i < upto for i in users)
        forks = [r for r in kept if forks(r)]
        if forks or len(kept) < len(runs):
            self.how = "rewind"
            return max(forks, key=rank, default=None)
        best = max(kept, key=rank, default=None)
        newer = [i for i, n in self.order.items() if best is None or n > rank(best)[0]]
        self.how = "compaction" if compacted else \
            "rewritten" if best is not None and all(self.own[i] for i in newer) else "unknown"
        return best

    def runs(self, keys: List[str]) -> List[Tuple[int, List[str]]]:
        """Every run of stored pieces in the request (`linked`, each as long as it goes), as (the index of its first
        piece, its ids), from the request's end back."""
        out, end = [], len(keys) - 1
        while end > 0:
            run = self.linked(keys, end)
            if run:
                out.append((end + 1 - len(run), run))
            end -= len(run) or 1                 # its pieces end no other run
        return out

    def cut_off(self, parts: list, start: int, run: List[str]) -> bool:
        """Whether the user's words come right before the stored run at `start` that its first piece was not stored
        after: what it was stored after is known -- one of the stored, or the start of a request -- and so is not
        there (`linked` would have found it). The user's words came in between: a rewind to them, with Claude Code's
        notes after them as they were after the words they replace."""
        if start == 0 or parts[start - 1].kind not in USER_KINDS:
            return False
        key = self.stored[run[0]]
        return key_id(key) == run[0] or any(key_id(key, before) == run[0] for before in self.stored)

    def fallback(self) -> Optional[str]:
        """What the hook logs when the stored history's end was not in the last request (`how`), else None."""
        if self.how not in HOW_FELL_BACK:
            return None
        where = f"new from piece {self.at} on" if self.at is not None else "all of it new"
        return f"the stored history's end is not in the request: {HOW_FELL_BACK[self.how]}, {where}"

    def linked(self, keys: List[str], end: int) -> List[str]:
        """The stored ids of the pieces up to `end` that link to one another, back from it -- at least it
        and the one before it -- oldest first; [] if those two do not. A piece stored more than once among them
        (Claude Code's notes, sent again word for word) is the one stored that the longest such run goes back
        from -- of two, the newer: a run of the copies stored first stops where the request goes on as it did
        after the second."""
        runs = (self.back(keys, end, this) for this in self.known.get(keys[end], ()))
        return max(runs, key=lambda run: (len(run), self.order[run[-1]]) if run else (0, 0), default=[])

    def back(self, keys: List[str], end: int, this: str) -> List[str]:
        """`linked`, with the piece at `end` taken for the stored `this`."""
        run = [this]
        for k in range(end, 0, -1):
            before = next((b for b in self.known.get(keys[k - 1], ()) if key_id(self.stored[run[0]], b) == run[0]), None)
            if before is None:
                break
            run.insert(0, before)
        return run if len(run) > 1 else []


def event(item, item_id: str, kind: Optional[str] = None, part=None) -> dict:
    """The piece as an event of type `kind` (None: as `classify` has it). A command the user typed reads as they typed it
    ("/greet Bob"), not as Claude Code's tags around it. With its `part` (the rules' reading of it), it carries what
    they read as its properties (`part_properties`)."""
    out = {"type": kind or classify(item), "id": item_id, "payload": item}
    text = (typed_command(item) if out["type"] == USER_MESSAGE else None) or text_of(item)
    if text is not None:
        out["text"] = text
    if out["type"] == AGENT_REASONING:
        out["tokens"] = 0
    found = part_properties(part) if part is not None else {}
    if found:
        out["properties"] = found
    return out


def is_system(event: dict) -> bool:
    """Whether the event is a piece of a system-role message (Claude Code's notes of its own)."""
    payload = event.get("payload")
    return isinstance(payload, dict) and payload.get("role") == "system"


def request_last(events: List[dict], expansions: frozenset = frozenset()) -> List[dict]:
    """`events` with the harness's own notes that follow the user's last request moved before it.

    A read answers the last event of a call, and the policy answers a user's request. Claude Code sends
    its environment notes (a system-role message) AFTER the user's first request, so on a session's
    first call the last event would be those notes. Moved before the request (system-role notes only:
    to_messages.py puts those back where Claude Code sent them; a note inside the request's own
    message, a `!` command's output after the command, stays), they are stored, and shown, ahead of it; their ids are given before the move (to_events), so the history re-sent on
    later calls is stored once all the same. The prompt a command the user typed expands to (by id in
    `expansions`: types_of) stays right after the command, and the notes after it move all the same."""
    last = max((i for i, e in enumerate(events) if e["type"] == USER_MESSAGE), default=None)
    after = events[last + 1:] if last is not None else []
    if not after or any(e["type"] != CONTEXT or not (is_system(e) or e["id"] in expansions) for e in after):
        return events                     # a note in the request's own message (a `!` command's output) stays
    notes = [e for e in after if is_system(e)]
    first = last
    while first > 0 and events[first - 1]["type"] == USER_MESSAGE:
        first -= 1
    return events[:first] + notes + events[first:last + 1] + [e for e in after if not is_system(e)]


def compacted_opening(items: list, typed=None) -> set:
    """The pieces Claude Code sends with a compacted history that are not the conversation (by index): when the history
    opens with its summary (`COMPACTED`), the summary and every note of its own up to the first reply to the user's
    first words after it, or to a note queued in their name that opens the turn instead (another session's message) --
    its reminders and environment notes again, the /compact command's lines, the files it read
    before restored ("Called the Read tool ..."), its tools announced again (COMPACTION_REPEAT). The gatherer holds the
    history they stand for, and built in its place; what the conversation said there (the reply it kept, the user's
    words, the note that opened the turn, the prompt a command they typed expands to) stays. Nothing, for a history that does not open with the
    summary."""
    return {i for i, p in enumerate(HARNESS.read(items)) if p.kind == Kind.COMPACTION_REPEAT or p.detail.get("opens")}


def to_events(messages: list, continuity: Optional[Continuity] = None,
              event_types: Dict[str, str] = EVENT_TYPES) -> List[dict]:
    """The events Claude Code's messages are, in order -- but for its notes after the user's last request, moved
    before it (`request_last`), and, after it compacted its history, its summary and the notes it sent with it, left
    out (COMPACTION_REPEAT). With the channel's `continuity`, only from the previous request's last pieces on (see the
    module's doc). `event_types`: which event type each Kind becomes (HarnessAdaptor's)."""
    items = HARNESS.items(messages)
    parts = HARNESS.read(items)
    ids, start = continuity.ids(items, parts) if continuity is not None else (chain_ids(items), 0)
    types = [event_types.get(p.kind, CONTEXT) for p in parts]
    dropped = {i for i, p in enumerate(parts) if p.kind == Kind.COMPACTION_REPEAT or p.detail.get("opens")}
    return request_last([event(items[k], ids[k], types[k], parts[k]) for k in range(start, len(items)) if k not in dropped],
                        frozenset(ids[k] for k, p in enumerate(parts) if p.detail.get("expands")))
