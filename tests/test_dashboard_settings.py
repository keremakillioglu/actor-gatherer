"""ag's settings in the dashboard (ag_dashboard/settings.py): config.toml read, its model set through
the real `ag model`, a new gatherer's defaults and the file itself written with its comments kept,
and the endpoints that do it from the page only."""

import json
import os
import sys
import tempfile
import threading
import tomllib
import unittest
import unittest.mock
import urllib.error
import urllib.request

from ag_dashboard import home, server, settings

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class SettingsBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = os.path.join(self.tmp.name, "home")
        os.makedirs(self.home)
        self.patches = [unittest.mock.patch.object(home, "HOME", self.home),
                        unittest.mock.patch.dict(os.environ, {"AG_COMMAND": f"{sys.executable} -m ag.cli",
                                                              "PYTHONPATH": REPO})]
        for p in self.patches:
            p.start()
        for var, _ in settings.LLM_ENV:
            os.environ.pop(var, None)

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()


class SetKeyTest(unittest.TestCase):
    TEXT = ('[policies]\ndefault = "a"   # the policy # a new gatherer gets\n\n[policies.llm]\nmodel = "x/y"\n\n'
            '[pollers]\n# default = ["old"]\ndefault = ["f"]  # its pollers\n')

    def test_a_value_is_replaced_and_its_comment_kept(self):
        got = settings.set_key(self.TEXT, "policies", "default", "b")
        self.assertIn('default = "b"   # the policy # a new gatherer gets', got)
        got = settings.set_key(got, "pollers", "default", [])
        self.assertIn('# default = ["old"]\ndefault = []', got)
        self.assertIn("# its pollers", got)
        cfg = tomllib.loads(got)
        self.assertEqual((cfg["policies"]["default"], cfg["pollers"]["default"], cfg["policies"]["llm"]["model"]),
                         ("b", [], "x/y"))

    def test_a_missing_key_or_section_is_added(self):
        got = settings.set_key(self.TEXT, "policies.llm", "api_base", 'http://h "q"')
        got = settings.set_key(got, "cli", "gatherer", "work")
        cfg = tomllib.loads(got)
        self.assertEqual((cfg["policies"]["llm"]["api_base"], cfg["cli"]["gatherer"]), ('http://h "q"', "work"))


class SettingsTest(SettingsBase):
    def test_before_ag_ran_there_is_no_file(self):
        got = settings.read()
        self.assertEqual((got["exists"], got["llm"]["model"]), (False, ""))
        with self.assertRaises(settings.SettingsError):
            settings.set_defaults(got["version"], gatherer="g")

    def test_the_model_is_set_by_ag_which_makes_the_file(self):
        got = settings.set_model("claude-code/haiku")
        self.assertTrue(got["exists"])
        self.assertEqual(got["llm"]["model"], "claude-code/haiku")
        self.assertIn("model:     claude-code/haiku", got["said"])
        self.assertIn("proactive_context_manager", got["policies"]["available"])
        with self.assertRaises(settings.SettingsError):
            settings.set_model("  ")

    def test_defaults_are_written_and_the_rest_kept(self):
        before = settings.set_model("claude-code/haiku")
        got = settings.set_defaults(before["version"], pollers=[], gatherer=".")
        self.assertEqual((got["pollers"]["default"], got["cli"]["gatherer"]), ([], "."))
        self.assertEqual(len(got["text"].splitlines()), len(before["text"].splitlines()) + 3)  # [cli] and its key added
        self.assertIn("# the pollers a new gatherer gets", got["text"])
        for bad in ({"policy": "nope"}, {"pollers": ["nope"]}, {"gatherer": "a b"}):
            with self.assertRaises(settings.SettingsError):
                settings.set_defaults(got["version"], **bad)

    def test_a_write_over_a_changed_file_or_one_that_does_not_parse_is_refused(self):
        got = settings.set_model("claude-code/haiku")
        with self.assertRaises(settings.SettingsError):
            settings.save_text(got["text"] + "\n[broken", got["version"])
        with self.assertRaises(settings.SettingsError):
            settings.save_text(got["text"], "stale")
        saved = settings.save_text(got["text"].replace("claude-code/haiku", "claude-code/opus"), got["version"])
        self.assertEqual(saved["llm"]["model"], "claude-code/opus")


class EndpointTest(SettingsBase):
    def setUp(self):
        super().setUp()
        self.httpd = server.serve("127.0.0.1", 0, live_updates=False)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        super().tearDown()

    def post(self, path, body, headers=None):
        req = urllib.request.Request(self.url + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as exc:
            return exc.code, json.load(exc)

    def test_the_page_reads_and_sets_them(self):
        with urllib.request.urlopen(self.url + "/api/settings", timeout=10) as r:
            self.assertFalse(json.load(r)["exists"])
        code, got = self.post("/api/settings/model", {"model": "claude-code/sonnet"})
        self.assertEqual((code, got["llm"]["model"]), (200, "claude-code/sonnet"))
        code, got = self.post("/api/settings/defaults", {"version": got["version"], "gatherer": "work"})
        self.assertEqual((code, got["cli"]["gatherer"]), (200, "work"))
        code, err = self.post("/api/settings/file", {"version": "stale", "text": got["text"]})
        self.assertEqual(code, 400)
        self.assertIn("changed since", err["error"])

    def test_another_origin_is_refused(self):
        code, _ = self.post("/api/settings/model", {"model": "claude-code/sonnet"}, {"Origin": "http://evil.example"})
        self.assertEqual(code, 403)
        self.assertFalse(os.path.exists(settings.path()))


if __name__ == "__main__":
    unittest.main()
