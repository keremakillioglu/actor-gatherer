"""The context manager's server (`ag.ag_harness.server`): the manager
functions over stdio, on generic events, the same for every harness."""

import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from ag.ag_harness import home as ag_home  # noqa: E402
from ag.ag_harness.server import serve  # noqa: E402
from ag.ag_harness.server.__main__ import server_for  # noqa: E402
from ag.ag_harness.store import paths  # noqa: E402
from ag.integrations.harnesses.codex.adaptor import to_events as codex  # noqa: E402

DEV = {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "instructions"}]}


def user(text, n):
    return {"type": "message", "role": "user", "id": f"u{n}", "content": [{"type": "input_text", "text": text}]}


def agent(text, n):
    return {"type": "message", "role": "assistant", "id": f"a{n}",
            "content": [{"type": "output_text", "text": text}]}


def events(*items):
    return codex.to_events(list(items))


class HomeBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, "ag")
        self.saved = paths.TRACE_DIR, paths.AG_HOME
        paths.AG_HOME, paths.TRACE_DIR = self.root, os.path.join(self.root, "gatherers")
        ag_home._HOMES.clear()

    def tearDown(self):
        paths.TRACE_DIR, paths.AG_HOME = self.saved
        ag_home._HOMES.clear()
        self.tmp.cleanup()

    def ask(self, *requests):
        out = io.StringIO()
        serve(server_for(), [json.dumps(dict(r, id=i)) for i, r in enumerate(requests, 1)], out)
        return [json.loads(line) for line in out.getvalue().splitlines()]


class ManagerFunctionsTest(HomeBase):
    def test_insert_then_read(self):
        sent = events(DEV, user("q", 1))
        inserted, again, read = self.ask(
            {"op": "insert", "gatherer": "s", "properties": {"channel": "c"}, "events": sent},
            {"op": "insert", "gatherer": "s", "properties": {"channel": "c"}, "events": sent},
            {"op": "read", "gatherer": "s", "properties": {"channel": "c"}, "row": 2})
        self.assertEqual((inserted["rows"], inserted["last"]), ([1, 2], 2))
        self.assertEqual((again["rows"], again["last"]), ([None, None], 2))    # stored already; the last found
        self.assertEqual(read["context"], [{"type": e["type"], "id": e["id"], "payload": e["payload"]}
                                           for e in sent])                    # events come back as they were sent

    def test_rewrite_is_insert_then_read(self):
        sent = events(DEV, user("q", 1))
        answer, = self.ask({"op": "rewrite", "gatherer": "s", "properties": {"channel": "c"}, "events": sent})
        self.assertEqual([e["payload"] for e in answer["context"]], [DEV, user("q", 1)])
        self.assertIn("2 events in (event 2), 2 out", answer["note"])

    def test_a_type_the_gatherer_does_not_have_is_added(self):
        self.ask({"op": "insert", "gatherer": "s", "properties": {},
                  "events": [{"type": "robot.beep", "id": "b1", "payload": {"beep": 1}}]})
        types, = self.ask({"op": "event_types", "gatherer": "s"})
        beep, = [t for t in types["event_types"] if t["name"] == "robot.beep"]
        self.assertEqual(beep["properties"], [])
        self.assertEqual(beep["id"], len(types["event_types"]))             # the last one defined

    def test_locate_init_and_event_types(self):
        init, _, by_id, added, types = self.ask(
            {"op": "init", "gatherer": "s", "event_types": [{"name": "ticket"}]},
            {"op": "insert", "gatherer": "s", "properties": {}, "events": events(user("q", 1))},
            {"op": "locate", "gatherer": "s", "properties": {}, "event_id": "u1"},
            {"op": "add_event_type", "gatherer": "s", "name": "robot"},
            {"op": "event_types", "gatherer": "s"})
        names = [t["name"] for t in types["event_types"]]
        self.assertEqual(names[:5], ["user_message", "agent_message", "tool_call", "tool_output", "context"])
        self.assertIn("ticket", [t["name"] for t in init["event_types"]])
        self.assertEqual(by_id["row"], 1)
        self.assertEqual(added["type_id"], dict((t["name"], t["id"]) for t in types["event_types"])["robot"])
        self.assertEqual(set(types["event_types"][0]), {"id", "name", "properties"})   # no text functions

    def test_every_request_is_stateless(self):
        """No manager outlives a request: two servers on one gatherer agree."""
        self.ask({"op": "insert", "gatherer": "s", "properties": {"channel": "c"}, "events": events(user("q", 1))})
        read, = self.ask({"op": "read", "gatherer": "s", "properties": {"channel": "c"}, "row": 1})       # another server
        self.assertEqual(read["context"][0]["payload"], user("q", 1))

    def test_bad_requests_are_answered(self):
        answers = self.ask({"op": "read", "gatherer": "s"}, {"op": "insert", "gatherer": "s"},
                           {"op": "dance", "gatherer": "s"}, {"op": "add_event_type", "gatherer": "s"},
                           {"op": "insert", "gatherer": "s", "events": [{"payload": 1}]},      # no type
                           {"op": "rewrite", "gatherer": "s"},
                           {"op": "rewrite", "gatherer": "s", "events": [{"type": ""}]})
        self.assertEqual([("error" in a) for a in answers], [True, True, True, True, True, False, False])
        self.assertIsNone(answers[5]["context"])                               # a rewrite: send your own
        self.assertIsNone(answers[6]["context"])

    def test_the_policy_s_own_message_comes_back_as_ag(self):
        work = os.path.join(self.tmp.name, "work")
        os.makedirs(work)
        target = os.path.join(work, "a.py")
        with open(target, "w") as fh:
            fh.write("x = 1\n")
        first = [DEV, user("please read a.py", 1)]
        self.ask({"op": "rewrite", "gatherer": "s", "properties": {"channel": "c"}, "cwd": work, "events": events(*first)})
        time.sleep(0.01)
        with open(target, "a") as fh:
            fh.write("y = 2\n")
        second = first + [agent("ok", 1), user("and now?", 2)]
        answer, = self.ask({"op": "rewrite", "gatherer": "s", "properties": {"channel": "c"}, "cwd": work, "events": events(*second)})
        *kept, notice = answer["context"]
        self.assertEqual([e["payload"] for e in kept], second)
        self.assertEqual((notice["type"], notice["name"]), ("ag", "environment_update"))
        self.assertTrue(notice["text"].startswith("File a.py was changed on disk"), notice["text"])
        self.assertIn("(1 ag)", answer["note"])

    def test_any_harness_may_share_a_gatherer_in_channels_of_its_own(self):
        pi_message = {"role": "user", "content": "hi from pi", "timestamp": 1}
        self.ask({"op": "insert", "gatherer": "shared", "properties": {"channel": "codex"}, "events": events(user("q", 1))},
                 {"op": "insert", "gatherer": "shared", "properties": {"channel": "pi"},
                  "events": [{"type": "user_message", "id": "p1", "payload": pi_message}]})
        codex_read, pi_read = self.ask({"op": "read", "gatherer": "shared", "properties": {"channel": "codex"}, "row": 1},
                                       {"op": "read", "gatherer": "shared", "properties": {"channel": "pi"}, "row": 2})
        own = lambda read: [e["payload"] for e in read["context"] if e["type"] != "ag"]  # noqa: E731
        self.assertEqual(own(codex_read), [user("q", 1)])
        self.assertEqual(own(pi_read), [pi_message])
        shown = lambda read: [e["name"] for e in read["context"] if e["type"] == "ag"]  # noqa: E731
        self.assertEqual((shown(codex_read), shown(pi_read)), (["parallel_request"], ["parallel_request"]))  # each other's

    def test_the_gatherer_s_log(self):
        self.ask({"op": "rewrite", "gatherer": "s", "properties": {"channel": "c"}, "events": events(user("q", 1))})
        with open(paths.server_log("s")) as fh:
            log = fh.read()
        self.assertIn("gatherer s created", log)
        self.assertIn("[c] 1 events in (event 1)", log)


class ProcessTest(unittest.TestCase):
    """The server as the harness side runs it: a process, JSON lines on stdio."""

    def run_server(self, tmp, requests, code=None):
        env = dict(os.environ, AG_HOME=os.path.join(tmp, "ag"), PYTHONPATH=REPO)
        args = [sys.executable, "-c", code] if code else [sys.executable, "-m", "ag.ag_harness.server"]
        return subprocess.run(args, input=("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in requests))
                              .encode("utf-8"), capture_output=True, env=env, cwd=REPO, timeout=120)

    def test_events_over_stdio(self):
        with tempfile.TemporaryDirectory() as tmp:
            sent = events(DEV, user("q", 1))
            done = self.run_server(tmp, [{"id": 1, "op": "rewrite", "gatherer": "s", "properties": {"channel": "s"}, "events": sent},
                                         {"id": 2, "op": "ping"}])
            self.assertEqual(done.returncode, 0, done.stderr)
            answers = [json.loads(line) for line in done.stdout.decode().splitlines()]
            self.assertEqual([e["payload"] for e in answers[0]["context"]], [DEV, user("q", 1)], done.stderr)
            self.assertEqual(answers[1], {"pong": True, "id": 2})
            self.assertTrue(os.path.exists(os.path.join(tmp, "ag", "logs", "gatherers", "s", "server.log")))

    def test_answers_on_stdout_alone(self):
        stray = ("import ag.ag_harness.server as s\n"                    # a print while a request is handled
                 "handle = s.Server.handle\n"
                 "def loud(self, r):\n    print('a stray print'); return handle(self, r)\n"
                 "s.Server.handle = loud\n"
                 "from ag.ag_harness.server.__main__ import main\nmain([])\n")
        with tempfile.TemporaryDirectory() as tmp:
            done = self.run_server(tmp, [{"id": 1, "op": "ping"}], code=stray)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual([json.loads(line) for line in done.stdout.decode().splitlines()],
                             [{"pong": True, "id": 1}])
            self.assertIn(b"a stray print", done.stderr)

    def test_text_is_utf_8_whatever_the_locale(self):
        with tempfile.TemporaryDirectory() as tmp:
            sent = events(user("café — naïve ✓", 1))
            done = subprocess.run([sys.executable, "-m", "ag.ag_harness.server"],
                                  input=(json.dumps({"id": 1, "op": "rewrite", "gatherer": "u", "events": sent},
                                                    ensure_ascii=False) + "\n").encode("utf-8"),
                                  capture_output=True, cwd=REPO, timeout=120,
                                  env=dict(os.environ, AG_HOME=os.path.join(tmp, "ag"), PYTHONPATH=REPO,
                                           PYTHONIOENCODING="latin-1"))
            self.assertEqual(done.returncode, 0, done.stderr)
            answer = json.loads(done.stdout.decode("utf-8"))
            self.assertEqual(answer["context"][0]["payload"], user("café — naïve ✓", 1))   # not "cafÃ©"


if __name__ == "__main__":
    unittest.main()
