"""Answering, from the page, what Claude Code asks in its terminal (data.py's `asking`): the keys that
answer its dialog, and what Claude Code then tells its model, to check the answer by.

    keys(ask, choice)       the keys to type, one at a time, into the dialog as it first shows
    expected(ask, choice)   what the tool's result says once Claude Code has the answer: each a string it holds

A QUESTION (AskUserQuestion) is answered with `choice` {"answers": [one per question: {"options": [the
picked options' places, from 0], "text": the reader's own answer, or None}]}; Claude Code's dialog
numbers the options as the tool call has them, so the keys come from the call itself:

    one option of a question       its number: picked, and on to the next question
    the reader's own words         the number after the options' ("Type something."), the words, Enter
    options of a multiSelect one   each one's number (ticked), then Tab: on to the next question
    then, after several questions  "1": the review's "Submit answers" -- after a lone multiSelect one too;
                                   a lone question of one option is answered by its key

and Claude Code tells the model `"<question>"="<answer>"` for each, the options' labels joined by ", ".

A PLAN (ExitPlanMode) is answered with `choice` {"plan": "auto" | "manual" | "change", "text": what to
change}: the dialog's own choices, as Claude Code 2.1.310 shows them -- 1 "Yes, and use auto mode", 2
"Yes, manually approve edits", 3 "Tell Claude what to change" (the words, then Enter). The tool's call
says none of them: they are Claude Code's.

The keys answer a dialog no one has touched yet; the server types them only into a terminal nothing was
typed into since the question was asked (sessions.py's `press`).
"""

from typing import List, Optional

PLAN_KEYS = {"auto": "1", "manual": "2", "change": "3"}
PLAN_APPROVED = "User has approved your plan"


class AnswerError(ValueError):
    """A choice that does not answer the question asked."""


def _picked(ask: dict, choice: dict) -> List[dict]:
    """Each question with what was picked for it: {question, multi, options: [labels], text}."""
    questions = ask.get("questions") or []
    answers = choice.get("answers")
    if not questions or not isinstance(answers, list) or len(answers) != len(questions):
        raise AnswerError(f"an answer for each of the {len(questions)} questions, please")
    out = []
    for q, a in zip(questions, answers):
        a = a if isinstance(a, dict) else {}
        labels = [o.get("label") or "" for o in q.get("options") or []]
        places = a.get("options") or []
        text = a.get("text") if isinstance(a.get("text"), str) and a["text"].strip() else None
        if not all(isinstance(i, int) and 0 <= i < len(labels) for i in places) or len(set(places)) != len(places):
            raise AnswerError(f"no such option for {q.get('question')!r}")
        if text is not None and (q.get("multiSelect") or places):
            raise AnswerError(f"your own answer to {q.get('question')!r} is the answer: no option with it")
        if text is not None and ("\r" in text or "\n" in text or "\x1b" in text):
            raise AnswerError("your own answer on one line, please")
        if text is None and not places:
            raise AnswerError(f"nothing picked for {q.get('question')!r}")
        if not q.get("multiSelect") and len(places) > 1:
            raise AnswerError(f"one option for {q.get('question')!r}")
        out.append({"question": q.get("question") or "", "multi": bool(q.get("multiSelect")), "count": len(labels),
                    "places": sorted(places), "labels": [labels[i] for i in sorted(places)], "text": text})
    return out


def keys(ask: dict, choice: dict) -> List[str]:
    """The keys that answer `ask` (data.py's `asking`) with `choice` (module doc), each typed on its own."""
    if ask.get("kind") == "plan":
        how = choice.get("plan")
        if how not in PLAN_KEYS:
            raise AnswerError("approve the plan (auto or manual) or say what to change")
        if how != "change":
            return [PLAN_KEYS[how]]
        text = choice.get("text") if isinstance(choice.get("text"), str) else ""
        if not text.strip() or any(c in text for c in "\r\n\x1b"):
            raise AnswerError("what to change, on one line, please")
        return [PLAN_KEYS[how], text.strip(), "\r"]
    picked = _picked(ask, choice)
    out: List[str] = []
    for p in picked:
        if p["text"] is not None:
            out += [str(p["count"] + 1), p["text"].strip(), "\r"]
        elif p["multi"]:
            out += [str(i + 1) for i in p["places"]] + ["\t"]
        else:
            out.append(str(p["places"][0] + 1))
    if len(picked) > 1 or picked[0]["multi"]:
        out.append("1")
    return out


def expected(ask: dict, choice: dict) -> List[str]:
    """What Claude Code's result for the call holds once it has this answer: each of these strings."""
    if ask.get("kind") == "plan":
        return [choice["text"].strip()] if choice.get("plan") == "change" else [PLAN_APPROVED]
    return [f'"{p["question"]}"="{p["text"].strip() if p["text"] is not None else ", ".join(p["labels"])}"'
            for p in _picked(ask, choice)]


def summary(ask: dict, choice: dict) -> str:
    """The answer in a line, for the page: "Which color? → Blue · Which pets? → Cat, Fish"."""
    if ask.get("kind") == "plan":
        return {"auto": "Approved, with auto mode", "manual": "Approved, edits approved by hand"}.get(
            choice.get("plan"), f"Change: {(choice.get('text') or '').strip()}")
    return " · ".join(f"{p['question']} → {p['text'].strip() if p['text'] is not None else ', '.join(p['labels'])}"
                      for p in _picked(ask, choice))


def recorded(result: Optional[str], expect: List[str]) -> Optional[bool]:
    """Whether Claude Code's result for the call (None: none yet) holds every expected string."""
    if result is None:
        return None
    return all(e in result for e in expect)
