"""The dashboard's own actions on a session, kept in its gatherer (ag_dashboard/actions.py): each an event put in by ag
(`ag home insert`), in the background, and only while a server runs the page."""
import json
import os
import sys
import unittest
import unittest.mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ag_dashboard import actions  # noqa: E402


class ActionsTest(unittest.TestCase):
    def setUp(self):
        self.ran = []
        run = unittest.mock.patch.object(actions.subprocess, "run", side_effect=self.ag)
        run.start()
        self.addCleanup(run.stop)
        on = unittest.mock.patch.object(actions, "ENABLED", True)
        on.start()
        self.addCleanup(on.stop)
        self.addCleanup(actions._typed.clear)

    def ag(self, argv, **kwargs):
        self.ran.append(argv)
        return unittest.mock.Mock(returncode=0, stdout='{"rows": [1]}', stderr="")

    def events(self):
        """What was put in: [(gatherer, channel, type, payload)]."""
        out = []
        for argv in self.ran:
            gatherer = argv[argv.index("insert") + 1]
            channel = json.loads(argv[argv.index("--properties") + 1])["channel"]
            out += [(gatherer, channel, e["type"], e["payload"]) for e in json.loads(argv[argv.index("--events") + 1])]
        return out

    def test_each_action_an_event_of_its_own_put_in_by_ag(self):
        actions.record("g", "s1", [actions._event(actions.CHAT_SENT, text="hi")], wait=True)
        [(gatherer, channel, kind, payload)] = self.events()
        self.assertEqual((gatherer, channel, kind, payload["text"]), ("g", "s1", "chat_sent", "hi"))
        self.assertIn("home", self.ran[0])
        with unittest.mock.patch.object(actions, "ENABLED", False):                # no page served: none kept
            actions.record("g", "s1", [actions._event(actions.CHAT_SENT, text="hi")], wait=True)
        self.assertEqual(len(self.ran), 1)

    def test_keys_typed_are_one_event_each_time_they_start_again(self):
        with unittest.mock.patch.object(actions, "record") as record:
            for at in (100.0, 100.5, 101.0, 105.0, 105.2):
                actions.terminal_input("g", "s1", at)
        self.assertEqual(len(record.call_args_list), 2)                   # at 100 and at 105: a quiet spell between

    def test_a_new_gatherer_s_first_action_waits_for_its_database(self):
        answers = [unittest.mock.Mock(returncode=1, stdout='{"error": "no database for gatherer g"}', stderr=""),
                   unittest.mock.Mock(returncode=0, stdout='{"rows": [1]}', stderr="")]
        with unittest.mock.patch.object(actions.subprocess, "run", side_effect=lambda argv, **kw: answers.pop(0)) as run, \
                unittest.mock.patch.object(actions.time, "sleep"):
            actions.record("g", "s1", [actions._event(actions.CHAT_SENT, text="hi")], wait=True)
        self.assertEqual((run.call_count, answers), (2, []))             # tried again once the session's call made it


if __name__ == "__main__":
    unittest.main()
