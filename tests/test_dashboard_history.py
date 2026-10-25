"""The dashboard's History view (ag_dashboard/history.py): a gatherer's history, light, with its tasks;
searched; the events picked rendered as one transcript and exported; and the Gatherer's model asked for
a summary, a memory or a skill of them -- through `ag home complete`, which asks it as a policy does."""
import io
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
import unittest.mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ag_dashboard import history  # noqa: E402
from ag_dashboard import home as dashboard_home  # noqa: E402


def said(role, text):
    return {"role": role, "content": [{"type": "text", "text": text}]}


EVENTS = [   # (channel, type, payload, text)
    ("c1", "context", said("system", "You are Claude Code."), None),
    ("c1", "user_message", said("user", "deploy the site"), "deploy the site"),
    ("c1", "tool_call", {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "Bash",
                                                           "input": {"command": "make deploy"}}]}, None),
    ("c1", "tool_output", {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1",
                                                        "content": "deployed ```fenced``` ok"}]}, None),
    ("c1", "agent_message", said("assistant", "Deployed with make deploy."), "Deployed with make deploy."),
    ("c2", "user_message", said("user", "what is the weather"), "what is the weather"),
    ("c1", "user_message", said("user", "now roll it back"), "now roll it back"),
    ("c1", "agent_message", said("assistant", "Rolled back."), "Rolled back."),
]


class HistoryBase(unittest.TestCase):
    """Gatherer g: actor c1 in two turns, ag's two tasks over them; actor c2 with one message."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.saved, dashboard_home.HOME = dashboard_home.HOME, self.tmp.name
        self.addCleanup(setattr, dashboard_home, "HOME", self.saved)
        os.makedirs(os.path.join(self.tmp.name, "gatherers", "g"))
        conn = sqlite3.connect(os.path.join(self.tmp.name, "gatherers", "g", "context.db"))
        conn.executescript("""CREATE TABLE event_types (event_type_id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL);
            CREATE TABLE events (row_id INTEGER PRIMARY KEY, inserted_at TEXT NOT NULL, event_id TEXT, event_type_id INTEGER NOT NULL,
              payload_json TEXT NOT NULL, tokens INTEGER NOT NULL, text TEXT, counted INTEGER, p_channel);
            CREATE TABLE tasks (channel_key TEXT NOT NULL, task_index INTEGER NOT NULL, name TEXT NOT NULL, description TEXT,
              first_row INTEGER NOT NULL, last_row INTEGER NOT NULL, tokens INTEGER, retention_json TEXT,
              PRIMARY KEY (channel_key, task_index));""")
        types = {}
        for ch, typ, payload, text in EVENTS:
            if typ not in types:
                types[typ] = conn.execute("INSERT INTO event_types (name, created_at) VALUES (?, '')", (typ,)).lastrowid
            conn.execute("INSERT INTO events (inserted_at, event_type_id, payload_json, tokens, text, p_channel) "
                         "VALUES ('2026-10-24T10:00:00+00:00', ?, ?, 5, ?, ?)", (types[typ], json.dumps(payload), text, ch))
        conn.executemany("INSERT INTO tasks VALUES ('c1', ?, ?, ?, ?, ?, 10, '{}')",
                         [(0, "Deploy", "Deploying the site", 1, 5), (1, "Roll back", "Undoing it", 7, 8)])
        conn.commit()
        conn.close()


class HistoryTest(HistoryBase):
    def test_the_outline_is_every_event_light_with_its_tasks(self):
        got = history.outline("g")
        self.assertEqual([e["row_id"] for e in got["events"]], list(range(1, 9)))
        self.assertEqual(got["events"][1], {"row_id": 2, "channel": "c1", "type": "user_message", "tokens": 5,
                                            "at": got["events"][1]["at"], "text": "deploy the site"})
        self.assertEqual([t["name"] for t in got["tasks"]], ["Deploy", "Roll back"])
        mine = history.outline("g", "c1", after=4)
        self.assertEqual([e["row_id"] for e in mine["events"]], [5, 7, 8])
        self.assertEqual({e["channel"] for e in mine["events"]}, {"c1"})
        self.assertFalse(mine["more"])
        self.assertIn("error", history.outline("nope"))

    def test_search_finds_words_and_what_only_the_payload_holds(self):
        hits = history.search("g", None, "ROLL")["hits"]
        self.assertEqual([h["row_id"] for h in hits], [7, 8])                 # any case: "roll it back", "Rolled back."
        self.assertIn("roll it back", hits[0]["snippet"])
        self.assertEqual([h["row_id"] for h in history.search("g", "c1", "make deploy")["hits"]], [3, 5])   # 3: in its input
        self.assertEqual(history.search("g", "c2", "deploy")["hits"], [])
        self.assertEqual(history.search("g", None, "100%")["hits"], [])        # % is a character, not a wildcard

    def test_the_picked_events_as_one_transcript(self):
        text, about = history.render("g", [[2, 5], 6, 8])
        self.assertEqual(about, {"messages": 6, "turns": 3, "channels": ["c1", "c2"], "tokens": 30})
        self.assertLess(text.index("# Session c1"), text.index("## Task 1: Deploy"))
        self.assertLess(text.index("### Turn 1"), text.index("**User:**\n\ndeploy the site"))
        self.assertIn("**Tool call** `Bash`:\n\n```\nmake deploy\n```", text)
        self.assertIn("````\ndeployed ```fenced``` ok\n````", text)           # a fence longer than the output's own
        self.assertIn("## Task 2: Roll back\n\nUndoing it\n\n### Turn 2", text)
        self.assertLess(text.index("Rolled back."), text.index("# Session c2"))  # an actor's events together
        with self.assertRaises(history.HistoryError):
            history.render("g", [])
        with self.assertRaises(history.HistoryError):
            history.render("g", [[1, 10 ** 9]])

    def test_long_parts_are_cut_in_the_middle(self):
        cut = history._cut("a" * 50 + "b" * 50, 20)
        self.assertTrue(cut.startswith("a" * 15) and cut.endswith("b" * 5))
        self.assertIn("80 characters left out", cut)
        self.assertEqual(history._cut("short", None), "short")

    def test_export_as_markdown_or_as_the_events_stored(self):
        md = history.export("g", [1, 2], "md")
        self.assertTrue(md["name"].endswith(".md"))
        self.assertIn("You are Claude Code.", md["text"])
        js = json.loads(history.export("g", [[1, 2]], "json")["text"])
        self.assertEqual([e["type"] for e in js["events"]], ["context", "user_message"])
        self.assertEqual(js["events"][1]["payload"]["content"][0]["text"], "deploy the site")

    def test_the_model_is_asked_in_the_background_and_its_answer_kept(self):
        seen = {}

        class Done:
            returncode = 0

            def __init__(self, argv, **kw):
                seen["argv"], seen["env"] = argv, kw["env"]

            def communicate(self, prompt, timeout=None):
                seen["prompt"] = prompt
                return json.dumps({"text": "# Memory\n- deploy with make deploy", "model": "m/x", "error": ""}), ""

        with unittest.mock.patch.object(history.subprocess, "Popen", Done), \
                unittest.mock.patch.object(history.sessions, "ag_command", return_value=["ag"]):
            rec = history.start("g", "memory", [[1, 5]], "only the commands")
            self.assertEqual(rec["status"], "running")
            for _ in range(100):
                done = history.extracts("g")[0]
                if done["status"] != "running":
                    break
                time.sleep(0.02)
        self.assertEqual((done["status"], done["output"], done["model"]), ("done", "# Memory\n- deploy with make deploy", "m/x"))
        self.assertEqual(done["rows"], [[1, 5]])
        self.assertEqual(seen["argv"][:3], ["ag", "home", "complete"])
        self.assertIn("MEMORY", seen["argv"][seen["argv"].index("--system") + 1])
        self.assertIn("only the commands", seen["prompt"])
        self.assertIn("make deploy", seen["prompt"])
        self.assertEqual(json.loads(seen["env"]["AG_JOB"])["properties"], {"channel": "c1"})   # one actor's: put to it
        history.delete(done["id"])
        self.assertEqual(history.extracts("g"), [])
        with self.assertRaises(history.HistoryError):
            history.start("g", "poem", [1])
        with self.assertRaises(history.HistoryError):
            history.delete("../../x")

    def test_a_failed_call_says_why_and_one_no_dashboard_runs_is_shown_failed(self):
        class Failed:
            returncode = 1

            def __init__(self, argv, **kw):
                pass

            def communicate(self, prompt, timeout=None):
                return json.dumps({"text": "", "model": "", "error": "no model: set [policies.llm] model"}), ""

        with unittest.mock.patch.object(history.subprocess, "Popen", Failed), \
                unittest.mock.patch.object(history.sessions, "ag_command", return_value=["ag"]):
            rec = history.start("g", "summary", [2])
            for _ in range(100):
                done = history.extracts("g")[0]
                if done["status"] != "running":
                    break
                time.sleep(0.02)
        self.assertEqual((done["status"], done["error"]), ("failed", "no model: set [policies.llm] model"))
        history._save({**rec, "id": "0123456789ab", "server": 2 ** 22 + 12345})       # a dashboard long gone
        orphan = next(r for r in history.extracts("g") if r["id"] == "0123456789ab")
        self.assertEqual(orphan["status"], "failed")


class ServerTest(HistoryBase):
    def test_the_server_answers_the_view(self):
        import threading
        import urllib.request
        from ag_dashboard import server
        httpd = server.serve("127.0.0.1", 0, live_updates=False)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        url = f"http://127.0.0.1:{httpd.server_port}"
        get = lambda path: json.load(urllib.request.urlopen(url + path, timeout=10))  # noqa: E731
        self.assertEqual(len(get("/api/outline?gatherer=g")["events"]), 8)
        self.assertEqual(len(get("/api/outline?gatherer=g&channel=c2")["events"]), 1)
        self.assertEqual([h["row_id"] for h in get("/api/search?gatherer=g&q=weather")["hits"]], [6])
        self.assertEqual(get("/api/extracts?gatherer=g"), [])
        post = urllib.request.Request(url + "/api/history/export", method="POST", headers={"Content-Type": "application/json"},
                                      data=json.dumps({"gatherer": "g", "rows": [[6, 6]], "format": "md"}).encode())
        self.assertIn("what is the weather", json.load(urllib.request.urlopen(post, timeout=10))["text"])
        bad = urllib.request.Request(url + "/api/history/extract", method="POST", headers={"Content-Type": "application/json"},
                                     data=json.dumps({"gatherer": "g", "rows": [], "kind": "summary"}).encode())
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(bad, timeout=10)
        self.assertEqual(caught.exception.code, 400)


class CompleteTest(unittest.TestCase):
    """`ag home complete`: the Gatherer's model asked once, the prompt on stdin."""

    def setUp(self):
        from ag.ag_harness.home import Home
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.h = Home(self.tmp.name)

    def run_it(self, stdin, *args, llm=None):
        from ag.ag_harness.home import __main__ as cli
        out, err = io.StringIO(), io.StringIO()
        with unittest.mock.patch.object(sys, "stdin", io.StringIO(stdin)), unittest.mock.patch.object(sys, "stdout", out), \
                unittest.mock.patch.object(sys, "stderr", err), unittest.mock.patch.object(self.h, "llm", return_value=llm), \
                unittest.mock.patch.object(self.h, "model", return_value="m/x"):
            code = cli.cmd_complete(self.h, *args)
        return code, out.getvalue(), err.getvalue()

    def test_the_answer_or_why_there_is_none(self):
        class Echo:
            def complete(self, prompt, *, system, model, effort, timeout, purpose):
                self.asked = (prompt, system, model, effort, purpose)
                return "answer to " + prompt

        llm = Echo()
        code, out, _ = self.run_it("the prompt", "ask", "be brief", "", 30, True, llm=llm)
        self.assertEqual((code, json.loads(out)), (0, {"text": "answer to the prompt", "model": "m/x", "error": ""}))
        self.assertEqual(llm.asked, ("the prompt", "be brief", "m/x", "", "ask"))
        code, out, err = self.run_it("  ", "ask", "", "", 30, False, llm=llm)
        self.assertEqual((code, out), (1, ""))
        self.assertIn("no prompt", err)

        class Silent:
            def complete(self, prompt, **kw):
                return ""

        code, out, _ = self.run_it("x", "ask", "", "", 30, True, llm=Silent())
        self.assertEqual((code, json.loads(out)["error"]), (1, "the model answered nothing"))


if __name__ == "__main__":
    unittest.main()
