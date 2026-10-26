"""codex's request items as the context manager's events -- the policy-
specific half of the codex harness, with `to_messages.py` (the way back).

    events = to_events(items)            # what the hook's routing sends in a `rewrite`

An event is `{"type", "id", "payload", "tokens"?, "text"?}` (ag/ag_harness/server):
the item is the payload, as it is; what it is, codex's rules say (harness_kit/codex.py:
a Part of a Kind), and the event type each Kind becomes, the adaptor
(`HarnessAdaptor.event_types`: the standard five, and `agent_reasoning`); its id
is codex's own, else a hash of its content; its text is what the model reads of
it (`text_of`): a message's words, a tool call's name and arguments, a tool's
output -- not codex's ids, turn metadata, status or wrappers, which the API never
shows the model. A reasoning item costs 0 tokens and has no text: its content is
an encrypted blob, sent back to the model as it is, but nothing to read or count.

After codex compacts its history, it starts its input again: its preamble re-sent
under new ids, the user messages it kept, and its encrypted summary (a
`compaction` item), then what comes after. None of that up to the summary is an
event: the gatherer holds the history the summary stands for, and built in its
place (the hook's `compaction`). Nor is the compaction call's own `compaction_trigger`.

Nothing of the context manager is imported here.
"""

import hashlib
import json
from typing import Dict, List

from harness_kit import Kind, codex as rules
from harness_kit.codex import (COMPACTED, PREAMBLE_MARKERS, TRIGGER, is_harness_context,  # noqa: F401 - the rules, as
                               text_of)                                                    # this module had them

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

HARNESS = rules.Codex()
#: Codex item type -> event type name, as the rules' Kinds become them. None = a message: the item's `role` decides
#: (ROLE_TYPES).
CODEX_TYPES = {kind: (None if k is None else EVENT_TYPES.get(k, CONTEXT)) for kind, k in rules.ITEM_KINDS.items()}
#: A message's role -> its event type.
ROLE_TYPES = {role: EVENT_TYPES.get(k, CONTEXT) for role, k in rules.ROLES.items()}


def classify(item, event_types: Dict[str, str] = EVENT_TYPES) -> str:
    """The name of a codex item's event type: its Kind's (`harness_kit.codex.kind_of`). Never raises: anything it does
    not know is CONTEXT -- carried as it is, never conversation, and always one of the types the adaptor declares."""
    return event_types.get(rules.kind_of(item), CONTEXT)


def item_id(item) -> str:
    """A stable id for a codex item: codex's own `id`, else one derived from
    the item's content.

    Codex keeps an item's `id` on every re-send, but some items (tool
    definitions, compaction summaries, older threads) arrive without one.
    `sha256:<hash of the item's JSON, keys sorted>` keeps them to one copy --
    at the cost that two identical id-less items are one."""
    value = item.get("id") if isinstance(item, dict) else None
    if isinstance(value, str) and value:
        return value
    raw = json.dumps(item, sort_keys=True, ensure_ascii=False)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def event(item, kind: str = None) -> dict:
    """The event a codex item is (of type `kind`; None: `classify`'s), with its text when it has one (`text_of`). A
    reasoning item costs 0 tokens: its `encrypted_content` is an opaque blob of roughly constant size whatever the
    reasoning was, which says nothing of what it costs."""
    out = {"type": kind or classify(item), "id": item_id(item), "payload": item}
    text = text_of(item)
    if text is not None:
        out["text"] = text
    if isinstance(item, dict) and item.get("type") == "reasoning":
        out["tokens"] = 0
    return out


def after_compaction(items: list) -> list:
    """The items after codex's summary of its compacted history (`COMPACTED`) -- the last one, if any is there -- with no
    compaction trigger: what is new since; all of them when it compacted nothing."""
    return [items[i] for i in rules.after_compaction(items)[1]]


def to_events(items: list, event_types: Dict[str, str] = EVENT_TYPES) -> List[dict]:
    """The events codex's request items are, in order: those after its summary of a compacted history
    (COMPACTION_REPEAT, the summary itself, and its trigger left out). `event_types`: which event type each Kind
    becomes (HarnessAdaptor's)."""
    items = HARNESS.items(items)
    parts = HARNESS.read(items)
    keep = rules.after_compaction(items)[1]
    return [event(items[i], event_types.get(parts[i].kind, CONTEXT)) for i in keep]
