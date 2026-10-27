"""What a harness's rules (harness_kit) read of one version's fixtures -- tests/fixtures/harnesses/<harness>/<version>/
-- as the probe writes it beside them (expected.json) and test_harness_fixtures.py checks it:

    calls.json         [{name, method, path, headers, body}]: model calls of each kind, as the harness sent them
                       (trimmed: probe.py's `clean`)
                       -> "calls": each one's Call (kind, session, cwd, version, detail, its history's and own
                          messages' lengths), its history's parts' kinds and its own messages' parts
    conversation.json  {history}: the longest conversation a turn sent
                       -> "parts": `read(items(history))`, each piece's Part (texts shortened to a head and a
                          checksum), and `words` of the text of each of the user's own
                       -> "derived": `derived` as ag's hook runs it -- on each answer, with the conversation before it
                          (what it asks), and on the pieces that came after it with the next call (less what it asks)
    record.jsonl       the harness's own record of the session (the lines its follower reads, trimmed)
                       -> "record": `follow` from its start, then what `due` gives once time has passed
    (the asks above)   -> "answers": for each question or plan asked, `answer_keys`, `answer_expected` and
                          `answer_summary` for a few choices (or the AnswerError)

`features` names what a reading holds -- the kinds of calls, parts and facts, how asks settled -- for the probe to say
what a run triggered and what changed against an older version."""

import json
import os
import sys
import zlib
from typing import Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import harness_kit  # noqa: E402
from harness_kit import USERS, AnswerError, Facts, follow  # noqa: E402

AT = 1_000_000_000.0            # when derived facts are seen, for every reading alike
LATER = 4_000_000_000.0         # a time past everything a record's follower waits on (`due`)
SHORT = 160                     # a text this long or shorter is kept whole in a reading


def short(text):
    """A text as a reading keeps it: whole when short, else its head, its length and a checksum of it all."""
    if not isinstance(text, str) or len(text) <= SHORT:
        return text
    return f"{text[:120]}…[{len(text)} {zlib.crc32(text.encode('utf-8')):08x}]"


def plain(value):
    """`value` as JSON has it (tuples as lists), its long strings shortened."""
    value = json.loads(json.dumps(value, ensure_ascii=False, default=str))

    def walk(v):
        if isinstance(v, str):
            return short(v)
        if isinstance(v, list):
            return [walk(x) for x in v]
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        return v
    return walk(value)


def load(folder: str, name: str):
    path = os.path.join(folder, name)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def harness_of(folder: str, name=None) -> harness_kit.Harness:
    """The harness a fixture folder is of: `name`, else its parent folder's name (claude, codex)."""
    h = harness_kit.get(name or os.path.basename(os.path.dirname(os.path.abspath(folder))))
    if h is None:
        raise ValueError(f"no harness for {folder}")
    return h


def part_view(h, p) -> dict:
    v = {"kind": p.kind, "role": p.role, "text": short(p.text)}
    if p.words is not None:
        v["words"] = short(p.words)
    if p.tool is not None:
        t = p.tool
        v["tool"] = {"id": t.id, "name": t.name, "action": t.action, "paths": t.paths,
                     "input": short(json.dumps(t.input, sort_keys=True, ensure_ascii=False)),
                     **({"ask": plain(t.ask)} if t.ask else {})}
    if p.result is not None:
        r = p.result
        v["result"] = {"call_id": r.call_id, "error": r.error, "output": short(r.output),
                       **({"task": plain(r.task)} if r.task else {})}
    if p.cwd:
        v["cwd"] = p.cwd
    if p.opaque:
        v["opaque"] = True
    if p.detail:
        v["detail"] = plain(p.detail)
    if p.kind in USERS and isinstance(p.text, str):
        v["says"] = plain(list(h.words(p.text)))         # as `words` reads a stored message in the user's name
    return v


def fact_view(f) -> list:
    return [f.type, f.key, f.at, plain(f.data)]


def call_view(h, c) -> dict:
    out = {"kind": c.kind, "session": c.session, "cwd": c.cwd, "version": c.version, "detail": plain(c.detail),
           "history": len(c.history), "own": len(c.own), "kinds": [p.kind for p in h.read(h.items(c.history))]}
    if c.own:
        out["own_parts"] = [part_view(h, p) for p in h.read(h.items(c.own))]
    return out


def calls(h, folder: str) -> list:
    out = []
    for c in load(folder, "calls.json") or []:
        got = h.call(c["method"], c["path"], c["headers"], c["body"])
        out.append({"name": c["name"], "call": call_view(h, got) if got is not None else None})
    return out


def windows(h, history: list) -> List[dict]:
    """The pieces ag's hook derives facts from (proxy_hook.py's `derive`), as the conversation has them: each answer
    (the model's message), with the conversation before it, then what came after it until the next answer -- which the
    next call carries -- less what it asks, recorded with the answer. Codex's are its pieces in order: one answer each."""
    answers = [i for i, m in enumerate(history) if isinstance(m, dict) and m.get("role") == "assistant"]
    out = []
    for n, i in enumerate(answers):
        end = answers[n + 1] if n + 1 < len(answers) else len(history)
        out.append((i, [history[i]], history[:i], history[i:end] if end > i + 1 else None))
    return out


def derived(h, folder: str) -> List[dict]:
    conv = load(folder, "conversation.json") or {}
    history = conv.get("history") or []
    out = []
    for i, answer, before, after in windows(h, history):
        said = [f for f in h.derived(h.read(h.items(answer)), AT, h.items(before))
                if not (f.type == Facts.ASKED and h.asks_recorded)]
        then = [f for f in h.derived(h.read(h.items(after)), AT) if f.type != Facts.ASKED] if after else []
        if said or then:
            out.append({"at": i, "answer": [fact_view(f) for f in said], "call": [fact_view(f) for f in then]})
    return out


def record(h, folder: str) -> list:
    path = os.path.join(folder, "record.jsonl")
    if not os.path.exists(path):
        return []
    follower = h.follower(path)
    facts, _ = follow(path, follower)
    return [fact_view(f) for f in facts + follower.due(LATER)]


QUESTION_CHOICES = ("first", "own")


def choices(h, ask: dict) -> List[tuple]:
    if ask.get("kind") == "plan":
        plans = ("auto", "manual", "change") if h.name == "claude" else ("implement", "change")
        return [(p, {"plan": p, "text": "Make it shorter"}) for p in plans]
    qs = ask.get("questions") or []
    first = {"answers": [{"options": [0, 1] if q.get("multiSelect") and len(q.get("options") or []) > 1 else [0]}
                         for q in qs]}
    own = {"answers": [{"options": [0]} if q.get("multiSelect") else {"text": "My own answer"} for q in qs]}
    return [("first", first), ("own", own)]


def answers(h, asks: List[dict]) -> List[dict]:
    out, seen = [], set()
    for ask in asks:
        if ask.get("call") in seen:
            continue
        seen.add(ask.get("call"))
        ask = {**ask, "harness": h.name}
        tried = {}
        for name, choice in choices(h, ask):
            try:
                tried[name] = {"keys": h.answer_keys(ask, choice), "expected": h.answer_expected(ask, choice),
                               "summary": h.answer_summary(ask, choice)}
            except AnswerError as exc:
                tried[name] = {"error": str(exc)}
            except Exception as exc:  # noqa: BLE001 - a rule that cannot take what it asked: kept as read, to fix
                tried[name] = {"error": f"{type(exc).__name__}: {exc}"}
        out.append({"call": ask.get("call"), "kind": ask.get("kind"), "async": bool(ask.get("async")),
                    "choices": plain(tried)})
    return out


def reading(folder: str, harness=None) -> Dict[str, list]:
    """Everything the harness's rules read of the fixtures in `folder` (of `harness`, else its parent folder's name)."""
    h = harness_of(folder, harness)
    conv = load(folder, "conversation.json") or {}
    parts = h.read(h.items(conv.get("history") or []))
    got = {"calls": calls(h, folder), "parts": [part_view(h, p) for p in parts], "derived": derived(h, folder),
           "record": record(h, folder)}
    asks = [f[3] for w in got["derived"] for f in w["answer"] if f[0] == Facts.ASKED]
    asks += [f[3] for f in got["record"] if f[0] == Facts.ASKED]
    full = {}                                         # the asks as read, not shortened: the questions' words matter
    for i, answer, before, _ in windows(h, conv.get("history") or []):
        for f in h.derived(h.read(h.items(answer)), AT, h.items(before)):
            if f.type == Facts.ASKED:
                full[f.data.get("call")] = f.data
    path = os.path.join(folder, "record.jsonl")
    if os.path.exists(path):
        for f in follow(path, h.follower(path))[0]:
            if f.type == Facts.ASKED:
                full[f.data.get("call")] = f.data
    got["answers"] = answers(h, [full.get(a.get("call"), a) for a in asks])
    return got


#: What a fact's feature is named by, after its type (`features`): its `how`, else this.
BY = {Facts.ASKED: "kind", Facts.TASK_STARTED: "kind", Facts.TASK_ENDED: "status"}


def features(got: Dict[str, list]) -> List[str]:
    """What a reading holds, by name: "call:<kind>", "part:<kind>", "tool:<action>", "task:<kind>", "derived:<type>[:how]",
    "record:<type>[:how]" (an ask's and a task's start by their kind, a task's end by its status), "answer:<kind>"."""
    out = set()
    for c in got.get("calls") or []:
        if c["call"]:
            out.add(f"call:{c['call']['kind']}")
            out.update(f"part:{k}" for k in c["call"].get("kinds") or [])
    for p in got.get("parts") or []:
        out.add(f"part:{p['kind']}")
        if p.get("tool"):
            out.add(f"tool:{p['tool']['action']}")
            if p["tool"].get("ask"):
                out.add(f"ask:{p['tool']['ask'].get('kind')}")
        if (p.get("result") or {}).get("task"):
            out.add(f"task:{p['result']['task'].get('kind')}:{p['result']['task'].get('how')}")

    def fact(prefix, f):
        data = f[3] if isinstance(f[3], dict) else {}
        how = data.get(BY.get(f[0], "how"))
        out.add(f"{prefix}:{f[0]}" + (f":{how}" if isinstance(how, str) else ""))
    for w in got.get("derived") or []:
        for f in w["answer"] + w["call"]:
            fact("derived", f)
    for f in got.get("record") or []:
        fact("record", f)
    for a in got.get("answers") or []:
        out.add(f"answer:{a['kind']}" + (":async" if a["async"] else ""))
    return sorted(out)
