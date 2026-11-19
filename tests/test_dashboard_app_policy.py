"""app_policy.py: what adding an app to an actor or a task does ("join", "folder", "no") -- its manifest's `on_task`,
unless the user chose otherwise for it on the Apps page, kept in <home>/dashboard/app_settings.json."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app_kit  # noqa: E402
from ag_dashboard import app_policy, home as dashboard_home  # noqa: E402


class AppPolicyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.was = dashboard_home.HOME
        dashboard_home.HOME = self.tmp.name
        self.browser = app_kit.parse({"name": "browser", "label": "Browser"})                     # a task app: join
        self.files = app_kit.parse({"name": "files", "label": "Files", "access": "group", "on_task": "folder"})

    def tearDown(self):
        dashboard_home.HOME = self.was
        self.tmp.cleanup()

    def kept(self, got=None):
        if got is not None:
            os.makedirs(os.path.dirname(app_policy.path()), exist_ok=True)
            with open(app_policy.path(), "w") as fh:
                json.dump(got, fh)
        with open(app_policy.path()) as fh:
            return json.load(fh)

    def test_the_manifest_s_unless_the_user_chose_otherwise(self):
        self.assertEqual((app_policy.chosen(), app_policy.of(self.browser), app_policy.of(self.files)),
                         ({}, "join", "folder"))
        self.kept({"browser": {"on_task": "no", "agent": False}, "files": {"on_task": "join"},
                   "notes": {"on_task": "sideways"}, "slack": {"agent": True}})
        self.assertEqual(app_policy.chosen(), {"browser": "no", "files": "join", "notes": "sideways"})
        self.assertEqual(app_policy.of(self.browser), "no")
        self.assertEqual(app_policy.of(self.files), "folder")          # a group app can't join: its manifest's
        listed = app_policy.listed([self.browser.to_dict(), self.files.to_dict()])
        self.assertEqual([a["on_task"] for a in listed], ["no", "folder"])

    def test_a_choice_kept_beside_the_app_s_others(self):
        self.kept({"browser": {"agent": False}})                       # the Apps page's other choice of it
        self.assertEqual(app_policy.choose(self.browser, "folder"), "folder")
        self.assertEqual(self.kept(), {"browser": {"agent": False, "on_task": "folder"}})
        self.assertEqual(app_policy.choose(self.files, "no"), "no")
        self.assertEqual(app_policy.chosen(), {"browser": "folder", "files": "no"})
        self.assertEqual(app_policy.choose(self.browser, "join"), "join")            # its own: the choice dropped
        self.assertEqual(app_policy.choose(self.files, "folder"), "folder")          # an app's last: its line too
        self.assertEqual(self.kept(), {"browser": {"agent": False}})

    def test_what_an_app_can_t_take_is_refused(self):
        with self.assertRaises(ValueError) as ctx:
            app_policy.choose(self.files, "join")
        self.assertIn("one of folder, no for Files", str(ctx.exception))
        with self.assertRaises(ValueError):
            app_policy.choose(self.browser, "beside")
        self.assertFalse(os.path.exists(app_policy.path()))


if __name__ == "__main__":
    unittest.main()
