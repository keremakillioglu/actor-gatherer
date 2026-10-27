"""Each harness version's fixtures (tests/fixtures/harnesses/<harness>/<version>/), read by harness_kit's rules as they
were when the fixtures were made (expected.json): what each model call is, what each piece of a conversation is, what
ag's hook derives from the answers and calls, what the follower reads in the harness's own record, and how what it asks
is answered. The fixtures are real, captured from a live session by the probe (tests/probe/probe.py), which writes a
new version's folder; an older version's stays, and its harness must still be read as it was.

A failure here is a rule that now reads one of them otherwise: a fix, or a break. A fix that is meant: write the
reading again (`python tests/probe/rewrite.py <folder>`) and look over the change before committing it."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "probe"))

import reading  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "harnesses")
SECTIONS = ("calls", "parts", "derived", "record", "answers")


def folders():
    """[(harness, version, folder)] of every version's fixtures."""
    out = []
    for harness in sorted(os.listdir(FIXTURES)) if os.path.isdir(FIXTURES) else []:
        for version in sorted(os.listdir(os.path.join(FIXTURES, harness))):
            folder = os.path.join(FIXTURES, harness, version)
            if os.path.exists(os.path.join(folder, "expected.json")):
                out.append((harness, version, folder))
    return out


class FixturesTest(unittest.TestCase):
    maxDiff = 4000

    def test_there_are_fixtures_of_each_harness(self):
        self.assertEqual({h for h, _, _ in folders()}, {"claude", "codex"})

    def test_each_version_is_read_as_it_was(self):
        for harness, version, folder in folders():
            with open(os.path.join(folder, "expected.json"), encoding="utf-8") as fh:
                expected = json.load(fh)
            got = reading.reading(folder)
            for section in SECTIONS:
                with self.subTest(harness=harness, version=version, section=section):
                    want, have = expected.get(section), got[section]
                    if want != have and isinstance(want, list) and isinstance(have, list):
                        at = next((i for i, (w, h) in enumerate(zip(want, have)) if w != h), min(len(want), len(have)))
                        self.assertEqual(want[at:at + 1], have[at:at + 1], f"{section}[{at}] of {len(want)} -> {len(have)}")
                    self.assertEqual(want, have)

    def test_each_version_s_calls_name_it(self):
        for harness, version, folder in folders():
            for c in reading.reading(folder)["calls"]:
                with self.subTest(harness=harness, version=version, call=c["name"]):
                    if c["name"].startswith("unread-"):         # a POST to a model endpoint that is no model call
                        self.assertIsNone(c["call"])            # (Claude Code's count_tokens), kept as such
                        continue
                    self.assertIsNotNone(c["call"])
                    self.assertEqual(c["call"]["version"], version)        # its User-Agent's, as the probe captured it


if __name__ == "__main__":
    unittest.main()
