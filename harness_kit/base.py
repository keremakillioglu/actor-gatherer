"""What a harness is: the facts about an agent harness that hold whatever reads them -- how it shapes its
model calls, which of the text it sends is its own, what each of its tools does. Standard library only:
nothing here knows of ag, of its gatherer or its policies.

A harness module reads what the harness sends at three levels:

    1. the model call     `call(method, path, headers, body)`: what one request is (`Call`) -- the
                          session's own turn, a subagent's, one of the harness's side calls -- or None
                          when it is no model call at all
    2. its pieces         `items(history)`: the conversation as pieces, each one thing said; and
                          `read(items)`: each piece as a `Part`, of a `Kind` -- the user's words, the
                          model's, the harness's own notes of each kind
    3. its tool calls     filled in by `read`, on the part: a `ToolCall` (its tool, its input, the
                          `Action` it takes, the files it names, what it asks the user) or a
                          `ToolResult` (its call, its words, the background task it started or ended)

A subclass mostly lists its rules (its tables of openings, whole texts and tools); the functions that
apply them are its own where its format needs them. `checked_with` is the harness's version the rules
were read from: a newer one may word things differently.
"""

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class Kind:
    """What a piece of a conversation is. The first four are the user's own words; AGENT, REASONING,
    TOOL_CALL and TOOL_RESULT the model's turn; every other is the harness's own text, sent in the
    model's conversation -- in the user's name, or a system message."""
    USER = "user"                        # the user's words
    USER_COMMAND = "user_command"        # a command the user typed: `!ls` (its shell), `/greet Bob` (a prompt it expands)
    MID_TURN = "mid_turn"                # the user's words, written while the turn ran and sent into it
    ASK_REPLY = "ask_reply"              # the user's answers to what the harness asked as the turn went on
    AGENT = "agent"                      # the model's words
    REASONING = "reasoning"              # the model's own reasoning: its words, or an opaque blob
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    ENVIRONMENT = "environment"          # the harness's notes on where and how the agent works: reminders,
                                         # instructions files, its environment, the tools it adds
    COMMAND_PROMPT = "command_prompt"    # the prompt a command the user typed expands to
    LOCAL_COMMAND = "local_command"      # a command the user ran that the harness runs itself (/context, /mcp)
    COMMAND_OUTPUT = "command_output"    # what such a command, or one run with `!`, printed
    ATTACHMENT_NOTE = "attachment_note"  # the harness's note on an attachment (an image shrunk to fit)
    INTERRUPT = "interrupt"              # its note that the user stopped the turn
    SKILL = "skill"                      # a skill's instructions, loaded
    AGENT_REPORT = "agent_report"        # a subagent's report, handed back
    PEER_MESSAGE = "peer_message"        # a message from another session or agent
    TASK_NOTICE = "task_notice"          # its notice that a background task ended, or did something
    RETRY_NOTE = "retry_note"            # its note after a response that went wrong, sending the model back to it
    HOOK_FEEDBACK = "hook_feedback"      # a hook's reason for not letting the turn end
    TOOL_NOTICE = "tool_notice"          # its note that tools were loaded, added or removed
    COMPACTION_SUMMARY = "compaction_summary"   # its summary of a compacted conversation
    COMPACTION_REPEAT = "compaction_repeat"     # what it sends again with that summary: its notes, files restored
    OTHER = "other"                      # anything else of its own


#: The kinds that are the user's own words.
USERS = frozenset({Kind.USER, Kind.USER_COMMAND, Kind.MID_TURN, Kind.ASK_REPLY})
#: The kinds that are the model's turn.
MODELS = frozenset({Kind.AGENT, Kind.REASONING, Kind.TOOL_CALL})


class CallKind:
    """What one model call is."""
    TURN = "turn"                        # the session's own turn
    SUBAGENT = "subagent"                # a subagent's: a conversation of its own
    SUGGESTION = "suggestion"            # a prompt suggestion: what the user might type next
    RECAP = "recap"                      # a recap of the session, for a user coming back
    TITLE = "title"                      # a title for the session
    COMPACTION = "compaction"            # the harness compacting its history: its summary asked for
    OTHER = "other"                      # any other side call of the harness's own


class Action:
    """What a tool call does."""
    READ = "read"                        # reads a file
    EDIT = "edit"                        # changes or writes files
    SHELL = "shell"                      # runs a shell command
    SEARCH = "search"                    # searches files, or lists them
    WEB = "web"                          # searches or fetches the web
    SKILL = "skill"                      # loads a skill
    DELEGATE = "delegate"                # starts or messages a subagent
    ASK = "ask"                          # asks the user, the turn waiting on the answer
    TASK = "task"                        # watches, waits on or stops a background task
    OTHER = "other"


@dataclass
class Call:
    """One model call: what it is (`kind`, a CallKind), the session it belongs to (None: none said), the
    working directory it states, the harness's version (None: not said), and where its conversation splits
    from the call's own messages -- `history`, the conversation so far; `own`, what the call adds to it to
    ask for what it is for (a suggestion's prompt, a compaction's instruction; [] for a turn)."""
    kind: str
    session: Optional[str] = None
    cwd: Optional[str] = None
    version: Optional[str] = None
    history: list = field(default_factory=list)
    own: list = field(default_factory=list)
    detail: Dict[str, Any] = field(default_factory=dict)   # what the harness says of it besides


@dataclass
class ToolCall:
    """A tool call: its id, its tool, its input (an object; or a string, as the harness gave it), what it
    does (`action`, an Action), the files it names, and -- when it asks the user and the turn waits --
    what it asks (`ask`: {kind: "question", questions: [{id, header, question, multiSelect, options:
    [{label, description}]}]} or {kind: "plan", plan: its text, None when the call carries none})."""
    id: Optional[str]
    name: str
    input: Any = None
    action: str = Action.OTHER
    paths: List[str] = field(default_factory=list)
    ask: Optional[dict] = None


@dataclass
class ToolResult:
    """A tool's result: its call's id, whether it is an error, its words as a reader sees them, and -- when
    it says a background task started, resumed or was stopped -- that task (`task`: {id, kind (command,
    agent, monitor, workflow), how: "started" or "stopped", output: the file it writes to, label: what it
    is for, when the result says})."""
    call_id: Optional[str]
    error: bool = False
    output: str = ""
    task: Optional[dict] = None


@dataclass
class Part:
    """One piece of a conversation, read: its `kind` (a Kind), the role it was sent in, `text` -- what the
    model reads of it (None: nothing to read, such as encrypted reasoning) -- and `words`, the user's own
    words in it, unwrapped (USERS: "! ls", "/greet Bob", a message sent mid-turn), else None. A tool call or
    result has `tool` or `result`; a piece that states the agent's working directory, `cwd`; `opaque`, an
    opaque blob (encrypted reasoning). `detail` holds what a kind says besides:

        SKILL            name, args, instructions
        AGENT_REPORT     from (the subagent's id or path), text (its report)
        PEER_MESSAGE     name (who sent it), text
        LOCAL_COMMAND    name: the command as typed ("/context")
        COMMAND_OUTPUT   text: what it printed
        TASK_NOTICE      notices: [{id, status, event, ended, waiting}]
        any kind         loaded: [(path, [(n, line)], how)], files whose lines the note gives the agent
    """
    kind: str
    role: Optional[str] = None
    text: Optional[str] = None
    words: Optional[str] = None
    tool: Optional[ToolCall] = None
    result: Optional[ToolResult] = None
    cwd: Optional[str] = None
    opaque: bool = False
    detail: Dict[str, Any] = field(default_factory=dict)


class Harness(ABC):
    """One harness's rules. Subclasses implement `items`, `read` and `owns`; `call` says what a request
    is (None by default: the harness's calls not known). `name` is how ag and the dashboard name it,
    `label` how a person does, `checked_with` the harness's version the rules were read from."""
    name: str = ""
    label: str = ""
    checked_with: str = ""

    # ---- level 1: one model call

    def call(self, method: str, path: str, headers, body) -> Optional[Call]:
        """What the request is, or None: not a model call this harness's rules know."""
        return None

    def title(self, reply: List[Part]) -> Optional[str]:
        """A title call's answer, as the title it gives: the reply's words, by default."""
        return _said(reply)

    def recap(self, reply: List[Part]) -> Optional[str]:
        """A recap call's answer, as the recap it gives: the reply's words, by default."""
        return _said(reply)

    # ---- levels 2 and 3: its pieces, and the tool calls among them

    @abstractmethod
    def items(self, history: list) -> list:
        """The conversation as pieces, in order: each one thing said, as the harness sent it."""

    @abstractmethod
    def read(self, items: list) -> List[Part]:
        """Each piece read, one Part per piece, in order. The whole list, because what a piece is may
        depend on its neighbours."""

    @abstractmethod
    def owns(self, payload) -> bool:
        """Whether a stored piece is in this harness's format, as far as its shape tells."""

    def read_one(self, payload) -> List[Part]:
        """A stored piece read on its own (its neighbours not known): one Part per piece it splits into."""
        return self.read(self.items([payload]))

    def words(self, text: str) -> tuple:
        """(the Kind, the user's words as they typed them) of the text of a message in the user's name -- the harness's
        wrappers around them taken off. By default, the text as it is."""
        return Kind.USER, text


def _said(reply: List[Part]) -> Optional[str]:
    text = "\n".join(p.text or "" for p in reply if p.kind == Kind.AGENT).strip()
    return text or None


def output_of(value) -> str:
    """A tool result's words, as a reader sees them: a string, or the text of its blocks ("[image]" for an image,
    "Loaded <tool>" for a tool a tool search loaded)."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        words = []
        for b in value:
            if isinstance(b, str):
                words.append(b)
            elif isinstance(b, dict):
                if isinstance(b.get("text"), str):
                    words.append(b["text"])
                elif b.get("type") in ("image", "input_image"):
                    words.append("[image]")
                elif b.get("type") == "tool_reference" and b.get("tool_name"):    # tool search: a tool loaded
                    words.append(f"Loaded {b['tool_name']}")
        return "\n".join(words)
    if isinstance(value, dict):
        for k in ("output", "content", "text"):
            if k in value:
                return output_of(value[k])
    return "" if value is None else json.dumps(value, ensure_ascii=False)
