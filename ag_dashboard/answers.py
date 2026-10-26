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

CODEX asks (its `harness` "codex") in three ways, each answered by keys of its own (codex 0.164):

    a question (request_user_input, Plan mode's; its turn waits): a dialog, one question at a time
        an option                  its number: picked, and on to the next question -- after the last, all sent
        the reader's own words     Down to "None of the above" (the one after the options), Tab (a note), the
                                   words, Enter
      and codex tells the model {"answers": {<id>: {"answers": [label, "user_note: <words>"]}}}
    a question asked as the turn goes on (request_user_input_async): Shift+Left from the prompt opens it
        an option                  its number (it only moves there), Enter
        the reader's own words     the number after the options' ("Other"), the words (in its place), Enter
      and codex sends the replies as the user's next message: [{"answer", "question", "questionItemId"}]
    a plan its turn proposed (its <proposed_plan>), once the turn is over: "Implement this plan?"
        "implement"                1 "Yes, implement this plan": Default mode, and "Implement the plan." sent
        "change"                   3 "No, stay in Plan mode", then the words and Enter, as a message in Plan mode
      (2 "Yes, clear context and implement" starts another thread: left to the terminal)

The keys answer a dialog no one has touched yet; the server types them only into a terminal nothing was
typed into since the question was asked (sessions.py's `press`).
"""

import json
from typing import List, Optional

PLAN_KEYS = {"auto": "1", "manual": "2", "change": "3"}
CODEX_PLAN_KEYS = {"implement": "1", "change": "3"}
CODEX_IMPLEMENT = "Implement the plan."
CODEX_NOTE = "user_note: "
CODEX_NONE = "None of the above"
DOWN, OPEN_ASYNC = "\x1b[B", "\x1b[1;2D"            # Down; Shift+Left, which opens codex's question asked as it works
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


def _words(text) -> str:
    """The reader's own words for a plan, on one line."""
    text = text if isinstance(text, str) else ""
    if not text.strip() or any(c in text for c in "\r\n\x1b"):
        raise AnswerError("what to change, on one line, please")
    return text.strip()


def keys(ask: dict, choice: dict) -> List[str]:
    """The keys that answer `ask` (data.py's `asking`) with `choice` (module doc), each typed on its own."""
    if ask.get("harness") == "codex":
        return _codex_keys(ask, choice)
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


def _codex_keys(ask: dict, choice: dict) -> List[str]:
    if ask.get("kind") == "plan":
        how = choice.get("plan")
        if how not in CODEX_PLAN_KEYS:
            raise AnswerError("implement the plan or say what to change")
        return [CODEX_PLAN_KEYS[how]] if how == "implement" else [CODEX_PLAN_KEYS[how], _words(choice.get("text")), "\r"]
    out: List[str] = [OPEN_ASYNC] if ask.get("async") else []
    for p in _picked(ask, choice):
        if ask.get("async"):
            out += [str(p["count"] + 1), p["text"].strip(), "\r"] if p["text"] is not None else [str(p["places"][0] + 1), "\r"]
        elif p["text"] is not None:
            out += [DOWN] * p["count"] + ["\t", p["text"].strip(), "\r"]
        else:
            out.append(str(p["places"][0] + 1))
    return out


def expected(ask: dict, choice: dict) -> List[str]:
    """What the harness's result for the call holds once it has this answer: each of these strings (codex's: in the
    JSON it records)."""
    if ask.get("harness") == "codex":
        if ask.get("kind") == "plan":
            return [CODEX_IMPLEMENT] if choice.get("plan") == "implement" else [_words(choice.get("text"))]
        if ask.get("async"):
            return ['"answer":' + _json(p["text"].strip() if p["text"] is not None else p["labels"][0]) for p in _picked(ask, choice)]
        return [_json(CODEX_NOTE + p["text"].strip()) if p["text"] is not None else _json(p["labels"][0])
                for p in _picked(ask, choice)]
    if ask.get("kind") == "plan":
        return [choice["text"].strip()] if choice.get("plan") == "change" else [PLAN_APPROVED]
    return [f'"{p["question"]}"="{p["text"].strip() if p["text"] is not None else ", ".join(p["labels"])}"'
            for p in _picked(ask, choice)]


def _json(text: str) -> str:
    """A string as codex's record has it in its JSON."""
    return json.dumps(text, ensure_ascii=False)


def summary(ask: dict, choice: dict) -> str:
    """The answer in a line, for the page: "Which color? → Blue · Which pets? → Cat, Fish"."""
    if ask.get("kind") == "plan" and ask.get("harness") == "codex":
        return "Implement the plan" if choice.get("plan") == "implement" else f"Change: {(choice.get('text') or '').strip()}"
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
