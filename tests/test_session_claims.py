"""One process per session: ag records which process has each session open (`_open`, claimed by its
launcher and by each call), refuses a second one -- a launch, a call after /resume -- and the
dashboard's chat messages any closed Claude Code session, letting it go after each turn."""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import unittest.mock
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ag.ag_harness.home.__main__ import main as home_main  # noqa: E402
from ag.ag_harness.server import Server  # noqa: E402
from ag.ag_harness.store import operations as store  # noqa: E402
from ag.ag_harness.store import paths, schema  # noqa: E402
from ag.ag_harness.store.processes import identity  # noqa: E402
from ag.cli.launch import LaunchError  # noqa: E402
from ag.integrations.harnesses.claude.ag_orchestrator import context_manager as claude_ag  # noqa: E402
from ag.integrations.harnesses.claude.setup.launch import session_args  # noqa: E402
from ag.integrations.harnesses.codex.ag_orchestrator.ag_clients import AgClients  # noqa: E402
from ag.integrations.tools.hook_server.hook_server import Answer  # noqa: E402
from ag_dashboard import data, sessions  # noqa: E402
from test_dashboard import HomeBase  # noqa: E402
from test_dashboard_sessions import SessionsBase  # noqa: E402

LINUX = os.path.isdir("/proc")
SID = "0b9e7a52-61b1-4c9b-9a3e-5d2f3a1c7e10"


def sleeper():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    return child, identity(child.pid)


@unittest.skipUnless(LINUX, "no /proc: no process can be told")
class ClaimTest(HomeBase):
    def conn(self):
        return self.m._conn("g")

    def test_one_running_process_per_session(self):
        child, other = sleeper()
        self.addCleanup(child.kill)
        me = identity(os.getpid())
        self.assertIsNone(store.claim(self.conn(), "s1", other, "launcher"))
        self.assertIsNone(store.claim(self.conn(), "s1", other, "call"))         # again: still its
        held = store.claim(self.conn(), "s1", me, "launcher")
        self.assertEqual((held["pid"], held["opened_by"]), (child.pid, "launcher"))
        self.assertEqual(store.holder(self.conn(), "s1")["pid"], child.pid)
        child.kill()
        child.wait()
        self.assertIsNone(store.holder(self.conn(), "s1"))                         # it ended: holds nothing
        self.assertIsNone(store.claim(self.conn(), "s1", me, "launcher"))
        self.assertEqual(store.holder(self.conn(), "s1")["pid"], os.getpid())

    def test_a_process_holds_one_session(self):
        me = identity(os.getpid())
        store.claim(self.conn(), "s1", me, "call")
        store.claim(self.conn(), "s2", me, "call")                                 # /resume to another
        self.assertIsNone(store.holder(self.conn(), "s1"))
        self.assertEqual(store.holder(self.conn(), "s2")["pid"], os.getpid())

    def test_the_server_s_claim(self):
        child, other = sleeper()
        self.addCleanup(child.kill)
        srv = Server(lambda gatherer: self.m)
        self.assertEqual(srv.handle({"op": "claim", "gatherer": "g", "session": "s1", "process": other}), {"claimed": True})
        got = srv.handle({"op": "claim", "gatherer": "g", "session": "s1", "process": identity(os.getpid())})
        self.assertEqual((got["claimed"], got["holder"]["pid"]), (False, child.pid))
        self.assertIn("error", srv.handle({"op": "claim", "gatherer": "g", "session": "s1", "process": {"pid": "x"}}))

    def test_the_home_command_the_launcher_runs(self):
        child, other = sleeper()
        self.addCleanup(child.kill)
        with unittest.mock.patch("sys.stdout"):
            self.assertEqual(home_main(["claim", "g", "s1", "--pid", str(child.pid)]), 0)
            self.assertEqual(home_main(["claim", "g", "s1", "--pid", str(os.getpid())]), 3)     # held: refused
        self.assertEqual(store.holder(self.conn(), "s1")["opened_by"], "launcher")

    def test_the_dashboard_sees_who_has_it_open(self):
        child, other = sleeper()
        self.addCleanup(child.kill)
        store.claim(self.conn(), "c1", other, "launcher")
        a = next(a for g in data.home()["gatherers"] for a in g["agents"] if a["channel"] == "c1")
        self.assertEqual((a["holder"]["pid"], a["alive"]), (child.pid, True))
        self.assertEqual(sessions.holder("g", "c1")["pid"], child.pid)
        child.kill()
        child.wait()
        a = next(a for g in data.home()["gatherers"] for a in g["agents"] if a["channel"] == "c1")
        self.assertNotIn("holder", a)
        self.assertIsNone(sessions.holder("g", "c1"))


class SessionArgsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = {"CLAUDE_CONFIG_DIR": self.tmp.name}

    def test_the_session_a_run_opens(self):
        self.assertEqual(session_args(["--resume", SID, "-p"], self.env, "/w"), (["--resume", SID, "-p"], SID))
        self.assertEqual(session_args([f"--resume={SID}"], self.env, "/w"), (["--resume", SID], SID))
        self.assertEqual(session_args(["-r", SID], self.env, "/w"), (["--resume", SID], SID))
        self.assertEqual(session_args(["--session-id", SID], self.env, "/w"), (["--session-id", SID], SID))
        self.assertEqual(session_args(["--resume", SID, "--fork-session"], self.env, "/w")[1], None)   # a new one
        self.assertEqual(session_args(["-p", "hi"], self.env, "/w"), (["-p", "hi"], None))

    def test_resume_with_no_id_is_refused(self):
        for args in (["--resume"], ["-r"], ["--resume", "-p"], ["--resume", "my search"]):
            with self.assertRaises(LaunchError, msg=args):
                session_args(args, self.env, "/w")

    def test_continue_is_the_newest_session_of_the_directory(self):
        d = os.path.join(self.tmp.name, "projects", "-w-my-proj")
        os.makedirs(d)
        older, newer = SID, SID[:-1] + "1"
        for name, at in ((older, 100), (newer, 200)):
            open(os.path.join(d, name + ".jsonl"), "w").close()
            os.utime(os.path.join(d, name + ".jsonl"), (at, at))
        self.assertEqual(session_args(["--continue", "-p"], self.env, "/w/my_proj"), (["--resume", newer, "-p"], newer))
        self.assertEqual(session_args(["-c"], self.env, "/elsewhere"), (["-c"], None))      # none: Claude Code says so


class HookRefusalTest(unittest.TestCase):
    class Client:
        def __init__(self, claimed):
            self.claimed, self.asked = claimed, []

        async def request(self, op, body=None, timeout=None):
            self.asked.append(op)
            if op == "claim":
                return {"claimed": True} if self.claimed else {"claimed": False, "holder": {"pid": 4242, "opened_at": "t"}}
            return {"context": body["events"], "note": "ok"}

        async def stop(self):
            pass

    def call(self, client, process):
        hook = claude_ag.ClaudeContextManager(ag_clients=AgClients(lambda gatherer: client), log=lambda g, l: None)
        req = SimpleNamespace(method="POST", path="/v1/messages", label="g", headers={"X-Claude-Code-Session-Id": "sess"},
                              body={"model": "m", "tools": [{"name": "Bash"}],
                                    "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]},
                              process=process, state={})
        return asyncio.run(hook(req))

    def test_a_call_on_a_session_another_process_has_open_is_refused(self):
        client = self.Client(claimed=False)
        out = self.call(client, {"pid": 1, "started": "b:1"})
        self.assertIsInstance(out, Answer)
        self.assertEqual(out.status, 400)
        self.assertIn("4242", out.body["error"]["message"])
        self.assertEqual(client.asked, ["claim"])                        # nothing stored

    def test_claimed_or_not_told_it_goes_on(self):
        client = self.Client(claimed=True)
        self.call(client, {"pid": 1, "started": "b:1"})
        self.assertEqual(client.asked[:2], ["claim", "rewrite"])
        client = self.Client(claimed=False)
        self.call(client, None)                                          # no process known: not asked
        self.assertEqual(client.asked, ["rewrite"])


class ChattableTest(unittest.TestCase):
    def test_the_rule(self):
        base = {"harness": "claude", "cwd": "/w"}
        self.assertTrue(data.chattable(base))
        self.assertTrue(data.chattable({**base, "alive": False}))
        self.assertFalse(data.chattable({**base, "alive": True}))                            # its last call's process runs
        self.assertFalse(data.chattable({**base, "holder": {"pid": 9}}))
        self.assertTrue(data.chattable({**base, "holder": {"pid": 9, "dashboard": True}}))  # the dashboard's own
        self.assertFalse(data.chattable({**base, "harness": "codex"}))
        self.assertFalse(data.chattable({"harness": "claude"}))                              # nowhere to resume it


class AdoptTest(SessionsBase):
    def gatherer_with(self, session_id, cwd, process=None):
        """Gatherer `g` with a read of `session_id` in `cwd` (by `process`), as ag writes it."""
        saved = paths.TRACE_DIR
        paths.TRACE_DIR = os.path.join(sessions.home.HOME, "gatherers")
        self.addCleanup(setattr, paths, "TRACE_DIR", saved)
        conn = schema.connect("g")
        conn.execute("ALTER TABLE _reads ADD COLUMN p_channel")
        conn.execute("ALTER TABLE _reads ADD COLUMN p_cwd")
        conn.execute("INSERT INTO _reads (read_at, p_channel, p_cwd, pid, pid_started) VALUES ('t', ?, ?, ?, ?)",
                     (session_id, cwd, *((process["pid"], process["started"]) if process else (None, None))))
        conn.commit()
        return conn

    def test_a_closed_session_is_resumed_where_it_worked_and_let_go(self):
        self.gatherer_with(SID, self.work)
        s = self.s.adopt("g", SID)
        self.assertEqual((s["cwd"], s["turns"], s["permission_mode"]), (self.work, 1, "auto"))
        self.s.send(SID, "hello")
        self.until(lambda: self.session(SID)["turns"] == 2)
        self.until(lambda: self.session(SID)["status"] == "stopped")
        run = [x for x in self.logged() if "argv" in x][0]["argv"]
        self.assertEqual(run[run.index("--resume") + 1], SID)
        self.assertEqual(os.path.realpath([x for x in self.logged() if "argv" in x][0]["cwd"]), os.path.realpath(self.work))

    @unittest.skipUnless(LINUX, "no /proc")
    def test_a_session_open_elsewhere_is_not_messaged(self):
        child, other = sleeper()
        self.addCleanup(child.kill)
        conn = self.gatherer_with(SID, self.work)
        store.claim(conn, SID, other, "launcher")
        self.s.adopt("g", SID)
        with self.assertRaises(sessions.SessionError):
            self.s.send(SID, "hello")
        self.assertFalse(os.path.exists(self.log))                        # no agent started
        child.kill()
        child.wait()
        self.s.send(SID, "hello")                                         # closed there: messaged here
        self.until(lambda: self.session(SID)["turns"] == 2)

    def test_what_it_refuses(self):
        with self.assertRaises(sessions.SessionError):
            self.s.adopt("g", "not-a-session")
        self.gatherer_with(SID, os.path.join(self.work, "gone"))
        with self.assertRaises(sessions.SessionError):
            self.s.adopt("g", SID)


if __name__ == "__main__":
    unittest.main()
