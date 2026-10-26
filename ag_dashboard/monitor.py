"""What each actor is doing, for the page's full-screen view of them all (page.html's monitor): of its latest
turn, what it was asked, what it is doing now, its newest calls, what it said last, and how many files it worked
on of each kind -- files.files' turn, made small. The files in a temporary folder, and a search's hits, are not
counted, as the Chat view leaves them out of its tree until asked."""
from collections import Counter
from typing import List

from . import files

STEPS = 4                  # the most of a turn's newest calls given
SAID_CHARS = 600           # the most of what it said last, or was asked
STEP_CHARS = 160           # the most of one call's line
MAX_ACTORS = 120           # the most actors one request reads
COUNTED = ("read", "edit", "write", "delete")


def _clip(text, chars: int):
    return None if text is None else text if len(text) <= chars else text[:chars].rstrip() + "…"


def actor(gatherer: str, channel: str, cwd: str = "") -> dict:
    """The actor's latest turn: {turns (how many), at, asked (its message), more (how many the user wrote while it
    ran), said (the last it said; None: nothing yet), now ({kind: "thinking"} or {kind: "call", text}: what it is
    doing; None: neither), work (work.summary's), steps ([{text, running, error}]: its newest calls, oldest first),
    calls (how many it made), files ({kind: how many})} -- {turns: 0} before the user's first message."""
    got = files.files(gatherer, channel, None, cwd or "")
    if "error" in got:
        return {"error": got["error"]}
    turns = got.get("turns") or []
    if not turns:
        return {"turns": 0}
    t = turns[-1]
    said = next((r["text"] for r in reversed(t["replies"]) if r["kind"] == "text"), None)
    kinds = Counter(k for f in got["files"] if not f.get("temporary") for k in f["kinds"] if k in COUNTED)
    now = t.get("now")
    return {"turns": len(turns), "at": t["at"], "asked": _clip(t["text"], SAID_CHARS), "more": len(t.get("more") or []),
            "said": _clip(said, SAID_CHARS),
            "now": None if not now else {"kind": now["kind"], **({"text": _clip(now.get("text"), STEP_CHARS)} if now.get("text") else {})},
            "work": t.get("work"),
            "steps": [{"text": _clip(c["text"], STEP_CHARS), "running": bool(c.get("running")), "error": bool(c.get("error"))}
                      for c in got["commands"][-STEPS:]],
            "calls": len(got["commands"]), "files": {k: kinds[k] for k in COUNTED if kinds[k]}}


def actors(wanted: List[tuple]) -> List[dict]:
    """`actor` for each (gatherer, channel, cwd) of `wanted`, at most MAX_ACTORS: each with its gatherer and channel;
    one that could not be read, with its `error`."""
    out = []
    for g, c, cwd in wanted[:MAX_ACTORS]:
        try:
            got = actor(g, c, cwd)
        except Exception as exc:  # noqa: BLE001 - one actor's error is its card's, not the others'
            got = {"error": f"{type(exc).__name__}: {exc}"}
        out.append({"gatherer": g, "channel": c, **got})
    return out
