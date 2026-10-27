"""A version's fixtures read again by the rules as they are now: its expected.json (and probe.json's features) written
anew, and what changed said -- for a rule changed on purpose, the change to look over before committing it.

    python tests/probe/rewrite.py tests/fixtures/harnesses/claude/2.1.311 [...]"""

import json
import os
import sys

from reading import features, reading


def main() -> None:
    for folder in sys.argv[1:]:
        path = os.path.join(folder, "expected.json")
        with open(path, encoding="utf-8") as fh:
            was = json.load(fh)
        got = reading(folder)
        for section in got:
            old, new = was.get(section) or [], got[section]
            if old != new:
                changed = sum(1 for a, b in zip(old, new) if a != b) + abs(len(old) - len(new))
                print(f"{folder}: {section}: {changed} of {len(new)} changed")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(got, fh, indent=1, ensure_ascii=False)
        meta = os.path.join(folder, "probe.json")
        if os.path.exists(meta):
            with open(meta, encoding="utf-8") as fh:
                kept = json.load(fh)
            with open(meta, "w", encoding="utf-8") as fh:
                json.dump({**kept, "features": features(got)}, fh, indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
