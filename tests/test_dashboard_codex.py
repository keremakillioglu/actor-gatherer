"""Codex sessions started from the dashboard (ag_dashboard/sessions.py): a turn per process through
`ag ... codex exec`, the interactive UI in a terminal, and the session kept under the dashboard's id
from its start (`ag --channel`), codex's own thread its `harness_id` -- here a fake ag standing in for
codex. No real agent runs."""
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
# interactively it records its turn's call in the gatherer's database as ag's hook would: in the channel
# ag was given (`--channel`, else the thread's own), naming the thread where that is not the channel --
# and ag's read for it.
FAKE_AG = textwrap.dedent("""
    import json, os, sqlite3, sys, time
    log = open(os.environ["FAKE_AG_LOG"], "a")
    argv = sys.argv[1:]
    gatherer = argv[argv.index("--gatherer") + 1]
    thread = argv[argv.index("resume") + 1] if "resume" in argv else %(thread)r
    if "exec" in argv:
        message = sys.stdin.read()
        log.write(json.dumps({"argv": argv, "cwd": os.getcwd(), "stdin": message}) + "\\n"); log.flush()
        time.sleep(float(os.environ.get("FAKE_AG_DELAY", "0")))
        print(json.dumps({"type": "thread.started", "thread_id": thread}), flush=True)
        if os.environ.get("FAKE_AG_FAIL"):
            print(json.dumps({"type": "turn.failed", "error": {"message": "model_not_found"}}), flush=True)
            sys.exit(1)
        print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "pong"}}), flush=True)
        print(json.dumps({"type": "turn.completed", "usage": {}}), flush=True)
        sys.exit(0)
    log.write(json.dumps({"argv": argv, "cwd": os.getcwd()}) + "\\n"); log.flush()
    channel = argv[argv.index("--channel") + 1] if "--channel" in argv else thread
    path = os.path.join(os.environ["AG_HOME"], "gatherers", gatherer, "context.db")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript("CREATE TABLE IF NOT EXISTS event_types (event_type_id INTEGER PRIMARY KEY, name TEXT UNIQUE);"
                       "CREATE TABLE IF NOT EXISTS events (row_id INTEGER PRIMARY KEY, event_type_id INT, "
                       "payload_json TEXT, p_channel TEXT); INSERT OR IGNORE INTO event_types (name) VALUES ('model_call');")
    call = {"kind": "turn", "harness": "codex", "run": str(os.getpid()), **({"session": thread} if thread != channel else {})}
    conn.execute("INSERT INTO events (event_type_id, payload_json, p_channel) VALUES ((SELECT event_type_id FROM "
                 "event_types WHERE name = 'model_call'), ?, ?)", (json.dumps(call), channel))
    conn.execute("CREATE TABLE IF NOT EXISTS _reads (read_id INTEGER PRIMARY KEY, p_channel TEXT, p_cwd TEXT, run TEXT)")
    conn.execute("INSERT INTO _reads (p_channel, p_cwd, run) VALUES (?, ?, ?)", (channel, os.getcwd(), str(os.getpid())))
    conn.commit(); conn.close()
    os.write(1, b"fake codex\\r\\n")
    while True:
        got = os.read(0, 1024)
        if not got or got == b"\\x04":
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
        os.makedirs(dashboard_home.HOME)                  # a message to codex exec; ChatTerminalTest: the default
        with open(os.path.join(dashboard_home.HOME, "config.toml"), "w") as fh:
            fh.write('[dashboard]\nchat = "headless"\n')
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
    def test_a_codex_session_keeps_its_model_and_its_id_is_the_dashboard_s(self):
        made = self.s.create("g", self.work, harness="codex", model="gpt-5.6-luna")
        self.assertEqual((made["harness"], made["model"], made["started_as"], made["harness_id"]),
                         ("codex", "gpt-5.6-luna", None, None))           # its thread's, once its first call names it
        self.assertEqual(sessions.channel_args(made), ["--channel", made["session_id"]])
        claude = self.s.create("g", self.work)
        self.assertEqual((claude["started_as"], sessions.channel_args(claude)), (None, []))   # its id is its own
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
        self.assertEqual({k: sessions.stored()[0][k] for k in ("kept", "model", "started_as", "harness_id")},
                         {"kept": 0, "model": None, "started_as": None, "harness_id": None})
        sessions.Sessions()
        conn = sqlite3.connect(sessions.db_path())
        have = {r[1] for r in conn.execute("PRAGMA table_info(sessions)")}
        conn.close()
        self.assertLessEqual({"kept", "model", "started_as", "harness_id"}, have)


class ExecTest(CodexBase):
    def test_a_message_is_a_codex_exec_turn_its_session_keeping_its_id_and_resumed_by_its_thread(self):
        sid = self.s.create("g", self.work, harness="codex", model="gpt-5.6-luna")["session_id"]
        self.s.send(sid, "Reply with pong")
        done = self.until(lambda: self.session(sid)["turns"] == 1 and self.session(sid))
        self.until(lambda: self.session(sid)["pid"] is None)
        run = self.logged()[0]
        self.assertEqual(run["argv"][:7], ["--gatherer", "g", "--channel", sid, "codex", "exec", "--json"])
        self.assertEqual(run["argv"][run["argv"].index("-m") + 1], "gpt-5.6-luna")
        self.assertIn("--approve-for-me", run["argv"])
        self.assertNotIn("resume", run["argv"])
        self.assertEqual((run["argv"][-1], run["stdin"]), ("-", "Reply with pong"))
        self.assertEqual(os.path.realpath(run["cwd"]), os.path.realpath(self.work))   # macOS: /var is /private/var
        self.assertEqual((done["harness_id"], done["started_as"]), (THREAD, None))   # codex's thread, named by it
        self.assertIsNone(self.session(THREAD))                                     # no session of the thread's id
        self.assertEqual(self.session(sid)["status"], "stopped")
        self.assertGreater(self.session(sid)["kept"], 0)  # its process gone with its turn: Idle, not Closed
        self.assertEqual(self.session(sid)["ended"], 0)
        self.assertTrue(os.path.exists(sessions.log_path(sid)))

        self.s.send(sid, "again")                        # the next: the thread resumed, in the same channel
        self.until(lambda: self.session(sid)["turns"] == 2)
        again = self.logged()[1]["argv"]
        self.assertEqual(again[again.index("--channel") + 1], sid)
        self.assertEqual(again[again.index("resume") + 1:], [THREAD, "-"])

    def test_a_message_from_chat_is_kept_in_its_channel_at_once(self):
        with unittest.mock.patch.object(sessions.actions, "chat_sent") as kept:
            sid = self.s.create("g", self.work, harness="codex")["session_id"]
            before = time.time()
            self.s.send(sid, "Reply with pong")
            [(args, _)] = kept.call_args_list                       # kept as sent, before codex has named its thread
            self.assertEqual(args[:3], ("g", sid, "Reply with pong"))
            self.assertTrue(before <= args[3] <= time.time())
            self.until(lambda: self.session(sid)["turns"] == 1)
            self.s.send(sid, "again")
            self.assertEqual(kept.call_args_list[-1].args[:3], ("g", sid, "again"))
            self.assertEqual(len({a.args[4] for a in kept.call_args_list}), 2)   # each send with an id of its own

    def test_a_message_sent_while_a_turn_runs_is_the_next_turn(self):
        os.environ["FAKE_AG_DELAY"] = "0.4"
        sid = self.s.create("g", self.work, harness="codex")["session_id"]
        self.s.send(sid, "one")
        self.s.send(sid, "two")
        self.until(lambda: self.session(sid)["turns"] == 2)
        self.assertEqual([r["stdin"] for r in self.logged()], ["one", "two"])
        self.assertIn("resume", self.logged()[1]["argv"])
        self.assertNotIn("-m", self.logged()[0]["argv"])            # no model chosen: codex's own

    def test_a_failed_turn_says_why(self):
        os.environ["FAKE_AG_FAIL"] = "1"
        try:
            sid = self.s.create("g", self.work, harness="codex")["session_id"]
            self.s.send(sid, "hi")
            s = self.until(lambda: self.session(sid)["status"] == "failed" and self.session(sid))
            self.assertEqual((s["last_error"], s["turns"]), ("model_not_found", 0))
        finally:
            del os.environ["FAKE_AG_FAIL"]


class OwnIdTest(CodexBase):
    """The harness's own id for a session (`own_id`): what it is resumed, renamed and found by in codex's own records."""

    def calls(self, rows):
        path = os.path.join(dashboard_home.HOME, "gatherers", "g", "context.db")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        conn = sqlite3.connect(path)
        conn.executescript("CREATE TABLE event_types (event_type_id INTEGER PRIMARY KEY, name TEXT);"
                           "CREATE TABLE events (row_id INTEGER PRIMARY KEY, event_type_id INT, payload_json TEXT, "
                           "p_channel TEXT); INSERT INTO event_types VALUES (1, 'model_call'), (2, 'name');")
        for channel, payload, type_id in rows:
            conn.execute("INSERT INTO events (event_type_id, payload_json, p_channel) VALUES (?, ?, ?)",
                         (type_id, json.dumps(payload), channel))
        conn.commit()
        conn.close()

    def test_its_thread_as_its_calls_name_it(self):
        self.calls([("dash-1", {"kind": "turn", "session": "t-old"}, 1),
                    ("dash-1", {"kind": "turn", "session": THREAD}, 1),      # the newest names it
                    ("dash-1", {"kind": "turn"}, 1),
                    ("dash-1", {"session": "not-a-call"}, 2),
                    (THREAD, {"kind": "turn"}, 1)])                         # a session from before: its own id
        row = {"session_id": "dash-1", "gatherer": "g", "harness": "codex"}
        self.assertEqual(sessions.own_id(row), THREAD)
        self.assertEqual(sessions.own_id({**row, "harness_id": "kept"}), "kept")        # the row's, where it has one
        self.assertEqual(sessions.own_id({**row, "session_id": THREAD, "started_as": "dash-0"}), THREAD)  # moved before
        self.assertEqual(sessions.own_id({**row, "session_id": "dash-2"}), "dash-2")    # no call yet
        self.assertEqual(sessions.own_id({**row, "harness": "claude"}), "dash-1")       # its id its own: not read
        self.assertEqual(sessions.own_id({**row, "gatherer": "nowhere"}), "dash-1")     # no database yet


@unittest.skipUnless(sessions.TERMINALS, "a terminal needs a pseudo-terminal")
class TerminalTest(CodexBase):
    def test_a_codex_terminal_runs_its_ui_under_its_id_for_good(self):
        sid = self.s.create("g", self.work, harness="codex", model="gpt-5.6-luna")["session_id"]
        self.s.terminal(sid, 100, 30)
        self.until(lambda: self.logged())
        argv = self.logged()[0]["argv"]
        self.assertEqual(argv[:6], ["--quiet", "--gatherer", "g", "--channel", sid, "codex"])
        self.assertEqual(argv[6:8], ["-c", 'projects={"%s"={trust_level="trusted"}}' % os.path.realpath(self.work)])
        self.assertEqual(argv[argv.index("-m") + 1], "gpt-5.6-luna")
        self.assertIn("--no-alt-screen", argv)
        self.assertNotIn("resume", argv)
        out = self.until(lambda: (self.s.output(sid, 0) or (b"",))[0])
        self.assertIn(b"fake codex", out)
        self.until(lambda: sessions.own_id(self.session(sid)) == THREAD)      # its first call named its thread
        self.assertEqual([x["session_id"] for x in self.s.list()], [sid])    # one session, never renamed
        self.s.stop(sid)
        self.assertEqual(self.session(sid)["status"], "stopped")

        self.s.terminal(sid, 100, 30, fullscreen=True)     # opened again: its thread resumed, its own screen
        self.until(lambda: len(self.logged()) == 2)
        again = self.logged()[1]["argv"]
        self.assertEqual(again[again.index("--channel") + 1], sid)
        self.assertEqual(again[-2:], ["resume", THREAD])
        self.assertNotIn("--no-alt-screen", again)
        self.assertEqual(self.session(sid)["harness_id"], THREAD)            # kept on its row once known


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
