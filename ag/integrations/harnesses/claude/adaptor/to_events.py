"""Claude Code's messages as the context manager's events -- the policy-specific
half of the claude harness, with `to_messages.py` (the way back).

    events = to_events(messages)        # what the hook's routing sends in a `rewrite`

Claude Code speaks the Anthropic Messages API: a request's `messages` are
`{"role", "content"}`, the content a string or a list of blocks -- `text`,
`image`, `tool_use`, `tool_result`, `thinking`, `redacted_thinking` -- and the
role `user`, `assistant`, or `system` (Claude Code puts its environment notes in
a system-role message of the list). One message carries several blocks where the
policies expect an event each (a user turn's system reminders and its request;
an assistant's thinking, words and tool calls), so a message is split into
PIECES, one per block -- the message with that block alone -- and each piece is
typed by its block:

    user text            USER_MESSAGE, or CONTEXT when it is Claude Code's own
                         (a `<system-reminder>`, a command's caveats or output, a skill's
                         instructions, a subagent's report); a command the user typed
                         that Claude Code expands into a prompt is theirs, and the
                         prompt Claude Code's (`types_of`)
    user image           USER_MESSAGE
    tool_result          TOOL_OUTPUT
    assistant text       AGENT_MESSAGE
    tool_use             TOOL_CALL
    thinking             AGENT_REASONING (0 tokens, no text: kept and sent back, never read)
    a system message     CONTEXT

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

import copy
import hashlib
import json
import re
from typing import Dict, Iterable, List, Optional, Set, Tuple

USER_MESSAGE, AGENT_MESSAGE, TOOL_CALL, TOOL_OUTPUT, CONTEXT = (
    "user_message", "agent_message", "tool_call", "tool_output", "context")
AGENT_REASONING = "agent_reasoning"
#: Every event type to_events makes, and nothing else.
OUTPUTS = (USER_MESSAGE, AGENT_MESSAGE, TOOL_CALL, TOOL_OUTPUT, CONTEXT, AGENT_REASONING)

# Claude Code's notes to the model after a response that went wrong -- a safety classifier stopped it,
# it was cut off mid-stream or at the output limit, its tool call could not be parsed -- or that sends
# it back to work (a goal check-in): sent in the user's name, as a message of their own. Claude Code
# 2.1.310 tells them from the user's words by these openings and, the rest, by their whole text; so does
# this adaptor (RETRY_OPENINGS in HARNESS_MARKERS, RETRY_NOTES in HARNESS_TEXTS).
RETRY_OPENINGS = ("[structured-output-enforce]", "[projects-reply-gate]",
                  "You ended the turn without calling SendUserMessage.", "Goal check-in: «")
_CLASSIFIER = ("Your response above was stopped by a safety classifier — this is not a tool or API error. The rest "
               "of it was withheld, and tool calls in it that had not finished did not run. Do not produce that "
               "content again, even reworded.")
RETRY_NOTES = (
    "The previous response failed to produce a valid tool call. Please retry the tool call now.",
    "Your tool call was malformed and could not be parsed. Please retry.",
    "[Your previous response had no visible output. Please continue and produce a user-visible response.]",
    "The PermissionDenied hook indicated you may retry this tool call.",
    "The turn did not end: a tool call in your last message asked to end it, but another call in that message "
    "failed. Deal with the failure, then finish the turn. The calls that succeeded took effect, so do not repeat them.",
    _CLASSIFIER,
    _CLASSIFIER + ' Exception: a tool call whose result reads "Interrupted" was already running when the response '
    "was stopped; it may have partially or fully completed.",
    "Output token limit hit. Resume directly — no apology, no recap of what you were doing. Pick up mid-thought if "
    "that is where the cut happened. Break remaining work into smaller pieces.",
    "Output token limit hit while you were still reasoning, before this response produced any text or tool call. "
    "That reasoning was not kept and is not part of this conversation, so there is nothing to resume. Continue from "
    "the conversation above: reason much more briefly and produce your answer or next tool call well within the "
    "output limit.",
    "[Your previous response reached the output limit with no visible output. Please continue and produce a brief "
    "user-visible response or tool call right away.]",
    "Your response was cut off because it exceeded the output token limit. Continue from where you left off. What "
    "you write next is shown as a separate block below the text so far, so begin at the start of the line, table "
    "row, list item or sentence that was cut, writing it again in full, and if you were inside a code block or a "
    "table, open it again first (the same code fence and language, the table's header row). Repeat nothing before "
    "that point and do not comment on the interruption. Keep going until the response is complete.",
    "Your response above was cut off mid-stream. Resume directly from where it stops — no apology, no recap. If "
    "none of it survived, answer the request from the start.",
    "Your response above was cut off mid-stream and only your next message is delivered. Write the complete "
    "response again from the start — no apology, no mention of the cut-off.")

# Claude Code's own text, sent in the user's name: a user text block starting with one of these is
# CONTEXT, not USER_MESSAGE -- the user did not say it. Besides its reminders and command output:
# its notes on an attachment, put after it (an image read through a tool, shrunk to fit: "[Image:
# original 1400x2400, displayed at 1167x2000. Multiply coordinates by 1.20 ...]"), not the "[Image
# #1]" it writes into the user's own words where an image was pasted; its note that the user
# stopped a turn ("[Request interrupted by user]", before the user's next words); the output of a
# command the user ran with `!` (its `<bash-stdout>`; the `<bash-input>`, what the user typed, is
# theirs); its summary of a compacted conversation, which opens the history after it ("This
# session is being continued from a previous conversation that ran out of context. ..."); a skill's
# instructions, loaded by the Skill tool or by the user's /name ("Base directory for this skill:
# ..."); a message from another session -- a subagent's report as it hands back ("Another Claude
# session sent a message:\n<agent-message from=...>"); its copy for the model of what /context
# shows ("## Context Usage ..."); a hook's reason for not letting the turn end ("Stop hook feedback:
# \n..."); the notes of RETRY_OPENINGS; and its note that the user declined its Chrome extension.
HARNESS_MARKERS = ("<system-reminder>", "<local-command-caveat>", "<local-command-stdout>",
                   "<local-command-stderr>", "<command-name>", "<command-message>", "<command-args>",
                   "Caveat: The messages below were generated by the user while running local commands",
                   "[Image: original ", "[Image: source: ", "[Image source: ", "[Image could not be processed",
                   "[Image left out:", "[Image not shown, read it from ", "[Document removed:",
                   "[Request interrupted by user", "<bash-stdout>", "<bash-stderr>",
                   "This session is being continued from a previous conversation that ran out of context",
                   "Base directory for this skill:", "Another Claude session sent a message:", "<agent-message ",
                   "## Context Usage\n", "Stop hook feedback:\n", "TeammateIdle hook feedback:\n",
                   "TaskCreated hook feedback:\n", "TaskCompleted hook feedback:\n",
                   "The user declined to install the Claude in Chrome extension") + RETRY_OPENINGS
SKILL = "Base directory for this skill:"
# A command the user typed that Claude Code expands into a prompt -- a skill's /name, a command file's:
# Claude Code sends the line typed as "<command-message>greet</command-message>\n<command-name>/greet
# </command-name>\n<command-args>Bob</command-args>", then the prompt it expands to (the skill's
# instructions, the file's text). The line is the user's message, read as they typed it ("/greet Bob");
# the prompt is Claude Code's (`types_of`). A command Claude Code runs itself (/context, /model) opens
# with <command-name> and is followed by its output: its own, as its other notes are.
TYPED_COMMAND = re.compile(r"\s*<command-message>[^<]*</command-message>\s*<command-name>([^<]*)</command-name>"
                           r"\s*(?:<command-args>([\s\S]*?)</command-args>)?\s*$")
# Claude Code's own text that is a whole block, word for word: its note after a tool search's result,
# in the message of the results, that the tools found are loaded ("Tool loaded."), and RETRY_NOTES.
HARNESS_TEXTS = ("Tool loaded.",) + RETRY_NOTES

BLOCK_TYPES = {"text": None, "image": USER_MESSAGE, "document": USER_MESSAGE, "tool_result": TOOL_OUTPUT,
               "tool_use": TOOL_CALL, "server_tool_use": TOOL_CALL, "thinking": AGENT_REASONING,
               "redacted_thinking": AGENT_REASONING}


def without_cache_control(value):
    """`value` with every `cache_control` key taken out, at any depth."""
    if isinstance(value, dict):
        return {k: without_cache_control(v) for k, v in value.items() if k != "cache_control"}
    if isinstance(value, list):
        return [without_cache_control(v) for v in value]
    return value


def blocks_of(message) -> list:
    """A message's content as blocks: a string is one text block."""
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [b for b in content or [] if isinstance(b, dict)]


def pieces(messages: list) -> List[dict]:
    """The items a message list is: each message split into one piece per content block, in
    order, without cache_control, and with its role and content alone. A message's other fields
    (Claude Code puts `output_config`, its effort, on its last message) belong to the request, not
    the conversation: they are not stored, and to_messages.py puts the request's back on its last
    message. A message with no blocks is one piece as it is."""
    out = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        m = {k: v for k, v in without_cache_control(m).items() if k in ("role", "content")}
        blocks = blocks_of(m)
        if not blocks:
            out.append(m)
            continue
        for b in blocks:
            out.append({**m, "content": [b]})
    return out


def is_harness_text(text: str) -> bool:
    text = text.strip()
    return not text or text.startswith(HARNESS_MARKERS) or text in HARNESS_TEXTS


def classify(item) -> str:
    """The name of a piece's event type. Never raises: anything it does not know is CONTEXT."""
    if not isinstance(item, dict):
        return CONTEXT
    role = item.get("role")
    if role == "system":
        return CONTEXT
    blocks = blocks_of(item)
    if not blocks:
        return CONTEXT
    kind = blocks[0].get("type")
    if kind == "text":
        if role == "assistant":
            return AGENT_MESSAGE
        return CONTEXT if is_harness_text(str(blocks[0].get("text") or "")) else USER_MESSAGE
    return BLOCK_TYPES.get(kind) or CONTEXT


def typed_command(item) -> Optional[str]:
    """The command a piece says the user typed, as they typed it ("/greet Bob"), when it is one Claude
    Code expands into a prompt (TYPED_COMMAND); else None."""
    blocks = blocks_of(item) if isinstance(item, dict) and item.get("role") == "user" else []
    m = TYPED_COMMAND.match(str(blocks[0].get("text") or "")) if len(blocks) == 1 and blocks[0].get("type") == "text" else None
    if not m:
        return None
    name, args = m.group(1).strip(), (m.group(2) or "").strip()
    name = name if name.startswith("/") else "/" + name
    return f"{name} {args}" if args else name


def types_of(items: list) -> Tuple[List[str], Set[int]]:
    """Each piece's event type, as `classify` has it -- but a command the user typed that Claude Code
    expands into a prompt is the user's message, and the prompt it expands to, the first of the user's
    words after it before the agent says anything (a skill's instructions are Claude Code's already),
    Claude Code's -- and the indexes of those prompts."""
    types = [classify(it) for it in items]
    expansions: Set[int] = set()
    for k, it in enumerate(items):
        if typed_command(it) is None:
            continue
        types[k] = USER_MESSAGE
        for j in range(k + 1, len(items)):
            if not isinstance(items[j], dict) or items[j].get("role") == "assistant":
                break
            blocks = blocks_of(items[j])
            skill = bool(blocks) and blocks[0].get("type") == "text" and str(blocks[0].get("text") or "").lstrip().startswith(SKILL)
            if skill or types[j] == USER_MESSAGE:
                types[j] = CONTEXT
                expansions.add(j)
                break
    return types, expansions

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


def _result_text(content) -> str:
    if isinstance(content, str):
        return content
    out = []
    for b in content or []:
        if isinstance(b, dict):
            if isinstance(b.get("text"), str):
                out.append(b["text"])
            elif b.get("type") in ("image", "document"):
                out.append(f"[{b['type']}]")
    return "\n".join(out)


def text_of(item) -> Optional[str]:
    """What the model reads of a piece, without the API's bookkeeping; None for thinking (an
    opaque or omitted blob) or a shape Claude Code does not make -- its JSON then stands in.

        text                its words
        image, document     [image], [document]
        tool_use            name(input as JSON)
        tool_result         the result's text (prefixed `error: ` when it is one)
        tool_addition       `tool added: <name>: <description>` and its input schema as JSON
                            (Claude Code's notice that tool search, or a connector, made a tool
                            available: the model gets its whole definition)
        tool_removal        `tool removed: <name>`
    """
    if not isinstance(item, dict):
        return None
    blocks = blocks_of(item)
    if not blocks:
        return None
    b = blocks[0]
    kind = b.get("type")
    if kind == "text":
        return str(b.get("text") or "")
    if kind in ("image", "document"):
        return f"[{kind}]"
    if kind in ("tool_use", "server_tool_use"):
        return f"{b.get('name')}({json.dumps(b.get('input'), ensure_ascii=False)})"
    if kind == "tool_result":
        text = _result_text(b.get("content"))
        return ("error: " + text) if b.get("is_error") else text
    if kind in ("tool_addition", "tool_removal"):
        tool = b.get("tool") if isinstance(b.get("tool"), dict) else {}
        definition = tool.get("definition") if isinstance(tool.get("definition"), dict) else tool
        name = definition.get("name") or tool.get("name")
        if not name:
            return None
        if kind == "tool_removal":
            return f"tool removed: {name}"
        text = f"tool added: {name}" + (f": {definition['description']}" if definition.get("description") else "")
        schema = definition.get("input_schema")
        return text + (f"\n{json.dumps(schema, ensure_ascii=False)}" if schema else "")
    return None


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


#: How the summary Claude Code goes on from after compacting its history opens: not an event -- the
#: gatherer holds the history it summarizes, and built in its place (the hook's `compaction`).
COMPACTED = "This session is being continued from a previous conversation that ran out of context"


def is_compacted_summary(item) -> bool:
    """Whether a piece is the summary Claude Code goes on from after compacting its history."""
    blocks = blocks_of(item) if isinstance(item, dict) and item.get("role") == "user" else []
    return len(blocks) == 1 and blocks[0].get("type") == "text" and \
        str(blocks[0].get("text") or "").lstrip().startswith(COMPACTED)


def compacted_opening(items: list, typed: Optional[Tuple[List[str], Set[int]]] = None) -> set:
    """The pieces Claude Code sends with a compacted history that are not the conversation (by index):
    when the history opens with its summary (`COMPACTED`), the summary and every note of its own up to
    the first reply to the user's first words after it -- its reminders and environment notes again,
    the /compact command's lines, the files it read before restored ("Called the Read tool ..."), its
    tools announced again. The gatherer holds the history they stand for, and built in its place; what
    the conversation said there (the reply it kept, the user's words, the prompt a command they typed
    expands to) stays. Nothing, for a history that does not open with the summary. `typed`: types_of(items),
    when known."""
    if not items or not is_compacted_summary(items[0]):
        return set()
    types, expansions = typed or types_of(items)
    asked = next((i for i, t in enumerate(types) if i and t == USER_MESSAGE), len(items))
    end = next((i for i in range(asked + 1, len(items)) if items[i].get("role") == "assistant"), len(items))
    return {0} | {i for i in range(1, end) if types[i] == CONTEXT and i not in expansions}


def to_events(messages: list, continuity: Optional[Continuity] = None) -> List[dict]:
    """The events Claude Code's messages are, in order -- but for its notes after the user's last
    request, moved before it (`request_last`), and, after it compacted its history, its summary and
    the notes it sent with it, left out (`compacted_opening`). With the channel's `continuity`, only
    from the previous request's last pieces on (see the module's doc)."""
    items = pieces(copy.deepcopy(messages))
    ids, start = continuity.ids(items) if continuity is not None else (chain_ids(items), 0)
    types, expansions = typed = types_of(items)
    dropped = compacted_opening(items, typed)
    return request_last([event(items[k], ids[k], types[k]) for k in range(start, len(items)) if k not in dropped],
                        frozenset(ids[k] for k in expansions))
