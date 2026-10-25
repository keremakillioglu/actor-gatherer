"""Codex sessions started from the dashboard (ag_dashboard/sessions.py): a turn per process through
`ag ... codex exec`, the interactive UI in a terminal, and the session renamed to the thread codex
chooses -- here a fake ag standing in for codex. No real agent runs."""
import json
import os
import sqlite3
import sys
import tempfile
import textwrap
import time
import unittest
import unittest.mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ag_dashboard import data, sessions  # noqa: E402
from ag_dashboard import home as dashboard_home  # noqa: E402

THREAD = "01a16f39-7f0a-7531-a545-d854579d7d68"
# A fake `ag ... codex`: writes its arguments (and an exec's stdin) to $FAKE_AG_LOG. `exec` answers as
# codex exec --json does: the thread (THREAD, or the one resumed), the reply, the turn's end. Run
# interactively it records a call from a child of its own process (codex's wrapper runs the real codex so)
# in the gatherer's database, as ag's hook would, with the thread as its channel -- after a side call that
# names no directory -- then waits for EOF.
FAKE_AG = textwrap.dedent("""
    import json, os, sqlite3, sys, time
    log = open(os.environ["FAKE_AG_LOG"], "a")
    argv = sys.argv[1:]
    gatherer = argv[argv.index("--gatherer") + 1]
    if "exec" in argv:
        message = sys.stdin.read()
        log.write(json.dumps({"argv": argv, "cwd": os.getcwd(), "stdin": message}) + "\\n"); log.flush()
        thread = argv[argv.index("resume") + 1] if "resume" in argv else %(thread)r
        time.sleep(float(os.environ.get("FAKE_AG_DELAY", "0")))
        print(json.dumps({"type": "thread.started", "thread_id": thread}), flush=True)
        if os.environ.get("FAKE_AG_FAIL"):
            print(json.dumps({"type": "turn.failed", "error": {"message": "model_not_found"}}), flush=True)
            sys.exit(1)
        print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "pong"}}), flush=True)
        print(json.dumps({"type": "turn.completed", "usage": {}}), flush=True)
        sys.exit(0)
    log.write(json.dumps({"argv": argv, "cwd": os.getcwd()}) + "\\n"); log.flush()
    path = os.path.join(os.environ["AG_HOME"], "gatherers", gatherer, "context.db")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS _reads (read_id INTEGER PRIMARY KEY, p_channel TEXT, p_cwd TEXT, pid INTEGER)")
    import subprocess
    child = subprocess.Popen(["sleep", "60"])
    conn.execute("INSERT INTO _reads (p_channel, p_cwd, pid) VALUES ('side-thread', NULL, ?)", (child.pid,))
    conn.execute("INSERT INTO _reads (p_channel, p_cwd, pid) VALUES ('elsewhere', '/x', 1)")
    conn.execute("INSERT INTO _reads (p_channel, p_cwd, pid) VALUES (?, ?, ?)", (%(thread)r, os.getcwd(), child.pid))
    conn.commit(); conn.close()
    os.write(1, b"fake codex\\r\\n")
    while True:
        got = os.read(0, 1024)
        if not got or got == b"\\x04":
            child.kill()
            sys.exit(0)
""") % {"thread": THREAD}


class CodexBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = dashboard_home.HOME
        dashboard_home.HOME = os.path.join(self.tmp.name, "ag")
        self.work = os.path.join(self.tmp.name, "work")
        os.makedirs(self.work)
        fake = os.path.join(self.tmp.name, "fake_ag.py")
        with open(fake, "w") as fh:
            fh.write(FAKE_AG)
        self.log = os.path.join(self.tmp.name, "fake.log")
        self.env = unittest.mock.patch.dict(os.environ, {"AG_COMMAND": f"{sys.executable} {fake}", "FAKE_AG_LOG": self.log,
                                                         "FAKE_AG_DELAY": "0"})
        self.env.start()
        self.s = sessions.Sessions()

    def tearDown(self):
        self.s.close()
        self.env.stop()
        dashboard_home.HOME = self.saved
        self.tmp.cleanup()

    def logged(self):
        try:
            with open(self.log) as fh:
                return [json.loads(line) for line in fh]
        except OSError:
            return []

    def until(self, check, timeout=10.0):
        end = time.time() + timeout
        while time.time() < end:
            got = check()
            if got:
                return got
            time.sleep(0.05)
        self.fail("timed out")

    def session(self, sid):
        return next((x for x in self.s.list() if x["session_id"] == sid), None)


class CreateTest(CodexBase):
    def test_a_codex_session_keeps_its_model_and_the_id_it_starts_under(self):
        made = self.s.create("g", self.work, harness="codex", model="gpt-5.6-luna")
        self.assertEqual((made["harness"], made["model"], made["started_as"]), ("codex", "gpt-5.6-luna", made["session_id"]))
        self.assertIsNone(self.s.create("g", self.work)["started_as"])        # Claude Code's id is its own
        for bad in ({"harness": "pi"}, {"harness": "codex", "model": "a b"}):
            with self.assertRaises(sessions.SessionError):
                self.s.create("g", self.work, **bad)

    def test_a_table_from_before_gets_the_new_columns(self):
        os.makedirs(dashboard_home.HOME, exist_ok=True)
        conn = sqlite3.connect(sessions.db_path())
        conn.execute("DROP TABLE IF EXISTS sessions")       # setUp's, made new
        conn.execute("CREATE TABLE sessions (session_id TEXT PRIMARY KEY, gatherer TEXT NOT NULL, harness TEXT NOT NULL, "
                     "cwd TEXT NOT NULL, permission_mode TEXT NOT NULL, created_at TEXT NOT NULL, turns INTEGER NOT NULL "
                     "DEFAULT 0, status TEXT NOT NULL, last_error TEXT)")
        conn.execute("INSERT INTO sessions VALUES ('old', 'g', 'claude', '/', 'auto', '2026-01-01', 1, 'stopped', NULL)")
        conn.commit(); conn.close()
        self.assertEqual({k: sessions.stored()[0][k] for k in ("kept", "model", "started_as")},
                         {"kept": 0, "model": None, "started_as": None})
        sessions.Sessions()
        conn = sqlite3.connect(sessions.db_path())
        have = {r[1] for r in conn.execute("PRAGMA table_info(sessions)")}
        conn.close()
        self.assertLessEqual({"kept", "model", "started_as"}, have)


class ExecTest(CodexBase):
    def test_a_message_is_a_codex_exec_turn_and_the_session_takes_the_thread_s_id(self):
        first = self.s.create("g", self.work, harness="codex", model="gpt-5.6-luna")["session_id"]
        self.s.send(first, "Reply with pong")
        done = self.until(lambda: (self.session(THREAD) or {}).get("turns") == 1 and self.session(THREAD))
        self.until(lambda: self.session(THREAD)["pid"] is None)
        run = self.logged()[0]
        self.assertEqual(run["argv"][:5], ["--gatherer", "g", "codex", "exec", "--json"])
        self.assertEqual(run["argv"][run["argv"].index("-m") + 1], "gpt-5.6-luna")
        self.assertIn("--approve-for-me", run["argv"])
        self.assertNotIn("resume", run["argv"])
        self.assertEqual((run["argv"][-1], run["stdin"], run["cwd"]), ("-", "Reply with pong", self.work))
        self.assertIsNone(self.session(first))
        self.assertEqual(done["started_as"], first)
        self.assertEqual(self.session(THREAD)["status"], "stopped")
        self.assertTrue(os.path.exists(sessions.log_path(THREAD)))

        self.s.send(THREAD, "again")                    # the next: the thread resumed
        self.until(lambda: self.session(THREAD)["turns"] == 2)
        again = self.logged()[1]["argv"]
        self.assertEqual(again[again.index("resume") + 1:], [THREAD, "-"])

    def test_a_message_sent_while_a_turn_runs_is_the_next_turn(self):
        os.environ["FAKE_AG_DELAY"] = "0.4"
        sid = self.s.create("g", self.work, harness="codex")["session_id"]
        self.s.send(sid, "one")
        self.s.send(sid, "two")
        self.until(lambda: (self.session(THREAD) or {}).get("turns") == 2)
        self.assertEqual([r["stdin"] for r in self.logged()], ["one", "two"])
        self.assertIn("resume", self.logged()[1]["argv"])
        self.assertNotIn("-m", self.logged()[0]["argv"])            # no model chosen: codex's own

    def test_a_failed_turn_says_why(self):
        os.environ["FAKE_AG_FAIL"] = "1"
        try:
            sid = self.s.create("g", self.work, harness="codex")["session_id"]
            self.s.send(sid, "hi")
            s = self.until(lambda: (self.session(THREAD) or {}).get("status") == "failed" and self.session(THREAD))
            self.assertEqual((s["last_error"], s["turns"]), ("model_not_found", 0))
        finally:
            del os.environ["FAKE_AG_FAIL"]


@unittest.skipUnless(sessions.TERMINALS, "a terminal needs a pseudo-terminal")
class TerminalTest(CodexBase):
    def test_a_codex_terminal_runs_its_ui_and_is_renamed_to_its_thread(self):
        first = self.s.create("g", self.work, harness="codex", model="gpt-5.6-luna")["session_id"]
        self.s.terminal(first, 100, 30)
        s = self.until(lambda: self.session(THREAD))
        self.assertEqual((s["terminal"], s["started_as"], s["turns"]), (True, first, 1))
        self.assertIsNone(self.session(first))
        argv = self.logged()[0]["argv"]
        self.assertEqual(argv[:4], ["--quiet", "--gatherer", "g", "codex"])
        self.assertEqual(argv[argv.index("-m") + 1], "gpt-5.6-luna")
        self.assertIn("--no-alt-screen", argv)
        self.assertNotIn("resume", argv)
        out = self.until(lambda: (self.s.output(THREAD, 0) or (b"",))[0])
        self.assertIn(b"fake codex", out)
        self.s.stop(THREAD)
        self.assertEqual(self.session(THREAD)["status"], "stopped")

        self.s.terminal(THREAD, 100, 30, fullscreen=True)    # opened again: resumed, its own screen
        self.until(lambda: len(self.logged()) == 2)
        again = self.logged()[1]["argv"]
        self.assertEqual(again[-2:], ["resume", THREAD])
        self.assertNotIn("--no-alt-screen", again)


class DataTest(CodexBase):
    def test_a_codex_session_with_a_directory_can_be_messaged(self):
        self.assertTrue(data.chattable({"harness": "codex", "cwd": "/w"}))
        self.assertFalse(data.chattable({"harness": "pi", "cwd": "/w"}))

    @unittest.skipUnless(os.path.isdir("/proc"), "needs /proc")
    def test_the_dashboard_s_own_terminal_is_its_own_though_codex_calls_from_a_child(self):
        import subprocess
        child = subprocess.Popen(["sleep", "30"])            # codex's real codex, under the wrapper the dashboard ran
        try:
            mine = {"harness": "codex", "cwd": "/w", "alive": True, "pid": child.pid, "session": {"pid": os.getpid()}}
            self.assertTrue(data.chattable(mine))
            self.assertFalse(data.chattable({**mine, "session": {"pid": child.pid + 100000}}))   # someone else's
            self.assertTrue(dashboard_home.runs_under(child.pid, os.getpid()))
            self.assertFalse(dashboard_home.runs_under(os.getpid(), child.pid))
            self.assertFalse(dashboard_home.runs_under(None, os.getpid()))
        finally:
            child.kill()
            child.wait()

    def test_models_come_from_codex_s_catalog(self):
        self.assertEqual(sessions.models("claude"), {"models": [], "default": None})
        bin_dir = os.path.join(self.tmp.name, "bin")
        os.makedirs(bin_dir)
        with open(os.path.join(bin_dir, "codex"), "w") as fh:
            fh.write("#!/bin/sh\necho '" + json.dumps({"models": [
                {"slug": "gpt-a", "display_name": "GPT-A", "description": "fast", "visibility": "list"},
                {"slug": "hidden", "visibility": "hide"}]}) + "'\n")
        os.chmod(os.path.join(bin_dir, "codex"), 0o755)
        codex_home = os.path.join(self.tmp.name, "codex")
        os.makedirs(codex_home)
        with open(os.path.join(codex_home, "config.toml"), "w") as fh:
            fh.write('model = "gpt-a"\n')
        sessions._models.clear()
        with unittest.mock.patch.dict(os.environ, {"PATH": bin_dir + os.pathsep + os.environ["PATH"], "CODEX_HOME": codex_home}):
            got = sessions.models("codex")
        sessions._models.clear()
        self.assertEqual(got, {"models": [{"slug": "gpt-a", "name": "GPT-A", "description": "fast"}], "default": "gpt-a"})


if __name__ == "__main__":
    unittest.main()
