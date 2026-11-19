"""The dashboard names no app (app_kit/DESIGN.md; ag_dashboard/DESIGN.md, rule 3): no module of its server says the
name of an app that comes with ag (ag_apps/: DocWriter, the Browser, the Editor) -- it reaches each only through the
app host and app_kit's contract, as it would one written by anyone else -- and mcp.py's tools/list record."""
import io
import json
import os
import re
import sys
import tempfile
import tokenize
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import app_kit  # noqa: E402
from ag_dashboard import mcp  # noqa: E402

DASHBOARD = os.path.join(ROOT, "ag_dashboard")
OWN: set = set()                                                  # none of the dashboard's modules is an app's own
#: Words an app is named by that are the dashboard's own, from before the app was: "files", its Files view's (files.py,
#: Chat's files and commands) -- the Files app's name and label. Not looked for: a module naming that app would not be
#: told apart from one saying its own word.
OWN_WORDS = {"files"}
NAMES = sorted({w.lower() for m in app_kit.finding.find(os.path.join(ROOT, "no-home"))[0].values()
                for w in (m.name, m.label)
                if os.path.dirname(m.folder or "") == os.path.join(ROOT, "ag_apps")} - OWN_WORDS)   # the apps that come with ag
SAID = re.compile("(?i)" + "|".join(map(re.escape, NAMES)))        # in any text, and any part of a name: DocWriters

#: What the dashboard's code may still say that names an app, and why it is not about one: (file, words of the line
#: where it is found).
ALLOWED = {
    ("__main__.py", "webbrowser"): "Python's module that opens the page in the user's web browser",
    ("__main__.py", "the browser"): "the user's web browser, which `ag dashboard` opens the page in",
    ("__main__.py", "open a browser"): "the same",
    ("files.py", "NOTES = {"): "what Chat calls each kind of a harness's note (a skill, a report): not the Notes app",
    ("files.py", "NOTES.get("): "the same",
}


def python_names(path: str) -> list:
    """Where a module's code names an app: (line, what, the line's text) of a string (not a docstring), or an
    f-string's text, that holds one's name, and of an identifier that does. Comments and docstrings say what they
    like."""
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    lines = src.split("\n")
    out, prev = [], tokenize.NEWLINE
    for t in tokenize.generate_tokens(io.StringIO(src).readline):
        if t.type in (tokenize.COMMENT, tokenize.NL):
            continue
        found = None
        if t.type == tokenize.STRING and prev not in (tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT):
            body = re.sub(r"^[A-Za-z]*('''|\"\"\"|'|\")|('''|\"\"\"|'|\")$", "", t.string)
            found = t.string[:100] if SAID.search(body) else None
        elif t.type == getattr(tokenize, "FSTRING_MIDDLE", -1) and SAID.search(t.string):
            found = t.string[:100]
        elif t.type == tokenize.NAME and SAID.search(t.string):
            found = t.string
        if found is not None:
            out.append((t.start[0], found, lines[t.start[0] - 1].strip()))
        prev = t.type
    return out


def modules() -> list:
    """The dashboard's modules, and its server's routers (api/), as paths from ag_dashboard/."""
    return sorted(n for n in os.listdir(DASHBOARD) if n.endswith(".py")) + \
        sorted("api/" + n for n in os.listdir(os.path.join(DASHBOARD, "api")) if n.endswith(".py"))


def _allowed(name: str, text: str) -> bool:
    return any(f == name and words in text for f, words in ALLOWED)


class OnlyTheAppsNameAnAppTest(unittest.TestCase):
    def test_the_dashboard_s_code_names_no_app_but_the_apps_own(self):
        found = []
        for name in modules():
            if name not in OWN:
                found += [f"{name}:{line}: {what}" for line, what, text in python_names(os.path.join(DASHBOARD, name))
                          if not _allowed(name, text)]
        self.assertEqual(found, [], "an app named in the dashboard: reach it through the app host and app_kit's "
                                    "contract instead (app_kit/DESIGN.md)")

    def test_every_allowance_is_still_needed(self):
        used = set()
        for name in modules():
            if name not in OWN:
                used |= {(f, words) for _, _, text in python_names(os.path.join(DASHBOARD, name))
                         for f, words in ALLOWED if f == name and words in text}
        self.assertEqual(set(ALLOWED) - used, set())

    def test_it_would_be_found(self):
        """The check itself: what the dashboard had is found; what is only words about one is not."""
        with tempfile.TemporaryDirectory() as tmp:
            mod = os.path.join(tmp, "m.py")
            with open(mod, "w") as fh:
                fh.write('"""A DocWriter\'s, a Browser\'s."""\nfrom . import browser as bw, docwriter\n'
                         'if role.get("docwriter"):  # a DocWriter\'s\n    x = srv.browsers.compose(row, text)\n'
                         '    y = f"{a} no DocWriter started {b}"\nz = "/browser/w/"\nw = "a page"\n')
            self.assertEqual([line for line, _, _ in python_names(mod)], [2, 2, 3, 4, 5, 6])


class ListedTest(unittest.TestCase):
    """mcp.py keeps when each endpoint last answered `tools/list` (`listed`), for a first message to wait on."""

    def call(self, method, at, id_=1):
        return mcp.handle(json.dumps({"jsonrpc": "2.0", "id": id_, "method": method}).encode(), [], lambda n, a: {},
                          at=at)

    def test_a_list_is_kept_by_its_endpoint(self):
        at = mcp.endpoint("listedtest", "0123456789abcdef")
        self.assertIsNone(mcp.listed(at))
        before = time.time()
        self.call("initialize", at)
        self.call("ping", at)
        self.assertIsNone(mcp.listed(at))                    # only a list of its tools counts
        self.assertEqual(self.call("tools/list", at), (200, {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}))
        self.assertGreaterEqual(mcp.listed(at), before)
        self.assertIsNone(mcp.listed(mcp.endpoint("listedtest", "fedcba9876543210")))     # another endpoint's: not
        batch = json.dumps([{"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]).encode()
        mcp.handle(batch, [], lambda n, a: {}, at="listedbatch/0123456789abcdef")    # in a batch, too
        self.assertIsNotNone(mcp.listed("listedbatch/0123456789abcdef"))
        self.call("tools/list", None)                         # a server that names no endpoint: none kept
        self.assertNotIn(None, mcp._listed)


if __name__ == "__main__":
    unittest.main()
