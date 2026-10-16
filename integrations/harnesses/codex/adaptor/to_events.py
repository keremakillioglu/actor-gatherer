"""codex's request items as the context manager's events -- the policy-
specific half of the codex harness, with `to_messages.py` (the way back).

    events = to_events(items)            # what the hook's routing sends in a `rewrite`

An event is `{"type", "id", "payload", "tokens"?, "text"?}` (ag/ag_harness/server):
the item is the payload, as it is; its type is the name `classify` gives it,
one of the event types the policies expect (the standard five, and
`agent_reasoning`); its id is codex's own, else a hash of its content; its
text is what the model reads of it (`text_of`): a message's words, a tool
call's name and arguments, a tool's output -- not codex's ids, turn metadata,
status or wrappers, which the API never shows the model. A reasoning item
costs 0 tokens and has no text: its content is an encrypted blob, sent back
to the model as it is, but nothing to read or count.

Codex item types are defined in codex-rs/protocol/src/models.rs
(`ResponseItem`). Nothing of the context manager is imported here.
"""

import hashlib
import json
from typing import List, Optional

USER_MESSAGE, AGENT_MESSAGE, TOOL_CALL, TOOL_OUTPUT, CONTEXT = (
    "user_message", "agent_message", "tool_call", "tool_output", "context")
AGENT_REASONING = "agent_reasoning"       # the model's own reasoning, encrypted: kept, never read
#: Every event type to_events makes, and nothing else.
OUTPUTS = (USER_MESSAGE, AGENT_MESSAGE, TOOL_CALL, TOOL_OUTPUT, CONTEXT, AGENT_REASONING)

# Codex item type -> event type name. None = a message: the item's `role`
# decides (ROLE_TYPES). An item type not listed here is CONTEXT.
CODEX_TYPES = {
    "message":                   None,
    "additional_tools":          CONTEXT,                 # tool definitions
    "reasoning":                 AGENT_REASONING,
    "agent_message":             AGENT_MESSAGE,           # a message from another agent
    "compaction":                CONTEXT,                 # codex's summary of dropped history
    "compaction_summary":        CONTEXT,                 # older name codex still accepts
    "context_compaction":        CONTEXT,
    "compaction_trigger":        CONTEXT,                 # marks where compaction happened
    "function_call":             TOOL_CALL,
    "custom_tool_call":          TOOL_CALL,
    "local_shell_call":          TOOL_CALL,
    "tool_search_call":          TOOL_CALL,
    "web_search_call":           TOOL_CALL,               # run by the API; no output item
    "image_generation_call":     TOOL_CALL,               # result is carried in the call
    "function_call_output":      TOOL_OUTPUT,
    "custom_tool_call_output":   TOOL_OUTPUT,
    "tool_search_output":        TOOL_OUTPUT,
}

# A message's role -> its event type. `system` is what the API calls
# developer instructions in older models.
ROLE_TYPES = {"user": USER_MESSAGE, "assistant": AGENT_MESSAGE, "developer": CONTEXT, "system": CONTEXT}

# Codex's own context, sent in USER-role messages. A user message made only of
# these is CONTEXT, not USER_MESSAGE: the user did not say it, so it opens no
# turn. Codex's fragments: core/src/context/contextual_user_message.rs.
PREAMBLE_MARKERS = (
    "# AGENTS.md instructions for ", "</INSTRUCTIONS>", "<environment_context>",
    "<environments_instructions>", "<user_shell_command>", "<skill>", "<skills_instructions>",
    "<goal_context>", "<codex_internal_context", "<subagent_notification>", "<turn_aborted>",
    "<hook_prompt", "<permissions instructions>", "<recommended_plugins>", "<external_",
    "Warning: The maximum number of unified exec processes",
    "Warning: apply_patch was requested via ",
    "Warning: Your account was flagged for potentially high-risk cyber activity",
)


def is_harness_context(item) -> bool:
    """A user-role message made only of codex's own context (or of nothing)."""
    texts = [p.get("text", "") for p in item.get("content") or []
             if isinstance(p, dict) and p.get("type") == "input_text"]
    if not any(t.strip() for t in texts):
        return True
    return all(t.strip().startswith(PREAMBLE_MARKERS) or not t.strip() for t in texts)


def classify(item) -> str:
    """The name of a codex item's event type. Never raises.

    A message (or an item with a role and no type) is typed by its role
    (`ROLE_TYPES`), except a user-role message made only of harness text,
    which is CONTEXT. Any other listed item type has its type
    (`CODEX_TYPES`). Anything else -- an unlisted item type or role, an item
    with neither -- is CONTEXT: carried as it is, never conversation, and
    always one of the types the adaptor declares (OUTPUTS).
    """
    if not isinstance(item, dict):
        return CONTEXT
    kind, role = item.get("type"), item.get("role")
    if kind == "message" or (kind is None and role is not None):
        if role == "user" and is_harness_context(item):
            return CONTEXT
        return ROLE_TYPES.get(role, CONTEXT)
    return CODEX_TYPES.get(kind) or CONTEXT


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


def _parts_text(content) -> str:
    """The words of a message's content (or of a tool output given as parts): its text
    parts, an image as `[image]`."""
    if isinstance(content, str):
        return content
    out = []
    for p in content or []:
        if isinstance(p, str):
            out.append(p)
        elif isinstance(p, dict):
            if isinstance(p.get("text"), str):
                out.append(p["text"])
            elif str(p.get("type", "")).endswith("image"):
                out.append("[image]")
    return "\n".join(out)


def _output_text(output) -> str:
    """A tool output's text: a string as it is, a `{content}` object's content, parts' words."""
    if isinstance(output, str):
        return output
    if isinstance(output, dict) and "content" in output:
        return _output_text(output["content"])
    if isinstance(output, list):
        return _parts_text(output)
    return json.dumps(output, ensure_ascii=False)


def text_of(item) -> Optional[str]:
    """What the model reads of a codex item, without codex's bookkeeping; None when
    it has nothing to read (reasoning, compaction's encrypted summary) or is not a
    shape codex makes -- the payload as JSON then stands in.

        message                      its words (text parts; an image as `[image]`)
        function / custom tool call  name(arguments)
        local shell call             local_shell(the command)
        web search call              web_search(the query)
        any call's output            the output's text
    """
    if not isinstance(item, dict):
        return None
    kind = item.get("type")
    if kind == "message" or (kind is None and "role" in item) or kind == "agent_message":
        return _parts_text(item.get("content"))
    if kind in ("function_call", "custom_tool_call", "tool_search_call"):
        args = item.get("arguments", item.get("input", ""))
        return f"{item.get('name') or kind}({args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)})"
    if kind == "local_shell_call":
        cmd = (item.get("action") or {}).get("command")
        return f"local_shell({' '.join(cmd) if isinstance(cmd, list) else cmd or ''})"
    if kind == "web_search_call":
        return f"web_search({(item.get('action') or {}).get('query') or ''})"
    if kind in ("function_call_output", "custom_tool_call_output", "tool_search_output"):
        return _output_text(item.get("output", item.get("tools")))
    return None


def event(item) -> dict:
    """The event a codex item is, with its text when it has one (`text_of`). A
    reasoning item costs 0 tokens: its `encrypted_content` is an opaque blob of
    roughly constant size whatever the reasoning was, which says nothing of what
    it costs."""
    out = {"type": classify(item), "id": item_id(item), "payload": item}
    text = text_of(item)
    if text is not None:
        out["text"] = text
    if isinstance(item, dict) and item.get("type") == "reasoning":
        out["tokens"] = 0
    return out


def to_events(items: list) -> List[dict]:
    """The events codex's request items are, in order."""
    return [event(item) for item in items]
