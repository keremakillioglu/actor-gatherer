"""Codex, as harness_kit reads it (0.164): its model calls (the Responses API), the items of its input,
its own context among them, and its tools.

    calls        a POST to .../responses whose input holds a user message; what each is for, in its turn
                 metadata (the `x-codex-turn-metadata` header, else the body's `client_metadata`):
                 `thread_source` user is the thread's own turn, any other one of codex's side calls --
                 thread_title (a title, its answer {"title"}), system (/recap, {"summary", "next_action"}),
                 a subagent's (`parent_thread_id`), guardian_review, memory_consolidation; `request_kind`
                 compaction, its input ending with a `compaction_trigger`. The thread in the `thread-id`
                 header (then `session-id`, then the body's `prompt_cache_key`); the working directory in
                 the last <environment_context> (its <cwd>, else its first workspace root)
    items        each input item, as it is (codex's items are already one thing each)
    kinds        by the item's type (CODEX_TYPES) -- a message by its role, but a user-role message made
                 only of codex's own context (PREAMBLE_MARKERS) is codex's

Codex item types are defined in codex-rs/protocol/src/models.rs (`ResponseItem`); its own context
fragments in core/src/context/contextual_user_message.rs.
"""

import json
import re
from typing import List, Optional, Tuple

from .base import Action, Call, CallKind, Harness, Kind, Part, ToolCall, ToolResult, output_of

# Codex item type -> Kind. None = a message: its role decides (ROLES). An item type not listed here is OTHER.
ITEM_KINDS = {
    "message":                   None,
    "additional_tools":          Kind.TOOL_NOTICE,        # tool definitions
    "reasoning":                 Kind.REASONING,
    "agent_message":             Kind.PEER_MESSAGE,       # another agent's message to this one (a subagent's report:
                                                          # AGENT_REPORT): codex's, not the model's -- as Claude Code's
    "compaction":                Kind.COMPACTION_SUMMARY, # codex's summary of dropped history
    "compaction_summary":        Kind.COMPACTION_SUMMARY, # older name codex still accepts
    "context_compaction":        Kind.COMPACTION_SUMMARY,
    "compaction_trigger":        Kind.OTHER,              # marks where compaction happened
    "function_call":             Kind.TOOL_CALL,
    "custom_tool_call":          Kind.TOOL_CALL,
    "local_shell_call":          Kind.TOOL_CALL,
    "tool_search_call":          Kind.TOOL_CALL,
    "web_search_call":           Kind.TOOL_CALL,          # run by the API; no output item
    "image_generation_call":     Kind.TOOL_CALL,          # result is carried in the call
    "function_call_output":      Kind.TOOL_RESULT,
    "custom_tool_call_output":   Kind.TOOL_RESULT,
    "tool_search_output":        Kind.TOOL_RESULT,
}
# A message's role -> its Kind. `system` is what the API calls developer instructions in older models.
ROLES = {"user": Kind.USER, "assistant": Kind.AGENT, "developer": Kind.ENVIRONMENT, "system": Kind.ENVIRONMENT}

# Codex's own context, sent in USER-role messages. A user message made only of these is codex's, not the user's:
# the user did not say it, so it opens no turn. Each of the Kind it is.
PREAMBLE = (
    ("# AGENTS.md instructions for ", Kind.ENVIRONMENT), ("</INSTRUCTIONS>", Kind.ENVIRONMENT),
    ("<environment_context>", Kind.ENVIRONMENT), ("<environments_instructions>", Kind.ENVIRONMENT),
    ("<user_shell_command>", Kind.COMMAND_OUTPUT), ("<skill>", Kind.SKILL), ("<skills_instructions>", Kind.ENVIRONMENT),
    ("<goal_context>", Kind.ENVIRONMENT), ("<codex_internal_context", Kind.ENVIRONMENT),
    ("<subagent_notification>", Kind.AGENT_REPORT), ("<turn_aborted>", Kind.INTERRUPT),
    ("<hook_prompt", Kind.HOOK_FEEDBACK), ("<permissions instructions>", Kind.ENVIRONMENT),
    ("<recommended_plugins>", Kind.ENVIRONMENT), ("<external_", Kind.ENVIRONMENT),
    ("Warning: The maximum number of unified exec processes", Kind.OTHER),
    ("Warning: apply_patch was requested via ", Kind.OTHER),
    ("Warning: Your account was flagged for potentially high-risk cyber activity", Kind.OTHER),
)
PREAMBLE_MARKERS = tuple(m for m, _ in PREAMBLE)
#: The user's answers to what codex asked as it worked (request_user_input_async), as codex sends them, one message
#: for each submitted: <send_user_message_question_reply>[{"answer", "question", "questionItemId"}]</...>.
REPLY = "<send_user_message_question_reply>"
REPLIED = re.compile(r"^\s*<send_user_message_question_reply>\s*([\s\S]*?)\s*(?:</send_user_message_question_reply>\s*)?$")
# codex's message from another of its agents (an `agent_message` item: a subagent's report handed back, FINAL_ANSWER;
# any other message between them), as it words it for the model
AGENT_TEXT = re.compile(r"^\s*Message Type: (\w+)\s*\nTask name: [^\n]*\nSender: ([^\n]*)\nPayload:\n?([\s\S]*)$")

#: Codex's summary of the history it compacted: what its input starts again from.
COMPACTED = ("compaction", "compaction_summary", "context_compaction")
TRIGGER = "compaction_trigger"   # the compaction call's last item: what asks for the summary

METADATA = "x-codex-turn-metadata"   # codex's header (and client_metadata key) saying what a call is for
TURN = "user"                         # the thread_source of a thread's own turn; any other is a side call
SIDE_KINDS = {"thread_title": CallKind.TITLE, "system": CallKind.RECAP, "subagent": CallKind.SUBAGENT}
CWD = re.compile(r"<cwd>\s*(.*?)\s*</cwd>", re.S)
ROOT = re.compile(r"<workspace_roots>\s*<root>\s*(.*?)\s*</root>", re.S)
VERSION = re.compile(r"codex_\w+/([\d.]+)")      # its User-Agent: codex_cli_rs/0.164.0

#: Its tools: each one's action, and the input key that names the file it works on.
TOOLS = {"exec_command": (Action.SHELL, None), "shell": (Action.SHELL, None), "shell_command": (Action.SHELL, None),
         "local_shell": (Action.SHELL, None), "apply_patch": (Action.EDIT, None), "write_stdin": (Action.TASK, None),
         "view_image": (Action.READ, "path"), "web_search": (Action.WEB, None), "spawn_agent": (Action.DELEGATE, None),
         "send_message": (Action.DELEGATE, None), "wait": (Action.TASK, None), "update_plan": (Action.OTHER, None),
         "request_user_input": (Action.ASK, None), "request_user_input_async": (Action.ASK, None)}
#: Its tool that asks the user in its terminal, its turn waiting on the answer (Plan mode's); and the one it asks
#: with as its turn goes on.
ASK, ASK_ASYNC = "request_user_input", "request_user_input_async"
#: The item types the dashboard reads as codex's, by shape.
SHAPES = {"message", "function_call", "function_call_output", "custom_tool_call", "custom_tool_call_output",
          "reasoning", "local_shell_call", "web_search_call", "compaction", "compaction_summary"}
SPAWN = "spawn_agent"                 # its tool that starts a subagent


def texts_of(item) -> list:
    """A message's text parts' words."""
    if not isinstance(item, dict):
        return []
    parts = item.get("content")
    if isinstance(parts, str):
        return [parts]
    return [p["text"] for p in parts or [] if isinstance(p, dict) and isinstance(p.get("text"), str)]


def own_context(item) -> Optional[str]:
    """The Kind of codex's own context a user-role message is -- made only of it (PREAMBLE_MARKERS), or of nothing
    (OTHER) -- by its first text that says anything; None: the user's."""
    texts = [p.get("text", "") for p in item.get("content") or []
             if isinstance(p, dict) and p.get("type") == "input_text"]
    if not any(t.strip() for t in texts):
        return Kind.OTHER
    if not all(t.strip().startswith(PREAMBLE_MARKERS) or not t.strip() for t in texts):
        return None
    first = next(t.strip() for t in texts if t.strip())
    return next(kind for marker, kind in PREAMBLE if first.startswith(marker))


def is_harness_context(item) -> bool:
    """A user-role message made only of codex's own context (or of nothing)."""
    return own_context(item) is not None


def kind_of(item) -> str:
    """A codex item's Kind. Never raises: anything it does not know is OTHER."""
    if not isinstance(item, dict):
        return Kind.OTHER
    kind, role = item.get("type"), item.get("role")
    if kind == "message" or (kind is None and role is not None):
        if role == "user":
            own = own_context(item)
            if own is not None:
                return own
            text = "\n".join(texts_of(item))
            return Kind.ASK_REPLY if text.lstrip().startswith(REPLY) else Kind.USER
        return ROLES.get(role, Kind.OTHER)
    return ITEM_KINDS.get(kind) or Kind.OTHER


def _parts_text(content) -> str:
    """The words of a message's content (or of a tool output given as parts): its text parts, an image as `[image]`."""
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
    """What the model reads of a codex item, without codex's bookkeeping; None when it has nothing to read (reasoning,
    compaction's encrypted summary) or is not a shape codex makes.

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


def arguments(raw):
    """A codex call's arguments: a JSON string, read as its object when it is one."""
    if isinstance(raw, str):
        try:
            got = json.loads(raw)
            return got if isinstance(got, dict) else raw
        except ValueError:
            return raw
    return raw


def replied(text: str) -> Optional[List[dict]]:
    """The user's answers in codex's reply to what it asked as it worked (REPLIED): [{answer, question,
    questionItemId}]; None when the text is not one."""
    m = REPLIED.match(text or "")
    if not m:
        return None
    try:
        got = json.loads(m.group(1))
    except ValueError:
        return None
    return [r for r in got if isinstance(r, dict)] if isinstance(got, list) else None


def replies(text) -> bool:
    """Whether a user message is codex's wrapper of answers to what it asked as it worked (REPLY): the user's words,
    sent while the turn that asked runs -- part of that turn, not one of its own."""
    return isinstance(text, str) and text.lstrip().startswith(REPLY)


def report_of(text: str) -> Optional[dict]:
    """What codex's message from another of its agents says (AGENT_TEXT): {kind: AGENT_REPORT, from, text} for a
    subagent's report handed back (FINAL_ANSWER), {kind: PEER_MESSAGE, name, text} for any other; None: not one."""
    m = AGENT_TEXT.match(text or "")
    if not m:
        return None
    if m.group(1) == "FINAL_ANSWER":
        return {"kind": Kind.AGENT_REPORT, "from": m.group(2).strip(), "text": m.group(3).strip()}
    return {"kind": Kind.PEER_MESSAGE, "name": m.group(2).strip(), "text": m.group(3).strip()}


def questions_of(given) -> list:
    """Codex's questions (request_user_input's: {id, header, question, options: [{label, description}]}; the async
    one's: {title, options: [label]}) as ToolCall.ask has them."""
    out = []
    for q in given if isinstance(given, list) else []:
        if not isinstance(q, dict):
            continue
        options = [o if isinstance(o, dict) else {"label": str(o)} for o in q.get("options") or [] if isinstance(o, (dict, str))]
        out.append({"id": q.get("id"), "header": q.get("header"), "question": q.get("question") or q.get("title"),
                    "multiSelect": False, "options": [{"label": o.get("label"), "description": o.get("description")}
                                                      for o in options]})
    return out


def ask_of(name: str, args) -> Optional[dict]:
    if name not in (ASK, ASK_ASYNC):
        return None
    got = args if isinstance(args, dict) else {}
    return {"kind": "question", "async": name == ASK_ASYNC, "questions": questions_of(got.get("questions"))}


def is_model_call(method: str, path: str, body) -> bool:
    """Whether the request is a model call whose input the context manager answers for: a POST to .../responses with
    an input list holding a user message."""
    if method != "POST" or not path.split("?", 1)[0].rstrip("/").endswith("/responses"):
        return False
    if not isinstance(body, dict) or not isinstance(body.get("input"), list):
        return False
    return any(isinstance(i, dict) and i.get("role") == "user" for i in body["input"])


def thread_of(headers, body: dict) -> Optional[str]:
    """The codex thread id the request belongs to, or None."""
    lower = {k.lower(): v for k, v in (headers or {}).items()}
    return lower.get("thread-id") or lower.get("session-id") or body.get("prompt_cache_key") or None


def metadata_of(headers, body: dict) -> dict:
    """What codex says of the call (its turn metadata: thread_source, request_kind, parent_thread_id, ...), from its
    header, else the body's client_metadata; {} when it says nothing."""
    lower = {k.lower(): v for k, v in (headers or {}).items()}
    raw = lower.get(METADATA) or ((body.get("client_metadata") or {}) if isinstance(body.get("client_metadata"), dict)
                                  else {}).get(METADATA)
    try:
        found = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return {}
    return found if isinstance(found, dict) else {}


def side_call(metadata: dict) -> Optional[str]:
    """The kind of codex's own side call this is (its thread_source: thread_title, system, subagent, guardian_review,
    ...), or None: the thread's own turn -- a user source, or none said."""
    source = metadata.get("thread_source")
    if metadata.get("parent_thread_id") and source in (None, TURN):
        source = "subagent"
    return None if source in (None, TURN) else str(source)


def compaction_split(metadata: dict, items: list) -> Optional[Tuple[list, list]]:
    """(the history, the trigger) of a compaction call -- `request_kind` compaction, or an input ending with a
    `compaction_trigger` -- else None."""
    last = items[-1] if items else None
    if isinstance(last, dict) and last.get("type") == TRIGGER:
        return items[:-1], [last]
    if metadata.get("request_kind") == "compaction":
        return items, []
    return None


def answer_object(reply: List[Part]) -> dict:
    """What a side call's answer says, read as the JSON object codex asked for (its output schema): the text of its
    messages; {} when it is not one."""
    text = "".join(p.text or "" for p in reply if p.kind == Kind.AGENT)
    try:
        found = json.loads(text)
    except ValueError:
        return {}
    return found if isinstance(found, dict) else {}


def cwd_of(items: list) -> Optional[str]:
    """The agent's working directory, as the last <environment_context> in the input states it -- its <cwd>, or,
    where codex writes none, the first of its <workspace_roots> -- None if none does."""
    found = None
    for item in items:
        for text in texts_of(item):
            if "<environment_context>" in text:
                match = CWD.findall(text) or ROOT.findall(text)
                if match:
                    found = match[-1]
    return found


def after_compaction(items: list) -> Tuple[int, list]:
    """(where what is new since codex's summary of its compacted history starts, the indexes of the items from then on
    that are not a compaction trigger): after the last summary (`COMPACTED`), if any is there; all of them when it
    compacted nothing."""
    at = max((i for i, item in enumerate(items) if isinstance(item, dict) and item.get("type") in COMPACTED), default=-1)
    return at, [i for i in range(at + 1, len(items)) if not (isinstance(items[i], dict) and items[i].get("type") == TRIGGER)]


class Codex(Harness):
    name = "codex"
    label = "Codex"
    checked_with = "0.164.0"
    NAME_CHARS = 120                 # the longest title kept (codex asks for 36 characters at most)

    def call(self, method: str, path: str, headers, body) -> Optional[Call]:
        """The request as a model call (module doc), None if it is not one; `detail["metadata"]`, what codex said of it,
        and `detail["source"]`, the side call's own name for one."""
        if not is_model_call(method, path, body):
            return None
        metadata = metadata_of(headers, body)
        agent = next((str(v) for k, v in (headers or {}).items() if k.lower() == "user-agent"), "")
        found = VERSION.search(agent)
        items = body["input"]
        out = Call(CallKind.TURN, thread_of(headers, body), cwd_of(items), found.group(1) if found else None,
                   history=items, detail={"metadata": metadata})
        source = side_call(metadata)
        if source is not None:
            out.kind, out.detail["source"] = SIDE_KINDS.get(source, CallKind.OTHER), source
            return out
        split = compaction_split(metadata, items)
        if split is not None:
            out.kind, out.history, out.own = CallKind.COMPACTION, split[0], split[1]
        return out

    def title(self, reply: List[Part]) -> Optional[str]:
        text = " ".join(str(answer_object(reply).get("title") or "").split())[:self.NAME_CHARS]
        return text or None

    def recap(self, reply: List[Part]) -> Optional[str]:
        got = answer_object(reply)
        summary, then = str(got.get("summary") or "").strip(), str(got.get("next_action") or "").strip()
        text = summary + (f"\n\nNext: {then}" if summary and then else "")
        return text or None

    def items(self, history: list) -> list:
        return list(history or [])

    def words(self, text: str) -> tuple:
        got = replied(text)
        if got is None:
            return Kind.USER, text
        return Kind.ASK_REPLY, "\n".join(f"{str(r.get('question') or '').strip()}{' → ' if r.get('question') else ''}"
                                          f"{str(r.get('answer') or '').strip()}" for r in got) or text

    def owns(self, payload) -> bool:
        if not isinstance(payload, dict):
            return False
        if payload.get("type") == "agent_message" and ("author" in payload or "recipient" in payload):
            return True
        if payload.get("type") in SHAPES | {"tool_search_call", "tool_search_output"}:
            return True
        blocks = [c for c in payload.get("content") or [] if isinstance(c, dict)] if isinstance(payload.get("content"), list) else []
        return bool({c.get("type") for c in blocks} & {"input_text", "output_text"})

    def read(self, items: list) -> List[Part]:
        """Each item read. After codex compacts its history, its input starts again: its preamble re-sent under new ids,
        the user messages it kept, and its encrypted summary (a `compaction` item), then what comes after -- the
        items up to the summary are COMPACTION_REPEAT, the summary COMPACTION_SUMMARY, and a compaction trigger OTHER."""
        out = [self.part(it) for it in items]
        at, _ = after_compaction(items)
        for i in range(at):
            out[i].detail["repeated"] = out[i].kind
            out[i].kind = Kind.COMPACTION_REPEAT
        if at >= 0:
            out[at].detail["opens"] = True
        return out

    def part(self, item) -> Part:
        """One item read on its own."""
        kind = kind_of(item)
        p = Part(kind, item.get("role") if isinstance(item, dict) else None, text_of(item),
                 detail={"block": item.get("type") if isinstance(item, dict) else None})
        if not isinstance(item, dict):
            return p
        t = item.get("type")
        if kind == Kind.USER:
            p.words = p.text
        elif kind == Kind.ASK_REPLY:
            p.words = self.words(p.text or "")[1]
            p.detail["replies"] = replied(p.text or "") or []
        elif t == "agent_message":
            p.detail["between"] = "author" in item or "recipient" in item
            said = report_of(p.text or "")
            if said:
                p.kind = said.pop("kind")
                p.detail.update(said)
        elif kind == Kind.ENVIRONMENT or p.role == "user":
            texts = texts_of(item)
            found = next((CWD.findall(x) or ROOT.findall(x) for x in texts if "<environment_context>" in x), None)
            if found:
                p.cwd = found[-1]
        if t in ("function_call", "custom_tool_call", "tool_search_call"):
            name = item.get("name") or t
            args = arguments(item.get("arguments", item.get("input")))
            action = TOOLS.get(name, (Action.OTHER, None))[0]
            p.tool = ToolCall(item.get("call_id") or item.get("id"), name, args, action, ask=ask_of(name, args))
        elif t == "local_shell_call":
            p.tool = ToolCall(item.get("call_id") or item.get("id"), "local_shell", item.get("action") or {}, Action.SHELL)
        elif t == "web_search_call":
            p.tool = ToolCall(item.get("id"), "web_search", item.get("action") or {}, Action.WEB)
        elif t == "image_generation_call":
            p.tool = ToolCall(item.get("id"), "image_generation", {}, Action.OTHER)
        elif kind == Kind.TOOL_RESULT:
            p.result = ToolResult(item.get("call_id"), False, output_of(item.get("output", item.get("tools"))))
        elif kind == Kind.REASONING:
            p.opaque = True
            p.detail["thinking"] = "\n\n".join(s.get("text", "") for s in item.get("summary") or [] if isinstance(s, dict))
        return p

