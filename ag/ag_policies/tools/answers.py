"""Reading JSON out of a model's answer.

Models do not always answer with JSON alone: some write prose or a draft
first, then a fenced block. So the answer is searched for the first JSON object that has the key asked
for, starting at each `{` in turn -- not just the first, which may sit in the
prose.
"""

import json
from typing import Iterator, Optional

_DECODER = json.JSONDecoder()


def find_objects(text: str, key: str) -> Iterator[dict]:
    """Every JSON object in `text` that has `key`, in order. A model may write
    a draft before its answer (a fenced block, then the object again, complete),
    so a caller that finds the first unusable can try the next."""
    if not text:
        return
    at = text.find("{")
    while at >= 0:
        try:
            data, end = _DECODER.raw_decode(text, at)
            if isinstance(data, dict) and key in data:
                yield data
                at = text.find("{", end)
                continue
        except ValueError:
            pass
        at = text.find("{", at + 1)


def find_object(text: str, key: str) -> Optional[dict]:
    """The first JSON object in `text` that has `key`, or None."""
    return next(find_objects(text, key), None)


def pairs(entries, a: str, b: str) -> list:
    """The entries of a list of objects that have non-empty `a` and `b`, as
    just those two (stripped)."""
    out = []
    for x in entries if isinstance(entries, list) else []:
        if isinstance(x, dict) and str(x.get(a) or "").strip() and str(x.get(b) or "").strip():
            out.append({a: str(x[a]).strip(), b: str(x[b]).strip()})
    return out
