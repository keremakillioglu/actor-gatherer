"""The context manager's answer as Claude Code's messages -- the policy-specific
half of the claude harness, with `to_events.py` (the way in).

    messages = to_messages(answer["context"], messages)   # the request's new `messages`

The context is the events the policy kept, as they were sent -- the pieces
to_events.py made, one block each -- and the context manager's own messages,
`{"type": "ag", "name", "text"}`. Consecutive pieces of one role are joined
into one message again (the API wants a turn's blocks together, a tool_result
right after its tool_use); an `ag` message is a system-role message, as Claude
Code sends its own environment notes.

The events are stored without `cache_control` (to_events.py), so Claude Code's
cache markers in its messages -- one, on its last message's last block, moved
along each call -- are put back: the same markers, counted from the end, on the
last blocks of the context's last messages. Anthropic caches a request's prefix
up to a marker; without them every call would pay for the whole context again.
The markers on the system prompt and the tools are Claude Code's own and not
touched here. Nor are the fields Claude Code puts on its messages
(`output_config`): to_events.py stores role and content alone, and they go back
on the context's message with the same blocks (`with_fields`). Claude Code's own
system notes, which to_events.py may store before the request they close, go
back where it sent them (`as_sent`). `finish` does all of this.

System-role messages, by `system_messages`: "keep" (the default) sends them as
Claude Code does, but one the API would refuse where it is made user text
(`placed`); "user" sends every one that says something as user-turn
`<system-reminder>` text (`as_user`), for a gateway that moves system messages
into the model's system instruction, where a new one per call would keep the
request from caching. Nothing of the context manager is imported here.
"""

from typing import List, Optional

from .to_events import piece_key, without_cache_control

AG = "ag"


def ag_message(text: str) -> dict:
    """A system-role message carrying the context manager's text."""
    return {"role": "system", "content": [{"type": "text", "text": text}]}


def join(items: List[dict]) -> List[dict]:
    """Items as messages: consecutive items of one role joined, their blocks in order."""
    out: List[dict] = []
    for item in items:
        blocks = item.get("content")
        if isinstance(blocks, str):
            blocks = [{"type": "text", "text": blocks}]
        if out and out[-1].get("role") == item.get("role") and isinstance(blocks, list):
            out[-1] = {**out[-1], "content": list(out[-1]["content"]) + list(blocks)}
        else:
            out.append({**item, "content": list(blocks) if isinstance(blocks, list) else blocks})
    return out


def cache_markers(messages: Optional[list]) -> List[tuple]:
    """(the block it is on, without it; the marker) for each cache_control marker in Claude Code's
    messages, in order."""
    out = []
    for m in messages or []:
        for b in m.get("content") if isinstance(m, dict) and isinstance(m.get("content"), list) else []:
            if isinstance(b, dict) and isinstance(b.get("cache_control"), dict):
                out.append(({k: v for k, v in b.items() if k != "cache_control"}, b["cache_control"]))
    return out


def with_markers(out: List[dict], markers: List[tuple]) -> List[dict]:
    """`out` with Claude Code's cache markers back: each on the block Claude Code put it on, where the
    context still holds that block (its last copy); the rest on the last cacheable blocks (not
    thinking blocks) of the context's last messages, counted from the end."""
    placed_on, left = set(), []
    for block, marker in markers:
        hit = None
        for i in range(len(out) - 1, -1, -1):
            blocks = out[i].get("content")
            if isinstance(blocks, list):
                k = next((k for k in range(len(blocks) - 1, -1, -1) if blocks[k] == block), None)
                if k is not None:
                    hit = (i, k)
                    break
        if hit is None:
            left.append(marker)
            continue
        i, k = hit
        out[i] = {**out[i], "content": [*out[i]["content"][:k], {**block, "cache_control": dict(marker)},
                                        *out[i]["content"][k + 1:]]}
        placed_on.add(i)
    rest = [i for i in range(len(out) - 1, -1, -1) if i not in placed_on]
    for i, marker in zip(rest, reversed(left)):
        blocks = out[i].get("content")
        if not isinstance(blocks, list):
            continue
        for k in range(len(blocks) - 1, -1, -1):
            b = blocks[k]
            if isinstance(b, dict) and b.get("type") not in ("thinking", "redacted_thinking"):
                blocks[k] = {**b, "cache_control": dict(marker)}
                break
    return out


def _flat(messages: Optional[list]) -> List[tuple]:
    """(role, block without cache_control) for every block of `messages`, in order."""
    out = []
    for m in messages or []:
        if not isinstance(m, dict):
            continue
        content = m.get("content")
        blocks = [{"type": "text", "text": content}] if isinstance(content, str) else list(content or [])
        out += [(m.get("role"), without_cache_control(b)) for b in blocks if isinstance(b, dict)]
    return out


def _same(flat: List[tuple], sent: List[tuple], p: int) -> Optional[int]:
    """Where in `flat` the block at `sent[p]` is: the same copy, counted from the end -- a block Claude
    Code sent more than once (a tool re-added, a repeated note) pairs with its own occurrence, and the
    context's end is the request's end -- or None when the context no longer holds that copy."""
    block = sent[p][1]
    later = sum(1 for _, b in sent[p + 1:] if b == block)
    found = [k for k, (_, b) in enumerate(flat) if b == block]
    return found[-(later + 1)] if len(found) > later else None


def as_sent(out: List[dict], messages: Optional[list], whole: bool = False) -> List[dict]:
    """`out` with each of Claude Code's own system-role messages back where Claude Code had it: right
    after the block that came before it in Claude Code's request. to_events.py stores a session's
    first notes before the request (so the read answers the request); shown there, inside the user's
    turn, the model would take them for the user's words. A block Claude Code sent more than once is
    matched copy for copy, counted from the end (`_same`). A system message the context no longer
    holds, or whose neighbour it no longer holds, stays where it is."""
    sent = _flat(messages)
    flat = []                                       # out's blocks; with `whole`, a message with none kept whole
    for m in out:
        blocks = m.get("content")
        if whole and isinstance(blocks, list) and not blocks:
            flat.append((m.get("role"), {"__whole__": m}))
        else:
            flat += _flat([m])
    i = 0
    while i < len(sent):
        role, _ = sent[i]
        if role != "system" or i == 0:
            i += 1
            continue
        j = i
        while j < len(sent) and sent[j][0] == "system":
            j += 1
        notes = [b for _, b in sent[i:j]]
        at = [_same(flat, sent, p) for p in range(i, j)]
        anchor = _same(flat, sent, i - 1)
        if None not in at and anchor is not None and anchor not in at:
            moved = set(at)
            rest = [x for k, x in enumerate(flat) if k not in moved]
            where = anchor - sum(1 for k in moved if k < anchor)
            flat = rest[:where + 1] + [("system", b) for b in notes] + rest[where + 1:]
        i = j
    if not sent:
        return out
    if not whole:
        return join([{"role": r, "content": [b]} for r, b in flat])
    rebuilt, after_whole = [], False
    for r, b in flat:
        if "__whole__" in b:
            rebuilt.append(b["__whole__"])
        elif rebuilt and not after_whole and rebuilt[-1].get("role") == r:
            rebuilt[-1] = {**rebuilt[-1], "content": rebuilt[-1]["content"] + [b]}
        else:
            rebuilt.append({"role": r, "content": [b]})
        after_whole = "__whole__" in b
    return rebuilt


def placed(out: List[dict]) -> List[dict]:
    """`out` with each system-role message the API would refuse where it is -- one neither last nor
    right before an assistant message -- made a user message, joined into the user turn beside it."""
    fixed = []
    for i, m in enumerate(out):
        nxt = out[i + 1] if i + 1 < len(out) else None
        if m.get("role") == "system" and nxt is not None and nxt.get("role") != "assistant":
            m = {**m, "role": "user"}
        fixed.append(m)
    return join(fixed)


REMINDER_OPEN, REMINDER_CLOSE = "<system-reminder>", "</system-reminder>"
SYSTEM_MESSAGES = ("keep", "user")      # how finish() sends system messages: see there


def reminder(block: dict) -> dict:
    """A text block as a system reminder (already one: as it is); any other block as it is."""
    if block.get("type") != "text" or str(block.get("text") or "").lstrip().startswith(REMINDER_OPEN):
        return block
    return {**block, "text": f"{REMINDER_OPEN}\n{block.get('text') or ''}\n{REMINDER_CLOSE}"}


def as_user(out: List[dict]) -> List[dict]:
    """`out` with every system-role message that says something made user text -- each text block a
    `<system-reminder>`, the form Claude Code gives its other notes -- joined into the user turn beside
    it. A system message with no text (an effort directive: `content: []` and `output_config`), or with
    a block that only a system message may hold (tool search's `tool_addition`), is left as it is:
    the API takes it where Claude Code put it. Why: a gateway that moves every system message into the
    model's one system instruction changes the request's front whenever Claude Code adds one, and
    nothing after it is cached; as user text the request only grows at its end."""
    fixed = []
    for m in out:
        blocks = m.get("content")
        if m.get("role") == "system" and isinstance(blocks, list) and blocks \
                and all(isinstance(b, dict) and b.get("type") == "text" for b in blocks) \
                and any(str(b.get("text") or "").strip() for b in blocks):
            m = {"role": "user", "content": [reminder(b) if isinstance(b, dict) else b for b in blocks]}
        fixed.append(m)
    return join(fixed)


def with_fields(out: List[dict], messages: Optional[list]) -> List[dict]:
    """`out` with each of Claude Code's messages' own fields (`output_config`: the effort the turn after
    it ran at) back on the message of the context that holds the same blocks with the same role --
    where `as_sent` has put Claude Code's notes, the fields are valid again. The last message gets the
    request's last message's fields when the roles agree, even if its blocks were joined with others."""
    sent = [m for m in messages or [] if isinstance(m, dict)]
    for m in sent:
        fields = {k: v for k, v in m.items() if k not in ("role", "content")}
        if not fields:
            continue
        blocks = [b for _, b in _flat([m])]
        for i, o in enumerate(out):
            if o.get("role") == m.get("role") and [b for _, b in _flat([o])] == blocks:
                out[i] = {**o, **fields}
                break
    if sent and out and out[-1].get("role") == sent[-1].get("role"):
        out[-1] = {**out[-1], **{k: v for k, v in sent[-1].items() if k not in ("role", "content")}}
    return out


def finish(out: List[dict], messages: Optional[list], system_messages: str = "keep") -> List[dict]:
    """The context's messages made a request's: Claude Code's own system notes back where it sent them
    (`as_sent`), its cache markers put back (`with_markers`), its messages' own fields back on theirs
    (`with_fields`); then the system messages: with `system_messages` "keep" only those the API would
    refuse where they are made user text (`placed`); with "user" every one that says something made
    user-turn system reminders (`as_user`)."""
    if system_messages not in SYSTEM_MESSAGES:
        raise ValueError(f"system_messages: {system_messages!r}, not one of {SYSTEM_MESSAGES}")
    if system_messages == "user":
        return as_user(with_fields(with_markers(as_sent(out, messages, whole=True), cache_markers(messages)), messages))
    return with_fields(with_markers(placed(as_sent(out, messages)), cache_markers(messages)), messages)


INLINE_TOOLS = ("tool_addition", "tool_removal")     # tool search's blocks: the request's state, not history


def only_sent_tools(items: List[dict], messages: Optional[list]) -> List[dict]:
    """`items` with no more of each inline tool block (`tool_addition`, `tool_removal`) than Claude Code's
    request carries, the latest kept. Those blocks say which tools the request offers, and need the beta
    header Claude Code sends with them: a request Claude Code sent without them (its retry of a refused
    call) must not get stored ones back."""
    sent: dict = {}
    for _, b in _flat(messages):
        if b.get("type") in INLINE_TOOLS:
            key = piece_key(b)
            sent[key] = sent.get(key, 0) + 1
    kept = []
    for item in reversed(items):
        blocks = item.get("content")
        b = blocks[0] if isinstance(blocks, list) and len(blocks) == 1 and isinstance(blocks[0], dict) else None
        if b is not None and b.get("type") in INLINE_TOOLS:
            key = piece_key(without_cache_control(b))
            if not sent.get(key):
                continue
            sent[key] -= 1
        kept.append(item)
    return kept[::-1]


def to_messages(context: list, messages: Optional[list] = None, system_messages: str = "keep") -> List[dict]:
    """The context as Claude Code's messages: each event's payload as it was sent, consecutive
    ones of a role joined, each `ag` message a system-role message, inline tool blocks only as the
    request carries them (`only_sent_tools`), finished as a request (`finish`)."""
    items = []
    for entry in context:
        if not isinstance(entry, dict):
            continue
        if entry.get("type") == AG:
            items.append(ag_message(str(entry.get("text") or "")))
        elif isinstance(entry.get("payload"), dict):
            items.append(entry["payload"])
    return finish(join(only_sent_tools(items, messages)), messages, system_messages)
