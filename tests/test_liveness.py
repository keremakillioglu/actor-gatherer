"""Whether a session is still going: the hook server finds the harness's process on the other end
of each call's connection (peer.py), ag keeps it with the call's read (`_reads.pid`,
`pid_started`), and the dashboard asks whether that process still runs and whether its turn is
over -- RUNNING, IDLE, or CLOSED."""
import os
import socket
import subprocess
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ag.ag_harness.store import operations as store  # noqa: E402
from ag.integrations.tools.hook_server import peer  # noqa: E402
from ag_dashboard import data  # noqa: E402
from ag_dashboard import home as dashboard_home  # noqa: E402
from channels import ch  # noqa: E402
from test_core import agent, user  # noqa: E402
from test_dashboard import HomeBase  # noqa: E402
import codex_items  # noqa: E402

LINUX = os.path.isdir("/proc/net")


@unittest.skipUnless(LINUX, "no /proc: the process cannot be told")
class PeerTest(unittest.TestCase):
    def test_the_process_on_the_other_end_of_a_connection(self):
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen()
        self.addCleanup(server.close)
        child = subprocess.Popen([sys.executable, "-c", "import socket, sys, time; s = socket.create_connection("
                                  f"('127.0.0.1', {server.getsockname()[1]})); print('up', flush=True); time.sleep(30)"],
                                 stdout=subprocess.PIPE, text=True)
        self.addCleanup(child.kill)
        self.assertEqual(child.stdout.readline().strip(), "up")
        conn, addr = server.accept()
        self.addCleanup(conn.close)
        found = peer.process_of(addr, conn.getsockname())
        self.assertEqual(found, peer.identity(child.pid))
        self.assertTrue(peer.alive(found))
        self.assertTrue(dashboard_home.process_alive(found["pid"], found["started"]))   # the dashboard's own check agrees
        child.kill()
        child.wait()
        self.assertFalse(peer.alive(found))
        self.assertFalse(dashboard_home.process_alive(found["pid"], found["started"]))

    def test_a_pid_given_to_another_process_is_not_it(self):
        me = peer.identity(os.getpid())
        self.assertFalse(peer.alive(dict(me, started=me["started"] + "0")))
        self.assertFalse(dashboard_home.process_alive(me["pid"], me["started"].split(":")[0] + ":1"))
        self.assertIsNone(dashboard_home.process_alive(None, None))          # nothing recorded

    def test_no_such_connection_no_process(self):
        self.assertIsNone(peer.process_of(("127.0.0.1", 1), ("127.0.0.1", 2)))
        self.assertIsNone(peer.process_of(None, None))


class StatusTest(unittest.TestCase):
    def test_the_rule(self):
        now = 1000.0
        self.assertEqual(data.status_of(False, False, now, now), data.CLOSED)   # gone, mid-turn or not
        self.assertEqual(data.status_of(False, True, now, now), data.CLOSED)
        self.assertEqual(data.status_of(True, True, now, now), data.IDLE)
        self.assertEqual(data.status_of(True, False, now - 99999, now), data.RUNNING)   # alive: no time limit
        self.assertEqual(data.status_of(None, False, now - 10, now), data.RUNNING)      # not known: recent
        self.assertEqual(data.status_of(None, False, now - data.STALE_SECONDS - 1, now), data.IDLE)


class AgentsTest(HomeBase):
    """Status as the home lists it, from what the gatherer holds."""

    def status(self, channel="c1"):
        a = next(a for g in data.home()["gatherers"] for a in g["agents"] if a["channel"] == channel)
        return a["status"], a["turn_over"], a["alive"]

    def pend(self, events, stop=None, channel="c1"):
        self.m.record_pending("g", ch(channel), events, "a1", stop)

    def test_an_agent_read_alone_is_as_the_home_lists_it(self):
        started = [{"session_id": "c1", "gatherer": "g", "cwd": "/", "harness": "codex", "status": "terminal", "pid": 42,
                    "created_at": "2026-10-24T00:00:00+00:00", "kept": 0, "ended": 0}]
        for stop in ("tool_use", "end_turn"):
            self.m.clear_pending("g", ch("c1"))
            self.pend([{"type": "tool_call" if stop == "tool_use" else "agent_message", "payload": {}, "text": "x"}], stop)
            whole = next(a for a in data.home(started)["gatherers"][0]["agents"] if a["channel"] == "c1")
            alone = data.actors("g", {"c1"}, started)
            self.assertEqual([a["channel"] for a in alone], ["c1"])          # c2 not read
            self.assertEqual(alone[0], whole, stop)
        self.assertEqual(data.actors("none", {"c1"}, []), [])                 # no such gatherer: none

    def test_the_turn_from_the_pending_answer_and_its_stop_reason(self):
        self.pend([{"type": "agent_message", "payload": {}, "text": "Done."}], "end_turn")
        self.assertEqual(self.status()[:2], (data.IDLE, True))
        self.m.clear_pending("g", ch("c1"))
        self.pend([{"type": "agent_message", "payload": {}, "text": "Running the tests."},
                   {"type": "tool_call", "payload": {}, "text": "pytest"}], "tool_use")
        self.assertEqual(self.status()[1], False)
        self.m.clear_pending("g", ch("c1"))
        self.pend([{"type": "tool_call", "payload": {}, "text": "ls"}], "completed")     # codex: by its last event
        self.assertEqual(self.status()[1], False)
        self.m.clear_pending("g", ch("c1"))
        self.pend([{"type": "agent_message", "payload": {}, "text": "Done."}], "completed")
        self.assertEqual(self.status()[1], True)

    def test_a_turn_that_asks_the_user_waits_for_them(self):
        question = {"type": "tool_use", "id": "t1", "name": "AskUserQuestion", "input": {"questions": [
            {"header": "Layout", "question": "Which layout?", "multiSelect": False,
             "options": [{"label": "Side by side", "description": "Two panes"}, {"label": "Tabs"}]}]}}
        self.pend([{"type": "agent_message", "payload": {}, "text": "One question first."},
                   {"type": "tool_call", "payload": {"role": "assistant", "content": [question]}, "text": "AskUserQuestion(...)"}],
                  "tool_use")
        a = next(a for a in data.home()["gatherers"][0]["agents"] if a["channel"] == "c1")
        self.assertEqual((a["status"], a["running"], a["turn_over"]), (data.ASKING, False, False))
        self.assertEqual((a["asking"]["kind"], a["asking"]["call"]), ("question", "t1"))
        self.assertEqual(a["asking"]["questions"], [{"header": "Layout", "question": "Which layout?", "multiSelect": False,
                                                     "options": [{"label": "Side by side", "description": "Two panes"},
                                                                 {"label": "Tabs", "description": None}]}])
        self.m.clear_pending("g", ch("c1"))                                     # answered: the next call carried it
        self.pend([{"type": "tool_call", "payload": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "ls"}}]}, "text": "Bash(ls)"}], "tool_use")
        self.assertEqual(self.status()[0], data.RUNNING)                         # any other tool: it runs
        self.m.clear_pending("g", ch("c1"))
        self.pend([{"type": "tool_call", "payload": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t3", "name": "ExitPlanMode", "input": {"plan": "1. Split the pane"}}]}, "text": "ExitPlanMode"}],
                  "tool_use")
        a = next(a for a in data.home()["gatherers"][0]["agents"] if a["channel"] == "c1")
        self.assertEqual((a["status"], a["asking"]["kind"], a["asking"]["plan"]), (data.ASKING, "plan", "1. Split the pane"))
        self.assertIsNone(next(a for a in data.home()["gatherers"][0]["agents"] if a["channel"] == "c2")["asking"])

    def test_an_earlier_answer_s_question_is_not_asked_again(self):
        ask = {"type": "tool_call", "payload": {"content": [{"type": "tool_use", "id": "t1", "name": "AskUserQuestion",
                                                             "input": {"questions": []}}]}}
        self.m.record_pending("g", ch("c1"), [ask], "a1", "tool_use")
        self.m.record_pending("g", ch("c1"), [{"type": "tool_call", "payload": {"content": [
            {"type": "tool_use", "id": "t2", "name": "Bash", "input": {}}]}}], "a2", "tool_use")   # answered, not yet stored
        self.assertEqual(self.status()[0], data.RUNNING)

    def test_with_none_pending_from_the_newest_event(self):
        items = codex_items.CodexItems(self.m)
        items.insert("g", agent("all done", 95), channel_id="c1")
        self.assertEqual(self.status()[1], True)
        items.insert("g", user("and now?", 96), channel_id="c1")                      # a call in flight
        self.assertEqual(self.status()[1], False)

    @unittest.skipUnless(LINUX, "no /proc")
    def test_a_closed_process_is_closed_whatever_its_turn(self):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        self.addCleanup(child.kill)
        process = peer.identity(child.pid)
        items = codex_items.CodexItems(self.m)
        items.insert("g", user("run the long job", 97), channel_id="c1")
        self.m._context("g", store.high_water(self.m._conn("g")), ch("c1"), process=process)
        self.pend([{"type": "tool_call", "payload": {}, "text": "make"}], "tool_use")
        self.assertEqual(self.status(), (data.RUNNING, False, True))
        child.kill()
        child.wait()
        self.assertEqual(self.status(), (data.CLOSED, False, False))

    def test_a_read_keeps_its_process_and_an_older_file_gets_the_columns(self):
        process = {"pid": 4242, "started": "boot:123"}
        read_id = self.m._context("g", store.high_water(self.m._conn("g")), ch("c1"), process=process)[1]
        row = self.m._conn("g").execute("SELECT pid, pid_started FROM _reads WHERE read_id = ?", (read_id,)).fetchone()
        self.assertEqual(tuple(row), (4242, "boot:123"))


class ServerTest(HomeBase):
    def test_the_server_keeps_a_rewrite_s_process_and_refuses_a_bad_one(self):
        from ag.ag_harness.server import Server
        srv = Server(lambda gatherer: self.m)
        for given, kept in (({"pid": 77, "started": "b:1"}, (77, "b:1")), ({"pid": "x"}, (None, None)), (None, (None, None))):
            body = {"op": "rewrite", "gatherer": "g", "properties": ch("c1"), "cwd": None,
                    "events": [{"type": "user_message", "id": f"u-{time.time_ns()}", "payload": {"role": "user", "content": "hi"},
                                "text": "hi"}]}
            if given is not None:
                body["process"] = given
            answer = srv.handle(body)
            row = self.m._conn("g").execute("SELECT pid, pid_started FROM _reads WHERE read_id = ?",
                                            (answer["read_id"],)).fetchone()
            self.assertEqual(tuple(row), kept, given)


if __name__ == "__main__":
    unittest.main()
