"""harness_kit: what each agent harness is, apart from ag -- how it shapes its model calls, which of the text
it sends is its own, what its tools do, what its own records of a session hold. Standard library only; it
imports nothing of ag (tests/test_harness_kit.py), so ag's integrations and the dashboard both read
harnesses through it.

    harness_kit.get("claude")        a harness's rules (ClaudeCode, Codex): `call`, `items`, `read`; a session's
                                     name given in the harness's own store (`rename`, `rename_command`)
    harness_kit.owner(payload)       the harness whose format a stored piece is in, as its shape tells; None
    harness_kit.harness_of(payloads) the harness a session runs on, as its pieces' shapes tell (pi's and
                                     opencode's too, which have no rules here yet)

    base.py      the Harness class, and what reading gives: Call, Part (of a Kind), ToolCall, ToolResult; and what
                 reading its own record of a session gives: a Follower's Facts (`follow`)
    claude.py    Claude Code (ClaudeCode); its record of a session (Record)
    codex.py     Codex (Codex); its rollout of a thread (Rollout)
    shell.py     what a shell command reads and writes, read from its words: shared by every harness
"""

from typing import Dict, Iterable, Optional

from .base import (MODELS, USERS, Action, AnswerError, Call, CallKind, Fact, Facts, Follower, Harness,  # noqa: F401 - the
                   Kind, Part, RenameError, ToolCall, ToolResult, follow)                             # package's API
from . import codex
from .claude import ClaudeCode
from .codex import Codex

HARNESSES: Dict[str, Harness] = {h.name: h for h in (ClaudeCode(), Codex())}


def get(name: Optional[str]) -> Optional[Harness]:
    """The harness named `name` ("claude", "codex"); None for one harness_kit has no rules for."""
    return HARNESSES.get(name or "")


def owner(payload) -> Optional[Harness]:
    """The harness whose format a stored piece is in, as far as its shape tells: codex's Responses items first (an
    item is typed; a message's parts are input_text and output_text), then Claude Code's Anthropic message pieces."""
    for h in (HARNESSES["codex"], HARNESSES["claude"]):
        if h.owns(payload):
            return h
    return None


def words(text: str, harness: Optional[str] = None) -> tuple:
    """(the Kind, the user's words as they typed them) of a message's text in the user's name, its harness's wrappers
    taken off (Harness.words): `harness`'s, else whichever harness's wrapper it is in (they do not overlap)."""
    h = get(harness)
    if h is not None:
        return h.words(text)
    for h in (HARNESSES["codex"], HARNESSES["claude"]):
        got = h.words(text)
        if got != (Kind.USER, text):
            return got
    return Kind.USER, text


def harness_of(payloads: Iterable) -> Optional[str]:
    """The harness a session runs on, as its pieces' shape tells -- a gatherer stores no name: codex's Responses
    items, Claude Code's Anthropic message pieces, pi's messages, opencode's {info, parts} messages; None when none
    of them shows."""
    for p in payloads:
        if not isinstance(p, dict):
            continue
        if "info" in p and ("parts" in p or "sessionID" in (p.get("info") or {})) or "sessionID" in p:
            return "opencode"
        if p.get("type") in codex.SHAPES and ("role" in p or "call_id" in p or "summary" in p or "id" in p):
            return "codex"
        blocks = [c for c in p.get("content") or [] if isinstance(c, dict)] if isinstance(p.get("content"), list) else []
        kinds = {c.get("type") for c in blocks}
        if kinds & {"input_text", "output_text"}:
            return "codex"
        if "api" in p or p.get("role") == "toolResult" or kinds & {"toolCall"}:
            return "pi"
        if kinds & {"tool_use", "tool_result", "redacted_thinking"} or p.get("role") == "system":
            return "claude"
    return None

