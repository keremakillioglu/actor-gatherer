"""The page's monitor of every actor (ag_dashboard/monitor.py): each actor's latest turn made small for its card --
what it was asked, what it is doing now, its newest calls, what it said last, how many files it worked on of each
kind -- and the server's /api/monitor, which reads it for several actors at once."""
import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ag_dashboard import home as dashboard_home  # noqa: E402
from ag_dashboard import monitor, server  # noqa: E402
from test_dashboard_files import asked, call, result, said, thought  # noqa: E402


class MonitorTest(unittest.TestCase):
    """Gatherer `g` of the test's own: c1 at work in its second turn, c2 done."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.saved, dashboard_home.HOME = dashboard_home.HOME, self.tmp.name
        self.addCleanup(setattr, dashboard_home, "HOME", self.saved)
        os.makedirs(os.path.join(self.tmp.name, "gatherers", "g"))
        self.db = os.path.join(self.tmp.name, "gatherers", "g", "context.db")
        conn = sqlite3.connect(self.db)
        conn.executescript("""CREATE TABLE event_types (event_type_id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL);
            CREATE TABLE events (row_id INTEGER PRIMARY KEY, inserted_at TEXT NOT NULL, event_id TEXT, event_type_id INTEGER NOT NULL,
              payload_json TEXT NOT NULL, tokens INTEGER NOT NULL, text TEXT, counted INTEGER, p_channel);""")
        conn.close()
        self.add("c1", asked("look at a.py"), said("It returns 1."),
                 asked("make g return 3"), thought("Read it, then edit."),
                 call("r1", "Read", {"file_path": "/w/a.py"}), result("r1", "1\tdef g():\n2\t    return 2"),
                 call("e1", "Edit", {"file_path": "/w/a.py", "old_string": "    return 2", "new_string": "    return 3"}), result("e1", "ok"),
                 call("s1", "Bash", {"command": "cat > /tmp/x/scratch.txt <<'EOF'\nx\nEOF", "description": "Note it"}), result("s1", ""),
                 call("t1", "Bash", {"command": "python3 -m unittest", "description": "Run the tests"}), result("t1", "FAILED", True),
                 said("A test fails; fixing it."),
                 call("g1", "Grep", {"pattern": "def g", "path": "/w"}), result("g1", "/w/a.py:1:def g():"),
                 call("t2", "Bash", {"command": "python3 -m unittest", "description": "Run the tests again"}))
        self.add("c2", asked("hello"), said("Hi! " + "word " * 200))

    def add(self, channel, *events):
        conn = sqlite3.connect(self.db)
        for typ, payload in events:
            got = conn.execute("SELECT event_type_id FROM event_types WHERE name = ?", (typ,)).fetchone()
            tid = got[0] if got else conn.execute("INSERT INTO event_types (name, created_at) VALUES (?, '')", (typ,)).lastrowid
            conn.execute("INSERT INTO events (inserted_at, event_type_id, payload_json, tokens, p_channel) VALUES "
                         "('2026-10-26 08:00:00', ?, ?, 1, ?)", (tid, json.dumps(payload), channel))
        conn.commit()
        conn.close()

    def test_an_actor_at_work(self):
        got = monitor.actor("g", "c1", "/w")
        self.assertEqual((got["turns"], got["asked"], got["more"]), (2, "make g return 3", 0))
        self.assertEqual(got["now"], {"kind": "call", "text": "Run the tests again"})
        self.assertEqual(got["said"], "A test fails; fixing it.")          # the last it said in this turn
        self.assertEqual(got["calls"], 6)
        self.assertEqual(got["steps"], [                                    # its newest, oldest first
            {"text": "Note it", "running": False, "error": False},
            {"text": "Run the tests", "running": False, "error": True},
            {"text": "Grep def g", "running": False, "error": False},
            {"text": "Run the tests again", "running": True, "error": False}])
        self.assertEqual(got["files"], {"read": 1, "edit": 1})            # not the temporary file, nor the search's hit
        self.assertEqual(got["work"]["doing"], "test")

    def test_an_actor_done_and_one_with_nothing_yet(self):
        got = monitor.actor("g", "c2")
        self.assertIsNone(got["now"])
        self.assertTrue(got["said"].startswith("Hi! word") and got["said"].endswith("…"))
        self.assertLessEqual(len(got["said"]), monitor.SAID_CHARS + 1)
        self.assertEqual((got["steps"], got["calls"], got["files"]), ([], 0, {}))
        self.assertEqual(monitor.actor("g", "nobody"), {"turns": 0})
        self.assertIn("error", monitor.actor("nope", "c1"))

    def test_several_at_once_each_named(self):
        got = monitor.actors([("g", "c1", "/w"), ("g", "c2", ""), ("nope", "c1", "")])
        self.assertEqual([(a["gatherer"], a["channel"]) for a in got], [("g", "c1"), ("g", "c2"), ("nope", "c1")])
        self.assertEqual(got[1]["asked"], "hello")
        self.assertIn("error", got[2])

    def test_the_server_reads_them(self):
        httpd = server.serve("127.0.0.1", 0, live_updates=False)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        ask = urllib.parse.quote(json.dumps([["g", "c1", "/w"], ["g", "c2"], ["g", 3], "x"]))
        got = json.load(urllib.request.urlopen(f"http://127.0.0.1:{httpd.server_port}/api/monitor?actors={ask}", timeout=10))
        self.assertEqual([a["channel"] for a in got["actors"]], ["c1", "c2"])    # what is not an actor left out
        self.assertEqual(got["actors"][0]["now"]["text"], "Run the tests again")


if __name__ == "__main__":
    unittest.main()
