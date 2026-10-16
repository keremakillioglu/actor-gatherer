"""The context manager's answer as codex's input items -- the policy-
specific half of the codex harness, with `to_events.py` (the way in).

    items = to_messages(answer["context"], items)   # what codex's model gets as `input`

The context is the events the policy kept, as they were sent, and the
context manager's own messages, `{"type": "ag", "name", "text"}`
(ag/ag_harness/server). An event comes back as its payload, as it was
sent; an `ag` message as a developer message (or, with AG_CODEX_AG_ROLE=user,
a user message marked <contextual_information>). Nothing of the context manager
is imported here.
"""

import os
from typing import Optional

AG = "ag"

# The role the context manager's messages are sent in: developer (the default), or user -- for an
# endpoint that moves developer messages out of the history (into a top-level system instruction), so
# a notice loses its place. A user message stays in place, marked as context, not the user's words.
ROLE_ENV = "AG_CODEX_AG_ROLE"
USER_MARKER = ("<contextual_information>", "</contextual_information>")


def ag_message(text: str) -> dict:
    """The context manager's text as an input item: a developer message, or -- with AG_CODEX_AG_ROLE=user
    -- a user message with the text inside <contextual_information></contextual_information>."""
    if os.environ.get(ROLE_ENV, "developer").strip().lower() == "user":
        return {"type": "message", "role": "user",
                "content": [{"type": "input_text", "text": f"{USER_MARKER[0]}\n{text}\n{USER_MARKER[1]}"}]}
    return {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": text}]}


def to_messages(context: list, items: Optional[list] = None) -> list:
    """The context as codex's input items: each event's payload as it was
    sent, each `ag` message as `ag_message` makes it. (`items`, this call's,
    are not needed: codex's items come back whole.)"""
    out = []
    for entry in context:
        if not isinstance(entry, dict):
            continue
        if entry.get("type") == AG:
            out.append(ag_message(str(entry.get("text") or "")))
        elif "payload" in entry:
            out.append(entry["payload"])
    return out
