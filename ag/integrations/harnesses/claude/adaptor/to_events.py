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
there, in that order. The last such link, searching back from the end, is where the
request carries on: the pieces after it are chained from there -- new, whatever they
repeat -- and only those, and the stored ones linked before them, are sent. Order is
told by the links, not by the rows: notes ag stored before the request they followed
(`request_last`) still link where Claude Code sends them. Without a link (the first
call, Claude Code rewriting the pieces at the end themselves), every piece's id is the
chain from the request's start, which the history re-sent unchanged reproduces.
Nothing of the context manager is imported here.
"""

import hashlib
import json
from typing import Dict, Iterable, List, Optional, Set, Tuple

from harness_kit import Kind, claude as rules
from harness_kit.claude import (COMPACTED, HARNESS_MARKERS, HARNESS_TEXTS, RETRY_NOTES,  # noqa: F401 - the rules, as
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


class Continuity:
    """Where a request carries on from its channel's history as the gatherer stored it: `stored`, the
    channel's last TAIL events as (payload, id), oldest first (the server's `latest`)."""

    def __init__(self, stored: Iterable[Tuple[object, str]] = ()):
        self.known: Dict[str, List[str]] = {}       # piece_key -> the ids it is stored with
        for payload, event_id in stored:
            self.known.setdefault(piece_key(payload), []).append(event_id)

    def ids(self, items: list) -> Tuple[List[Optional[str]], int]:
        """(each piece's id, None for one not sent; the index of the first piece to send). The last piece
        stored with an id that links it to the stored piece before it is where the request carries on: it
        and the stored pieces linked before it keep their ids and are sent, and the pieces after it are
        chained from it. Without one, every id is chained from the request's start and every piece is sent."""
        keys = [piece_key(it) for it in items]
        for end in range(len(keys) - 1, 0, -1):
            run = self.linked(keys, end)
            if run:
                start = end + 1 - len(run)
                ids: List[Optional[str]] = [None] * start + run
                for key in keys[end + 1:]:
                    ids.append(key_id(key, ids[-1]))
                return ids, start
        return chain_ids(items), 0

    def linked(self, keys: List[str], end: int) -> List[str]:
        """The stored ids of the pieces up to `end` that link to one another, back from it -- at least it
        and the one before it -- oldest first; [] if those two do not."""
        run: List[str] = []
        for k in range(end, 0, -1):
            pair = next(([before, this] for this in (run[:1] or self.known.get(keys[k], ()))
                         for before in self.known.get(keys[k - 1], ()) if key_id(keys[k], before) == this), None)
            if pair is None:
                break
            run[:1] = pair
        return run


def event(item, item_id: str, kind: Optional[str] = None) -> dict:
    """The piece as an event of type `kind` (None: as `classify` has it). A command the user typed reads
    as they typed it ("/greet Bob"), not as Claude Code's tags around it."""
    out = {"type": kind or classify(item), "id": item_id, "payload": item}
    text = (typed_command(item) if out["type"] == USER_MESSAGE else None) or text_of(item)
    if text is not None:
        out["text"] = text
    if out["type"] == AGENT_REASONING:
        out["tokens"] = 0
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
    first words after it -- its reminders and environment notes again, the /compact command's lines, the files it read
    before restored ("Called the Read tool ..."), its tools announced again (COMPACTION_REPEAT). The gatherer holds the
    history they stand for, and built in its place; what the conversation said there (the reply it kept, the user's
    words, the prompt a command they typed expands to) stays. Nothing, for a history that does not open with the
    summary."""
    return {i for i, p in enumerate(HARNESS.read(items)) if p.kind == Kind.COMPACTION_REPEAT or p.detail.get("opens")}


def to_events(messages: list, continuity: Optional[Continuity] = None,
              event_types: Dict[str, str] = EVENT_TYPES) -> List[dict]:
    """The events Claude Code's messages are, in order -- but for its notes after the user's last request, moved
    before it (`request_last`), and, after it compacted its history, its summary and the notes it sent with it, left
    out (COMPACTION_REPEAT). With the channel's `continuity`, only from the previous request's last pieces on (see the
    module's doc). `event_types`: which event type each Kind becomes (HarnessAdaptor's)."""
    items = HARNESS.items(messages)
    ids, start = continuity.ids(items) if continuity is not None else (chain_ids(items), 0)
    parts = HARNESS.read(items)
    types = [event_types.get(p.kind, CONTEXT) for p in parts]
    dropped = {i for i, p in enumerate(parts) if p.kind == Kind.COMPACTION_REPEAT or p.detail.get("opens")}
    return request_last([event(items[k], ids[k], types[k]) for k in range(start, len(items)) if k not in dropped],
                        frozenset(ids[k] for k, p in enumerate(parts) if p.detail.get("expands")))
