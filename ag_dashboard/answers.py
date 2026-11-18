"""Answering, from the page, what a harness asks in its terminal (data.py's `asking`): the keys that answer its dialog,
and what it then tells its model, to check the answer by -- each harness's own (harness_kit's `answer_keys`,
`answer_expected`, `answer_summary`, where its dialogs are described), for the harness the question names (its
`harness`; Claude Code's when it names none).

    keys(ask, choice)       the keys to type, one at a time, into the dialog as it first shows
    expected(ask, choice)   what the harness records once it has the answer: each a string it holds
    summary(ask, choice)    the answer in a line, for the page
    recorded(result, expect)  whether what the harness recorded holds what was expected

A QUESTION is answered with `choice` {"answers": [one per question: {"options": [the picked options' places, from 0],
"text": the reader's own answer, or None}]}; a PLAN with {"plan": "auto" | "manual" | "change" (Claude Code's),
"implement" | "change" (codex's), "text": what to change}; a PERMISSION (a tool it asks to run) with {"allow": bool,
"text": why not, or None} -- its harness's `permission_keys`.

The keys answer a dialog no one has touched yet; the server types them only into a terminal nothing was typed into
since the question was asked (sessions.py's `answer`).
"""

from typing import List, Optional

import harness_kit
from harness_kit import AnswerError  # noqa: F401 - raised by keys, expected and summary
from harness_kit.base import permission_choice, permission_summary

PERMISSION = "permission"                # what an ask is that a tool waits on (harness_kit's `hooked`)


def _harness(ask: dict) -> harness_kit.Harness:
    h = harness_kit.get(ask.get("harness") or harness_kit.DEFAULT)
    if h is None:
        raise AnswerError(f"can't answer {ask.get('harness')} here. Answer it in the terminal.")
    return h


def keys(ask: dict, choice: dict, shown: Optional[dict] = None) -> List[str]:
    """The keys that answer `ask` with `choice` (module doc), each typed on its own; a permission's, into its dialog as
    the terminal's screen shows it (`shown`: harness_kit's `permission_shown`)."""
    if ask.get("kind") == PERMISSION:
        return _harness(ask).permission_keys(choice, shown)
    return _harness(ask).answer_keys(ask, choice)


def expected(ask: dict, choice: dict) -> List[str]:
    """What the harness's result for the call holds once it has this answer: each of these strings (a permission's:
    none -- what it asked about has no result of its own to check)."""
    if ask.get("kind") == PERMISSION:
        permission_choice(choice)
        return []
    return _harness(ask).answer_expected(ask, choice)


def summary(ask: dict, choice: dict) -> str:
    """The answer in a line, for the page: "Which color? → Blue · Which pets? → Cat, Fish"; "Allowed"."""
    if ask.get("kind") == PERMISSION:
        return permission_summary(choice)
    return _harness(ask).answer_summary(ask, choice)


def recorded(result: Optional[str], expect: List[str]) -> Optional[bool]:
    """Whether the harness's result for the call (None: none yet) holds every expected string."""
    if result is None:
        return None
    return all(e in result for e in expect)
