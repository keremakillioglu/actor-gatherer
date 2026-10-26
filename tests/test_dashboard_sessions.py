"""Sessions started from the dashboard (ag_dashboard/sessions.py): its table, the agent it runs
for each through ag -- here a fake ag that answers each message with a result line -- and the
server's endpoints for them. No real agent runs."""
import base64
import json
import os
import sqlite3
import struct
import sys
import tempfile
import textwrap
import threading
import time
import unittest
import unittest.mock
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ag_dashboard import data, hiding, saved, seen, server, sessions  # noqa: E402
from ag_dashboard import home as dashboard_home  # noqa: E402

# A fake `ag`: writes its arguments, then each message it is sent, to $FAKE_AG_LOG; answers each
# after $FAKE_AG_DELAY seconds with a result line; exits when its stdin closes. `new G` makes G's
# config in $AG_HOME, as ag's does. In a terminal, resized, it clears its screen and says its size, as a
# full screen draws all of it again.
FAKE_AG = textwrap.dedent("""
    import json, os, sys, time
    if sys.argv[1:2] == ["home"]:                       # `ag home hold ...`: it has the session
        open(os.environ["FAKE_AG_LOG"] + ".home", "a").write(json.dumps(sys.argv[2:]) + "\\n")
        sys.exit(0)
    if sys.argv[1:2] == ["new"]:
        os.makedirs(os.path.join(os.environ["AG_HOME"], "gatherers", sys.argv[2]))
        open(os.path.join(os.environ["AG_HOME"], "gatherers", sys.argv[2], "gatherer.toml"), "w").write('policy = "p"\\n')
        sys.exit(0)
    log = open(os.environ["FAKE_AG_LOG"], "a")
    log.write(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd(),
                          "base_url": os.environ.get("ANTHROPIC_BASE_URL"), "claudecode": os.environ.get("CLAUDECODE")}) + "\\n")
    log.flush()
    if "-p" not in sys.argv:                            # interactive, in a terminal: says its size, echoes what is typed
        import signal, tty
        tty.setraw(0)
        size = lambda: "%dx%d" % tuple(os.get_terminal_size(0))
        signal.signal(signal.SIGWINCH, lambda *_: os.write(1, ("\\x1b[2J[resized %s]\\r\\n" % size()).encode()))
        os.write(1, ("fake terminal %s tty=%s term=%s alt=%s\\r\\n" % (size(), os.isatty(0), os.environ.get("TERM"),
                                                                     os.environ.get("CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN"))).encode())
        while True:
            try:
                got = os.read(0, 1024)
            except InterruptedError:
                continue
            if not got or got == b"\\x04":
                sys.exit(0)
            log.write(json.dumps({"typed": got.decode()}) + "\\n"); log.flush()
            os.write(1, b"[got " + got.replace(b"\\x1b", b"ESC") + b"]\\r\\n")
    for line in sys.stdin:
        message = json.loads(line)["message"]["content"]
        log.write(json.dumps({"message": message}) + "\\n"); log.flush()
        time.sleep(float(os.environ.get("FAKE_AG_DELAY", "0")))
        print(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "ok"}]}}), flush=True)
        print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "ok"}), flush=True)
""")


class SessionsBase(unittest.TestCase):
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
        self.chat("headless")                     # a message to the agent with no screen; ChatTerminalTest: the default
        self.s = sessions.Sessions()

    def tearDown(self):
        self.s.close()
        self.env.stop()
        dashboard_home.HOME = self.saved
        self.tmp.cleanup()

    def chat(self, mode):
        """The home's `[dashboard] chat` (sessions.py's `chat_mode`), in its config.toml; None: no config.toml."""
        path = os.path.join(dashboard_home.HOME, "config.toml")
        if mode is None:
            if os.path.exists(path):
                os.remove(path)
            return
        os.makedirs(dashboard_home.HOME, exist_ok=True)
        with open(path, "w") as fh:
            fh.write(f'[dashboard]\nchat = "{mode}"\n')

    def logged(self):
        with open(self.log) as fh:
            return [json.loads(line) for line in fh]

    def until(self, check, timeout=10.0):
        end = time.time() + timeout
        while time.time() < end:
            got = check()
            if got:
                return got
            time.sleep(0.05)
        self.fail("timed out")

    def held(self):
        try:
            with open(self.log + ".home") as fh:
                return [json.loads(line) for line in fh]
        except OSError:
            return []

    def session(self, sid):
        return next(x for x in self.s.list() if x["session_id"] == sid)


class TableTest(SessionsBase):
    def test_a_new_session_is_a_row(self):
        made = self.s.create("g", self.work)
        conn = sqlite3.connect(os.path.join(dashboard_home.HOME, "dashboard.db"))
        rows = conn.execute("SELECT session_id, gatherer, harness, cwd, permission_mode, turns, status FROM sessions").fetchall()
        conn.close()
        self.assertEqual(rows, [(made["session_id"], "g", "claude", self.work, "auto", 0, "stopped")])
        self.assertEqual(sessions.stored()[0]["session_id"], made["session_id"])

    def test_what_it_refuses(self):
        for gatherer, cwd, mode in (("a b", self.work, "auto"), ("g", os.path.join(self.work, "none"), "auto"),
                                    ("g", self.work, "yolo")):
            with self.assertRaises(sessions.SessionError):
                self.s.create(gatherer, cwd, mode)
        with self.assertRaises(sessions.SessionError):
            self.s.send("no-such-session", "hi")
        sid = self.s.create("g", self.work)["session_id"]
        with self.assertRaises(sessions.SessionError):
            self.s.send(sid, "   ")

    def test_a_dashboard_restarted_finds_its_sessions_stopped(self):
        sid = self.s.create("g", self.work)["session_id"]
        self.s._set(sid, status="running")
        self.assertEqual([x["status"] for x in sessions.Sessions().list()], ["stopped"])


class AgentTest(SessionsBase):
    def test_the_first_message_starts_the_agent_through_ag(self):
        sid = self.s.create("g", self.work, "acceptEdits")["session_id"]
        self.s.send(sid, "hello")
        self.until(lambda: self.session(sid)["turns"] == 1)
        run, said = self.logged()
        self.assertEqual(run["argv"][:3], ["--gatherer", "g", "claude"])
        for flag, value in (("--session-id", sid), ("--permission-mode", "acceptEdits"), ("--input-format", "stream-json"),
                            ("--output-format", "stream-json"), ("--permission-prompts", "none")):
            self.assertEqual(run["argv"][run["argv"].index(flag) + 1], value)
        self.assertNotIn("--resume", run["argv"])
        self.assertEqual(os.path.realpath(run["cwd"]), os.path.realpath(self.work))
        self.assertEqual(said, {"message": "hello"})
        self.until(lambda: self.held()[-1:] == [["hold", "g", sid, "--pid", str(self.s.agents[sid].proc.pid), "--yields"]])
        self.assertEqual((self.session(sid)["status"], self.session(sid)["last_error"]), ("idle", None))   # kept, giving way
        self.assertTrue(os.path.exists(sessions.log_path(sid)))

    def test_an_idle_agent_closed_from_the_page_ends_and_the_next_message_resumes_it(self):
        sid = self.s.create("g", self.work)["session_id"]
        with self.assertRaises(sessions.SessionError):                      # no process yet
            self.s.stop(sid)
        os.environ["FAKE_AG_DELAY"] = "0.4"
        self.s.send(sid, "one")
        self.until(lambda: self.s.agents.get(sid) and self.s.agents[sid].yielding)
        self.s.stop(sid)
        self.until(lambda: self.session(sid)["status"] == "stopped" and sid not in self.s.agents)
        self.assertIsNone(self.session(sid)["last_error"])
        self.s.send(sid, "two")
        self.until(lambda: self.session(sid)["turns"] == 2)
        runs = [x["argv"] for x in self.logged() if "argv" in x and x["argv"][:1] == ["--gatherer"]]
        self.assertEqual(len(runs), 2)
        self.assertEqual(runs[1][runs[1].index("--resume") + 1], sid)

    def test_an_agent_closed_mid_turn_is_cut_off_and_the_next_message_starts_it_again(self):
        sid = self.s.create("g", self.work)["session_id"]
        os.environ["FAKE_AG_DELAY"] = "5"
        self.s.send(sid, "one")
        self.s.send(sid, "two")                                             # waits: dropped with the turn
        self.until(lambda: os.path.exists(self.log) and {"message": "one"} in self.logged())   # its turn runs
        self.s.stop(sid)
        self.until(lambda: self.session(sid)["status"] == "stopped" and sid not in self.s.agents, timeout=3)
        self.assertIsNone(self.session(sid)["last_error"])
        self.assertEqual(self.session(sid)["turns"], 0)                    # no call through ag: nothing to resume
        os.environ["FAKE_AG_DELAY"] = "0"
        self.s.send(sid, "three")
        self.until(lambda: self.session(sid)["turns"] == 1)
        runs = [x["argv"] for x in self.logged() if "argv" in x and x["argv"][:1] == ["--gatherer"]]
        self.assertEqual(runs[1][runs[1].index("--session-id") + 1], sid)

    def test_one_agent_takes_every_turn_and_a_message_waits_for_the_turn(self):
        os.environ["FAKE_AG_DELAY"] = "0.4"
        sid = self.s.create("g", self.work)["session_id"]
        self.s.send(sid, "one")
        self.assertEqual(self.s.send(sid, "two")["queued"], ["two"])      # the first turn still runs
        self.until(lambda: self.session(sid)["turns"] == 2)
        got = self.logged()
        self.assertEqual(len([x for x in got if "argv" in x]), 1)            # one process
        self.assertEqual([x["message"] for x in got if "message" in x], ["one", "two"])
        self.assertEqual(self.session(sid)["queued"], [])

    def test_the_next_message_goes_on_the_same_process_which_stops_giving_way_first(self):
        sid = self.s.create("g", self.work)["session_id"]
        self.s.send(sid, "one")
        self.until(lambda: self.s.agents[sid].yielding)
        self.s.send(sid, "two")
        self.until(lambda: self.session(sid)["turns"] == 2)
        self.assertEqual(len([x for x in self.logged() if "argv" in x]), 1)
        self.assertEqual([h[-1] for h in self.held()][:3], ["--yields", "--keeps", "--yields"])

    def test_an_agent_gone_is_started_again_resuming_the_session(self):
        sid = self.s.create("g", self.work)["session_id"]
        self.s.send(sid, "one")
        self.until(lambda: self.s.agents[sid].yielding)
        self.s.agents[sid].proc.terminate()                                  # taken over: stopped as it gave way
        self.until(lambda: self.session(sid)["status"] == "stopped")
        self.assertIsNone(self.session(sid)["last_error"])
        self.s.send(sid, "two")
        self.until(lambda: self.session(sid)["turns"] == 2)
        second = [x for x in self.logged() if "argv" in x][1]["argv"]
        self.assertEqual(second[second.index("--resume") + 1], sid)
        self.assertNotIn("--session-id", second)

    def test_each_change_of_a_session_is_told_for_the_page_s_live_updates(self):
        rung = []
        s = sessions.Sessions(on_change=lambda g, sid: rung.append((g, sid)))
        try:
            sid = s.create("g", self.work)["session_id"]
            s.send(sid, "hello")
            self.until(lambda: next(x for x in s.list() if x["session_id"] == sid)["turns"] == 1)
        finally:
            s.close()
        self.assertTrue(rung and all(r == ("g", sid) for r in rung))
        self.assertGreaterEqual(len(rung), 3)                 # made, running, idle

    def test_the_agent_is_not_run_as_part_of_the_dashboard_s_own_session(self):
        hooked = {"ANTHROPIC_BASE_URL": "http://127.0.0.1:4113/h/making_ag/l/967000", "CLAUDECODE": "1",
                  "CLAUDE_CODE_SESSION_ID": "parent", "PATH": "/bin"}
        env = sessions.agent_env(hooked)
        self.assertNotIn("ANTHROPIC_BASE_URL", env)
        self.assertNotIn("CLAUDECODE", env)
        self.assertNotIn("CLAUDE_CODE_SESSION_ID", env)
        self.assertEqual((env["PATH"], env["AG_HOME"]), ("/bin", dashboard_home.HOME))
        own = sessions.agent_env({"ANTHROPIC_BASE_URL": "https://gateway.example.com"})   # the user's own: kept
        self.assertEqual(own["ANTHROPIC_BASE_URL"], "https://gateway.example.com")


@unittest.skipUnless(sessions.TERMINALS, "a terminal needs a Unix pseudo-terminal")
class TerminalTest(SessionsBase):
    def screen(self, sid):
        got = self.s.output(sid, -1)
        return got[0].decode("utf-8", "replace") if got else ""

    def started(self, sid, cols=120, rows=32):
        self.s.terminal(sid, cols, rows)
        self.until(lambda: "fake terminal" in self.screen(sid))

    def test_a_terminal_runs_the_interactive_ui_through_ag_in_a_pseudo_terminal(self):
        sid = self.s.create("g", self.work)["session_id"]
        self.started(sid, 100, 30)
        self.assertIn("fake terminal 100x30 tty=True term=xterm-256color alt=1", self.screen(sid))     # Claude Code's classic screen
        run = self.logged()[0]
        self.assertNotIn("-p", run["argv"])
        self.assertEqual(run["argv"][:4], ["--quiet", "--gatherer", "g", "claude"])   # ag's notes not on its screen
        self.assertEqual(run["argv"][-2:], ["--session-id", sid])
        self.assertEqual(os.path.realpath(run["cwd"]), os.path.realpath(self.work))   # macOS: /var is /private/var
        self.assertEqual(self.session(sid)["status"], "terminal")
        self.assertTrue(self.session(sid)["terminal"])
        self.assertEqual(self.session(sid)["pid"], self.s.terms[sid].pid)

    def test_a_terminal_asked_for_full_screen_runs_the_screen_its_settings_choose(self):
        sid = self.s.create("g", self.work)["session_id"]
        self.assertFalse(self.session(sid)["fullscreen"])
        with unittest.mock.patch.dict(os.environ, sessions.CLASSIC):             # the dashboard's own environment classic
            self.s.terminal(sid, 100, 30, fullscreen=True)
        self.until(lambda: "fake terminal" in self.screen(sid))
        self.assertIn("fake terminal 100x30 tty=True term=xterm-256color alt=None", self.screen(sid))
        self.assertTrue(self.session(sid)["fullscreen"])

    def test_what_is_typed_and_the_size_reach_it_and_what_it_prints_comes_back(self):
        sid = self.s.create("g", self.work)["session_id"]
        self.started(sid, 100, 30)
        _, at, _, _ = self.s.output(sid, -1)
        self.s.type(sid, "\x1b")                       # Esc, as typed
        self.until(lambda: "[got ESC]" in self.screen(sid))
        out, end, reset, code = self.s.output(sid, at)
        self.assertFalse(reset)
        self.assertEqual(out.decode(), "[got ESC]\r\n")
        self.assertIsNone(code)
        self.s.resize(sid, 90, 20)
        self.until(lambda: "[resized 90x20]" in self.screen(sid))
        self.assertTrue(self.s.output(sid, end + 10_000)[2])      # past its end: all of it again

    def size(self, sid):
        rows, cols = struct.unpack("HHHH", sessions.fcntl.ioctl(self.s.terms[sid].fd, sessions.termios.TIOCGWINSZ, b"\0" * 8))[:2]
        return cols, rows

    def test_a_full_screen_whose_last_whole_drawing_is_no_longer_kept_is_drawn_again(self):
        sid = self.s.create("g", self.work)["session_id"]
        self.s.terminal(sid, 100, 30, fullscreen=True)
        self.until(lambda: "fake terminal" in self.screen(sid))
        self.s.redraw(sid)                                        # all it printed is kept: nothing to draw again
        time.sleep(0.3)
        self.assertNotIn("[resized", self.screen(sid))
        with unittest.mock.patch.object(sessions, "TERM_KEEP", 200):
            self.s.type(sid, "x" * 300)                           # echoed: its start no longer kept
            self.until(lambda: self.s.output(sid, -1)[1] > 300)
            self.s.redraw(sid)
            self.until(lambda: "[resized 100x30]" in self.screen(sid))
        out = self.screen(sid)
        self.assertLess(out.index("[resized 100x29]"), out.index("[resized 100x30]"))   # a row less, then put back
        self.assertEqual(self.size(sid), (100, 30))
        _, at, _, _ = self.s.output(sid, -1)
        self.s.redraw(sid)                                        # its clearing kept now: not again
        time.sleep(0.3)
        self.assertEqual(self.s.output(sid, -1)[1], at)

    def test_the_page_s_own_size_given_while_it_is_drawn_again_stays(self):
        sid = self.s.create("g", self.work)["session_id"]
        self.s.terminal(sid, 100, 30, fullscreen=True)
        self.until(lambda: "fake terminal" in self.screen(sid))
        with unittest.mock.patch.object(sessions, "TERM_KEEP", 100):
            self.s.type(sid, "x" * 200)
            self.until(lambda: self.s.output(sid, -1)[1] > 200)
            self.s.redraw(sid)
            self.s.resize(sid, 90, 20)
            self.until(lambda: not self.s.terms[sid].redrawing)
        self.assertEqual(self.size(sid), (90, 20))

    def test_the_classic_screen_is_not_drawn_again(self):
        sid = self.s.create("g", self.work)["session_id"]
        self.started(sid, 100, 30)
        with unittest.mock.patch.object(sessions, "TERM_KEEP", 100):
            self.s.type(sid, "x" * 200)
            self.until(lambda: self.s.output(sid, -1)[1] > 200)
            self.s.redraw(sid)
        time.sleep(0.3)
        self.assertNotIn("[resized", self.screen(sid))

    def test_a_message_from_another_view_is_pasted_into_it_then_entered(self):
        sid = self.s.create("g", self.work)["session_id"]
        self.started(sid)
        self.s.send(sid, "two\nlines")
        self.until(lambda: "[got \r]" in self.screen(sid))
        typed = "".join(x.get("typed", "") for x in self.logged())
        self.assertEqual(typed, "\x1b[200~two\nlines\x1b[201~\r")

    def test_closing_it_hangs_it_up_and_the_session_shows_stopped(self):
        sid = self.s.create("g", self.work)["session_id"]
        self.started(sid)
        self.s.stop(sid)
        self.until(lambda: self.session(sid)["status"] == "stopped")
        self.assertFalse(self.session(sid)["terminal"])
        self.assertIsNone(self.s.output(sid, 0))
        with self.assertRaises(sessions.SessionError):
            self.s.type(sid, "x")

    def test_once_closed_it_can_be_opened_again_straight_away_in_the_other_screen(self):
        sid = self.s.create("g", self.work)["session_id"]
        self.started(sid)
        first = self.s.terms[sid]
        self.s.stop(sid)                                                # returns once it has gone
        self.assertNotIn(sid, self.s.terms)
        self.assertEqual(self.session(sid)["status"], "stopped")
        self.s.terminal(sid, fullscreen=True)
        self.assertIsNot(self.s.terms[sid], first)
        self.until(lambda: "alt=None" in self.screen(sid))
        self.assertTrue(self.session(sid)["fullscreen"])

    def test_it_ends_the_idle_agent_first_and_is_refused_mid_turn(self):
        sid = self.s.create("g", self.work)["session_id"]
        self.s.send(sid, "hi")
        self.until(lambda: self.session(sid)["status"] == "idle")
        self.started(sid)
        argvs = [x["argv"] for x in self.logged() if "argv" in x]
        self.assertEqual(len(argvs), 2)
        self.assertIn("-p", argvs[0])
        self.assertEqual(argvs[1][-2:], ["--resume", sid])        # it had a turn: resumed
        self.assertNotIn(sid, self.s.agents)
        self.s.stop(sid)
        self.until(lambda: self.session(sid)["status"] == "stopped")
        os.environ["FAKE_AG_DELAY"] = "0.6"
        self.s.send(sid, "slow")
        with self.assertRaises(sessions.SessionError):
            self.s.terminal(sid)

    def test_a_dashboard_restarted_finds_its_terminals_stopped(self):
        sid = self.s.create("g", self.work)["session_id"]
        self.s._set(sid, status="terminal")
        self.assertEqual([x["status"] for x in sessions.Sessions().list()], ["stopped"])


@unittest.skipUnless(sessions.TERMINALS, "a terminal needs a Unix pseudo-terminal")
class ChatTerminalTest(SessionsBase):
    """A message to a session with no terminal open opens one, the message its first prompt (the default,
    `[dashboard] chat = "terminal"`); a turn of its agent's running takes it after the turn."""

    def setUp(self):
        super().setUp()
        self.chat(None)

    def screen(self, sid):
        got = self.s.output(sid, -1)
        return got[0].decode("utf-8", "replace") if got else ""

    def argvs(self):
        return [x["argv"] for x in self.logged() if "argv" in x]

    def test_which_the_config_says(self):
        self.assertEqual(sessions.chat_mode(), "terminal")              # no config.toml
        self.chat("headless")
        self.assertEqual(sessions.chat_mode(), "headless")
        for text in ('[dashboard]\nchat = "tmux"\n', "[cli]\n", "[dashboard\n"):   # none of them, none said, not TOML
            with open(os.path.join(dashboard_home.HOME, "config.toml"), "w") as fh:
                fh.write(text)
            self.assertEqual(sessions.chat_mode(), "terminal", text)
        with unittest.mock.patch.object(sessions, "TERMINALS", False):  # no pseudo-terminals here
            self.assertEqual(sessions.chat_mode(), "headless")

    def test_a_message_opens_its_terminal_with_the_message_as_its_first_prompt(self):
        sid = self.s.create("g", self.work)["session_id"]
        s = self.s.send(sid, "-p is not an option\nhere", 90, 25, fullscreen=True)
        self.assertEqual((s["terminal"], s["status"], s["fullscreen"]), (True, "terminal", True))
        self.until(lambda: "fake terminal" in self.screen(sid))
        self.assertIn("fake terminal 90x25 tty=True term=xterm-256color alt=None", self.screen(sid))
        [argv] = self.argvs()
        self.assertEqual(argv[:4], ["--quiet", "--gatherer", "g", "claude"])
        self.assertEqual(argv[-4:], ["--session-id", sid, "--", "-p is not an option\nhere"])   # after --: the prompt
        self.assertNotIn(sid, self.s.agents)                             # no agent with no screen
        with open(sessions.log_path(sid)) as fh:
            self.assertNotIn("not an option", fh.read())                 # the message is not in its log
        self.s.send(sid, "next")                                         # open now: typed into it
        self.until(lambda: "[got \r]" in self.screen(sid))
        self.assertEqual("".join(x.get("typed", "") for x in self.logged()), "\x1b[200~next\x1b[201~\r")
        self.assertEqual(len(self.argvs()), 1)

    def test_one_closed_is_opened_again_resuming_the_session(self):
        sid = self.s.create("g", self.work)["session_id"]
        self.s.terminal(sid)
        self.until(lambda: "fake terminal" in self.screen(sid))
        self.s._set(sid, turns=1)                                        # it had a turn
        self.s.stop(sid)
        self.s.send(sid, "again")
        self.until(lambda: len(self.argvs()) == 2)
        self.assertEqual(self.argvs()[1][-4:], ["--resume", sid, "--", "again"])
        self.assertTrue(self.session(sid)["terminal"])

    def test_an_idle_agent_is_ended_and_the_terminal_takes_the_session(self):
        self.chat("headless")
        sid = self.s.create("g", self.work)["session_id"]
        self.s.send(sid, "one")
        self.until(lambda: self.session(sid)["status"] == "idle")
        self.chat("terminal")
        self.s.send(sid, "two")
        argvs = self.until(lambda: len(self.argvs()) == 2 and self.argvs())
        self.assertEqual((len(argvs), "-p" in argvs[0], "-p" in argvs[1]), (2, True, False))
        self.assertEqual(argvs[1][-4:], ["--resume", sid, "--", "two"])
        self.assertNotIn(sid, self.s.agents)
        self.assertEqual(self.session(sid)["status"], "terminal")       # the agent's end did not overwrite it
        self.assertEqual([x["message"] for x in self.logged() if "message" in x], ["one"])

    def test_a_turn_running_takes_the_message_after_it(self):
        self.chat("headless")
        os.environ["FAKE_AG_DELAY"] = "0.5"
        sid = self.s.create("g", self.work)["session_id"]
        self.s.send(sid, "one")
        self.chat("terminal")
        self.assertEqual(self.s.send(sid, "two")["queued"], ["two"])    # waits for the turn, in the agent
        self.until(lambda: self.session(sid)["turns"] == 2)
        self.assertEqual([x["message"] for x in self.logged() if "message" in x], ["one", "two"])
        self.assertFalse(self.session(sid)["terminal"])


class KeptTest(SessionsBase):
    """What the dashboard's own end takes is kept -- shown Idle after a restart -- and what is closed is not."""

    def test_the_dashboard_s_end_keeps_its_idle_agent_and_its_terminal(self):
        chat = self.s.create("g", self.work)["session_id"]
        self.s.send(chat, "hi")
        self.until(lambda: self.session(chat)["status"] == "idle")
        term = self.s.create("g", self.work)["session_id"]
        self.s.terminal(term)
        self.until(lambda: self.s.output(term, -1) and b"fake terminal" in self.s.output(term, -1)[0])
        before = time.time()
        self.s.close()
        again = sessions.Sessions()
        for sid in (chat, term):
            row = next(x for x in again.list() if x["session_id"] == sid)
            self.assertEqual(row["status"], "stopped")
            self.assertGreaterEqual(row["kept"], before)

    def test_closed_from_the_list_or_exited_by_itself_it_is_not_kept(self):
        sid = self.s.create("g", self.work)["session_id"]
        self.s.send(sid, "hi")
        self.until(lambda: self.session(sid)["status"] == "idle")
        self.s.stop(sid)
        self.until(lambda: self.session(sid)["status"] == "stopped")
        self.s.close()
        self.assertEqual(self.session(sid)["kept"], 0)

    def test_a_dashboard_gone_without_closing_keeps_what_it_last_had_running(self):
        live, closed = (self.s.create("g", self.work)["session_id"] for _ in range(2))
        self.s._set(live, status="terminal")
        rows = {x["session_id"]: x for x in sessions.Sessions().list()}
        self.assertGreater(rows[live]["kept"], 0)
        self.assertEqual(rows[closed]["kept"], 0)

    def test_a_kept_session_is_closed_from_the_list_or_cleared_by_opening_it(self):
        a, b = (self.s.create("g", self.work)["session_id"] for _ in range(2))
        for sid in (a, b):
            self.s._set(sid, kept=time.time())
        self.s.stop(a)                                       # no process: closed at once
        self.assertEqual(self.session(a)["kept"], 0)
        self.s.send(b, "hi")
        self.assertEqual(self.session(b)["kept"], 0)

    def test_a_table_from_before_kept_gets_it(self):
        self.s.close()
        os.remove(sessions.db_path())
        conn = sqlite3.connect(sessions.db_path())
        conn.execute(sessions.SCHEMA[:sessions.SCHEMA.index(",\n    kept")] + "\n)")     # the columns before `kept`
        conn.execute("INSERT INTO sessions VALUES ('x', 'g', 'claude', '/', 'auto', 'now', 1, 'idle', NULL)")
        conn.commit()
        conn.close()
        self.assertEqual(sessions.stored()[0]["kept"], 0)       # read as it is: none kept
        self.s = sessions.Sessions()
        self.assertGreater(sessions.stored()[0]["kept"], 0)     # it was idle, with a process: kept

    def test_a_kept_session_whose_process_is_gone_shows_idle_until_used_again(self):
        def shown(last, kept):
            g = [{"name": "g", "agents": [{"channel": "c", "created": 1.0, "last": last, "status": data.CLOSED,
                                           "running": False, "harness": "claude", "cwd": "/"}], "last": last}]
            data._with_started(g, [{"session_id": "c", "gatherer": "g", "cwd": "/", "harness": "claude",
                                    "created_at": "2026-10-24T00:00:00+00:00", "status": "stopped", "kept": kept}])
            return g[0]["agents"][0]["status"]
        self.assertEqual(shown(100.0, 200.0), data.IDLE)
        self.assertEqual(shown(300.0, 200.0), data.CLOSED)     # used since, elsewhere, and closed there
        self.assertEqual(shown(100.0, 0), data.CLOSED)


class RestTest(SessionsBase):
    """An actor saved for later whose process is left unused is put away (saved.py's `Rest`): its process
    ended as the dashboard's own end ends it -- kept, shown Idle -- and resumed by its next message."""

    def idle_agent(self):
        sid = self.s.create("g", self.work)["session_id"]
        self.s.send(sid, "hi")
        self.until(lambda: self.session(sid)["status"] == "idle")
        return sid

    def open_terminal(self):
        sid = self.s.create("g", self.work)["session_id"]
        self.s.terminal(sid)
        self.until(lambda: self.s.output(sid, -1) and b"fake terminal" in self.s.output(sid, -1)[0])
        return sid

    def starts(self):
        return [x["argv"] for x in self.logged() if "argv" in x]

    def test_an_idle_agent_or_terminal_put_away_is_kept_and_resumed_by_its_next_message(self):
        chat = self.idle_agent()
        self.assertTrue(self.s.put_away(chat, time.time() + 1))
        self.until(lambda: self.session(chat)["status"] == "stopped")
        row = self.session(chat)
        self.assertGreater(row["kept"], 0)
        self.assertIsNone(row["pid"])
        self.s.send(chat, "again")
        self.until(lambda: self.session(chat)["status"] == "idle" and self.session(chat)["turns"] == 2)
        self.assertEqual(len(self.starts()), 2)
        self.assertIn("--resume", self.starts()[-1])
        self.assertEqual(self.session(chat)["kept"], 0)          # opened again: no longer kept
        term = self.open_terminal()
        self.assertTrue(self.s.put_away(term, time.time() + 1))
        row = self.session(term)                                 # its end recorded before it returns
        self.assertEqual((row["status"], row["terminal"], row["pid"]), ("stopped", False, None))
        self.assertGreater(row["kept"], 0)
        with open(sessions.log_path(term)) as fh:
            self.assertIn("put away", fh.read())

    def test_what_was_used_since_or_is_working_is_not_put_away(self):
        chat = self.idle_agent()
        self.assertFalse(self.s.put_away(chat, time.time() - 60))   # started since
        term = self.open_terminal()
        before = time.time()
        self.s.type(term, "x")
        self.assertFalse(self.s.put_away(term, before))              # typed into since
        self.assertTrue(self.session(term)["terminal"])
        self.assertFalse(self.s.put_away("nothing-here", time.time()))
        os.environ["FAKE_AG_DELAY"] = "5"
        busy = self.s.create("g", self.work)["session_id"]
        self.s.send(busy, "hi")
        self.until(lambda: self.session(busy)["status"] == "running")
        self.assertFalse(self.s.put_away(busy, time.time() + 1))     # mid-turn
        self.s.stop(busy)

    def test_a_message_sent_as_it_is_put_away_goes_to_the_next_process(self):
        chat = self.idle_agent()
        self.assertTrue(self.s.put_away(chat, time.time() + 1))
        self.s.send(chat, "again")
        self.until(lambda: self.session(chat)["turns"] == 2 and self.session(chat)["status"] == "idle")
        self.assertIn({"message": "again"}, self.logged())
        self.assertEqual(self.session(chat)["kept"], 0)
        term = self.open_terminal()
        t = self.s.terms[term]
        with self.s.lock:                                    # put away, its end not yet recorded
            t.kept = True
            self.s._hang_up(t)
        self.s.send(term, "after")
        self.until(lambda: {"message": "after"} in self.logged())   # not pasted into the terminal going away

    def test_which_saved_actors_are_due(self):
        now = 100.0 + saved.REST_SECONDS

        def due(saved_as=("g", "c"), shown=(), at=now, **change):
            agent = {"channel": "c", "status": data.IDLE, "last": 100.0}
            s = {"session_id": "c", "pid": 42, "status": "terminal", "queued": [], "typed": None, "since": 50.0}
            for k, v in change.items():
                (agent if k in agent else s)[k] = v
            agent["session"] = s
            home = {"saved": {saved_as[0]: {saved_as[1]: "2026-10-25T00:00:00+00:00"}} if saved_as else {},
                    "gatherers": [{"name": "g", "agents": [agent]}]}
            return saved.resting(home, set(shown), at)

        self.assertEqual(due(), ["c"])
        self.assertEqual(due(at=now - 1), [])                          # used under REST_SECONDS ago
        self.assertEqual(due(saved_as=None), [])
        self.assertEqual(due(saved_as=("other", "c")), [])
        for status in (data.RUNNING, data.BACKGROUND, data.ASKING, data.ERROR, data.CLOSED):
            self.assertEqual(due(status=status), [], status)
        self.assertEqual(due(**{"status": data.IDLE}), ["c"])
        self.assertEqual(due(pid=None), [])                            # no process of the dashboard's
        self.assertEqual(due(queued=["hi"]), [])
        self.assertEqual(due(shown={"c"}), [])                         # open in a page
        self.assertEqual(due(typed=now - 10), [])
        self.assertEqual(due(since=now - 10), [])
        self.assertEqual(due(last=now - 10), [])
        renamed = {"saved": {"g": {"first": "x"}}, "gatherers": [{"name": "g", "agents": [
            {"channel": "thread", "status": data.IDLE, "last": 100.0,
             "session": {"session_id": "thread", "started_as": "first", "pid": 42, "status": "terminal", "since": 50.0}}]}]}
        self.assertEqual(saved.resting(renamed, set(), now), ["thread"])  # a codex session saved as it started

    def test_the_check_puts_away_saved_actors_left_unused(self):
        kept, other = self.idle_agent(), self.idle_agent()
        saved.choose("g", kept, True)
        shown = set()
        rest = saved.Rest(self.s, lambda: shown)
        try:
            self.assertEqual(rest.check(), [])                       # just used
            later = time.time() + saved.REST_SECONDS + 1
            shown.add(("g", kept))
            self.assertEqual(rest.check(later), [])                  # open in a page
            shown.clear()
            self.assertEqual(rest.check(later), [kept])
            self.until(lambda: self.session(kept)["status"] == "stopped")
            self.assertIsNotNone(self.session(other)["pid"])         # not saved: left alone
            a = next(x for g in data.home(self.s.list())["gatherers"] for x in g["agents"] if x["channel"] == kept)
            self.assertEqual(a["status"], data.IDLE)
            self.assertEqual(rest.check(later), [])                  # no process left to put away
        finally:
            rest.close()


class EndedTest(SessionsBase):
    """Where ag cannot tell whether a process runs (no /proc: macOS), what the dashboard saw end shows Closed."""

    def test_closed_from_the_list_or_its_terminal_hung_up_it_has_ended(self):
        chat = self.s.create("g", self.work)["session_id"]
        self.s.send(chat, "hi")
        self.until(lambda: self.session(chat)["status"] == "idle")
        self.assertEqual(self.session(chat)["ended"], 0)        # running: not ended
        before = time.time()
        self.s.stop(chat)
        self.until(lambda: self.session(chat)["ended"] >= before)
        term = self.s.create("g", self.work)["session_id"]
        self.s.terminal(term)
        self.s.stop(term)                                    # its end recorded before this returns
        self.assertGreaterEqual(self.session(term)["ended"], before)

    def test_a_kept_session_closed_from_the_list_ended_when_it_was_kept(self):
        sid = self.s.create("g", self.work)["session_id"]
        self.s._set(sid, kept=123.0)
        self.s.stop(sid)
        self.assertEqual((self.session(sid)["kept"], self.session(sid)["ended"]), (0, 123.0))

    def test_shown_closed_until_used_again_where_its_process_cannot_be_told(self):
        def shown(last, ended, status=data.IDLE, alive=None, **session):     # `status`: the actor's, as the gatherer says
            g = [{"name": "g", "agents": [{"channel": "c", "created": 1.0, "last": last, "status": status, "alive": alive,
                                           "running": status == data.RUNNING, "building": False, "harness": "claude",
                                           "cwd": "/"}], "last": last}]
            data._with_started(g, [{"session_id": "c", "gatherer": "g", "cwd": "/", "harness": "claude", "pid": None,
                                    "created_at": "2026-10-24T00:00:00+00:00", "status": "stopped", "kept": 0,
                                    "ended": ended, **session}])
            a = g[0]["agents"][0]
            return a["status"], a["running"]
        self.assertEqual(shown(100.0, 200.0), (data.CLOSED, False))
        self.assertEqual(shown(100.0, 200.0, data.RUNNING), (data.CLOSED, False))   # cut off mid-turn
        self.assertEqual(shown(300.0, 200.0), (data.IDLE, False))   # used since, elsewhere: as the gatherer says
        self.assertEqual(shown(100.0, 0), (data.IDLE, False))       # never had a process here
        self.assertEqual(shown(100.0, 200.0, alive=True), (data.IDLE, False))   # the gatherer can tell: it runs
        self.assertEqual(shown(100.0, 200.0, kept=150.0), (data.IDLE, False))   # the dashboard's own end: kept
        self.assertEqual(shown(100.0, 200.0, pid=42), (data.IDLE, False))       # open here again

    def test_a_table_from_before_ended_gets_it_set_for_what_had_run_and_stopped(self):
        self.s.close()
        os.remove(sessions.db_path())
        conn = sqlite3.connect(sessions.db_path())
        conn.execute(sessions.SCHEMA[:sessions.SCHEMA.index(",\n    ended")] + "\n)")    # the columns before `ended`
        conn.executemany("INSERT INTO sessions VALUES (?, 'g', 'claude', '/', 'auto', 'now', ?, ?, NULL, ?, NULL, NULL)",
                         [("ran", 1, "stopped", 0), ("never", 0, "stopped", 0), ("kept", 1, "stopped", 5.0),
                          ("open", 1, "terminal", 0)])
        conn.commit()
        conn.close()
        self.assertEqual({r["session_id"]: r["ended"] for r in sessions.stored()},
                         {"ran": 0, "never": 0, "kept": 0, "open": 0})   # read as it is: none
        before = time.time()
        self.s = sessions.Sessions()
        ended = {r["session_id"]: r["ended"] for r in sessions.stored()}
        self.assertGreaterEqual(ended.pop("ran"), before)
        self.assertEqual(ended, {"never": 0, "kept": 0, "open": 0})


class HomeTest(SessionsBase):
    def test_a_session_with_no_calls_yet_is_listed_in_its_new_gatherer(self):
        made = self.s.create("brand_new", self.work)
        h = data.home(self.s.list())
        g = next(x for x in h["gatherers"] if x["name"] == "brand_new")
        a, = g["agents"]
        self.assertEqual((a["channel"], a["harness"], a["cwd"]), (made["session_id"], "claude", self.work))
        self.assertEqual(a["session"]["status"], "stopped")
        self.assertEqual(data.home()["gatherers"][0]["agents"][0]["channel"], made["session_id"])   # its table, read


class GathererTest(SessionsBase):
    def test_a_new_gatherer_is_made_by_ag_and_listed_with_no_actors(self):
        self.assertEqual(sessions.new_gatherer("fresh"), {"name": "fresh"})
        g = next(x for x in data.home([])["gatherers"] if x["name"] == "fresh")
        self.assertEqual((g["policy"], g["agents"]), ("p", []))

    def test_what_it_refuses(self):
        sessions.new_gatherer("fresh")
        for name in ("fresh", "a b", "", "../x"):
            with self.assertRaises(sessions.SessionError):
                sessions.new_gatherer(name)


class AvailableTest(SessionsBase):
    """The harnesses a gatherer's start buttons offer: those config.toml has, whose command is installed."""

    def setUp(self):
        super().setUp()
        self.chat(None)

    def config(self, text):
        os.makedirs(dashboard_home.HOME, exist_ok=True)
        with open(os.path.join(dashboard_home.HOME, "config.toml"), "w") as fh:
            fh.write(text)

    def test_those_configured_whose_command_is_on_the_path(self):
        bin_dir = os.path.join(self.tmp.name, "bin")
        os.makedirs(bin_dir)
        for name in ("claude", "my-codex"):
            with open(os.path.join(bin_dir, name), "w") as fh:
                fh.write("#!/bin/sh\n")
            os.chmod(os.path.join(bin_dir, name), 0o755)
        env = {"PATH": bin_dir}
        self.assertEqual(sessions.available(env), ["claude"])          # no config.toml: the shipped commands
        self.config('[cli.harnesses.claude]\ncommand = ["claude"]\n[cli.harnesses.codex]\ncommand = ["my-codex"]\n')
        self.assertEqual(sessions.available(env), ["claude", "codex"])
        self.config('[cli.harnesses.codex]\ncommand = "my-codex"\n')      # claude has no entry: ag cannot run it
        self.assertEqual(sessions.available(env), ["codex"])
        self.config('[cli.harnesses.codex]\ncommand = ["my-codex"]\nenv = { PATH = "/nowhere" }\n')
        self.assertEqual(sessions.available(env), [])                   # its own PATH has none
        self.config('[policies]\ndefault = "p"\n')                      # no [cli] yet: ag writes the shipped ones
        self.assertEqual(sessions.available(env), ["claude"])
        self.config('[cli]\ngatherer = "default"\n')                    # a [cli] with none
        self.assertEqual(sessions.available(env), [])
        self.config("[cli\n")
        self.assertEqual(sessions.available(env), [])


class EndpointTest(SessionsBase):
    def setUp(self):
        super().setUp()
        self.httpd = server.serve("127.0.0.1", 0)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()                 # its agents end before the home is removed
        super().tearDown()

    def post(self, path, body, headers=None):
        req = urllib.request.Request(self.url + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as exc:
            return exc.code, json.load(exc)

    def test_a_session_made_and_messaged_from_the_page(self):
        code, made = self.post("/api/sessions", {"gatherer": "g", "cwd": self.work})
        self.assertEqual((code, made["gatherer"], made["permission_mode"]), (200, "g", "auto"))
        code, sent = self.post("/api/send", {"session_id": made["session_id"], "text": "hello"})
        self.assertEqual(code, 200)
        self.until(lambda: json.load(urllib.request.urlopen(self.url + "/api/sessions", timeout=10))[0]["turns"] == 1)
        home = json.load(urllib.request.urlopen(self.url + "/api/home", timeout=10))
        self.assertEqual(home["gatherers"][0]["agents"][0]["session"]["session_id"], made["session_id"])
        self.assertIn("auto", home["permission_modes"])

    @unittest.skipUnless(sessions.TERMINALS, "a terminal needs a Unix pseudo-terminal")
    def test_a_message_opens_its_terminal_at_the_size_and_screen_the_page_sends(self):
        self.chat(None)
        sid = self.post("/api/sessions", {"gatherer": "g", "cwd": self.work})[1]["session_id"]
        code, sent = self.post("/api/send", {"session_id": sid, "text": "hello", "cols": 88, "rows": 22, "fullscreen": True})
        self.assertEqual((code, sent["terminal"], sent["fullscreen"]), (200, True, True))
        self.until(lambda: b"fake terminal 88x22" in (self.httpd.sessions.output(sid, -1) or (b"",))[0])
        self.assertEqual([x["argv"] for x in self.logged() if "argv" in x][0][-2:], ["--", "hello"])

    @unittest.skipUnless(sessions.TERMINALS, "a terminal needs a Unix pseudo-terminal")
    def test_a_terminal_opened_typed_into_and_streamed_from_the_page(self):
        sid = self.post("/api/sessions", {"gatherer": "g", "cwd": self.work})[1]["session_id"]
        code, opened = self.post("/api/terminal", {"session_id": sid, "cols": 80, "rows": 24})
        self.assertEqual((code, opened["terminal"], opened["status"]), (200, True, "terminal"))
        stream = urllib.request.urlopen(self.url + f"/api/terminal?session_id={sid}", timeout=10)
        seen = b""

        def until_seen(what):
            nonlocal seen
            while what not in seen:
                line = stream.readline()
                if line.startswith(b"data: "):
                    seen += base64.b64decode(json.loads(line[6:])["data"])
        until_seen(b"fake terminal 80x24")                 # it is up: what is typed now reaches it
        self.assertEqual(self.post("/api/terminal/input", {"session_id": sid, "data": "hi"}), (200, {}))
        until_seen(b"[got hi]")
        self.assertEqual(self.post("/api/terminal/resize", {"session_id": sid, "cols": 100, "rows": 30}), (200, {}))
        until_seen(b"[resized 100x30]")
        self.post("/api/stop", {"session_id": sid})
        events = []
        while "exit" not in events:
            line = stream.readline().decode()
            if line.startswith("event: "):
                events.append(line[7:].strip())
        stream.close()
        self.assertEqual(self.post("/api/terminal/input", {"session_id": sid, "data": "x"})[0], 400)
        none = urllib.request.urlopen(self.url + f"/api/terminal?session_id={sid}", timeout=10).read().decode()
        self.assertIn("event: none", none)

    def test_a_gatherer_made_from_the_page(self):
        self.assertEqual(self.post("/api/gatherers", {"name": "fresh"}), (200, {"name": "fresh"}))
        self.assertEqual(self.post("/api/gatherers", {"name": "fresh"})[0], 400)
        home = json.load(urllib.request.urlopen(self.url + "/api/home", timeout=10))
        self.assertIn("fresh", [g["name"] for g in home["gatherers"]])

    def test_the_reader_s_own_chat_views_are_listed_and_served(self):
        get = lambda path: urllib.request.urlopen(self.url + path, timeout=10)  # noqa: E731
        self.assertEqual(json.load(get("/api/views")), [])                   # none yet
        views = os.path.join(dashboard_home.HOME, "dashboard", "views")
        os.makedirs(views)
        for name, text in (("mine.js", "agDashboard.chatView({});"), ("notes.txt", "x"), (".hidden.js", "x")):
            with open(os.path.join(views, name), "w") as fh:
                fh.write(text)
        self.assertEqual(json.load(get("/api/views")), ["mine.js"])          # .js files, by name
        r = get("/views/mine.js")
        self.assertEqual((r.headers["Content-Type"].split(";")[0], r.read()), ("text/javascript", b"agDashboard.chatView({});"))
        with open(os.path.join(self.tmp.name, "secret.js"), "w") as fh:
            fh.write("x")
        for path in ("/views/notes.txt", "/views/.hidden.js", "/views/../secret.js", "/views/%2e%2e%2fsecret.js", "/views/none.js"):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                get(path)
            self.assertEqual(caught.exception.code, 404, path)

    def test_a_gatherer_hidden_stays_hidden_for_every_dashboard_on_the_home(self):
        self.assertEqual(json.load(urllib.request.urlopen(self.url + "/api/home", timeout=10))["hiding"], {})
        self.assertEqual(self.post("/api/hiding", {"gatherer": "old", "choice": "hidden"}), (200, {"old": "hidden"}))
        self.assertEqual(self.post("/api/hiding", {"gatherer": "quiet", "choice": "shown"}),
                         (200, {"old": "hidden", "quiet": "shown"}))
        other = server.serve("127.0.0.1", 0)         # another dashboard: a new port, its own page origin
        threading.Thread(target=other.serve_forever, daemon=True).start()
        try:
            home = json.load(urllib.request.urlopen(f"http://127.0.0.1:{other.server_port}/api/home", timeout=10))
            self.assertEqual(home["hiding"], {"old": "hidden", "quiet": "shown"})
        finally:
            other.shutdown()
            other.server_close()
        self.assertEqual(self.post("/api/hiding", {"gatherer": "old", "choice": ""}), (200, {"quiet": "shown"}))
        self.assertEqual(data.home([])["hiding"], {"quiet": "shown"})      # snapshots carry it too
        self.assertEqual(self.post("/api/hiding", {"gatherer": "old", "choice": "gone"})[0], 400)
        self.assertEqual(self.post("/api/hiding", {"gatherer": "", "choice": "hidden"})[0], 400)
        self.assertEqual(self.post("/api/hiding", {"gatherer": "x", "choice": "hidden"}, {"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(hiding.stored(), {"quiet": "shown"})

    def test_an_actor_saved_for_later_stays_saved_for_every_dashboard_on_the_home(self):
        self.assertEqual(json.load(urllib.request.urlopen(self.url + "/api/home", timeout=10))["saved"], {})
        code, kept = self.post("/api/saved", {"gatherer": "g", "channel": "c1", "saved": True})
        self.assertEqual((code, list(kept)), (200, ["g"]))
        first = kept["g"]["c1"]
        code, kept = self.post("/api/saved", {"gatherer": "g", "channel": "c2", "saved": True})
        self.assertEqual(sorted(kept["g"]), ["c1", "c2"])
        code, kept = self.post("/api/saved", {"gatherer": "g", "channel": "c1", "saved": True})
        self.assertEqual(kept["g"]["c1"], first)                 # saved again: kept from when it was first
        other = server.serve("127.0.0.1", 0)         # another dashboard: a new port, its own page origin
        threading.Thread(target=other.serve_forever, daemon=True).start()
        try:
            home = json.load(urllib.request.urlopen(f"http://127.0.0.1:{other.server_port}/api/home", timeout=10))
            self.assertEqual(sorted(home["saved"]["g"]), ["c1", "c2"])
        finally:
            other.shutdown()
            other.server_close()
        code, kept = self.post("/api/saved", {"gatherer": "g", "channel": "c1", "saved": False})
        self.assertEqual((code, sorted(kept["g"])), (200, ["c2"]))
        self.assertEqual(sorted(data.home([])["saved"]["g"]), ["c2"])      # snapshots carry it too
        self.assertEqual(self.post("/api/saved", {"gatherer": "g", "channel": "", "saved": True})[0], 400)
        self.assertEqual(self.post("/api/saved", {"gatherer": "", "channel": "c", "saved": True})[0], 400)
        self.assertEqual(self.post("/api/saved", {"gatherer": "g", "channel": "c3", "saved": True}, {"Origin": "https://evil.example"})[0], 403)
        self.post("/api/saved", {"gatherer": "g", "channel": "c2", "saved": False})

    def test_when_the_reader_last_looked_at_each_actor_is_the_same_for_every_dashboard_on_the_home(self):
        self.assertIsNone(json.load(urllib.request.urlopen(self.url + "/api/home", timeout=10))["seen"])   # none kept yet
        code, kept = self.post("/api/seen", {"seen": [["g", "c1", 100.5], ["g", "c2", 200]]})
        self.assertEqual((code, kept), (200, {"g": {"c1": 100.5, "c2": 200.0}}))
        code, kept = self.post("/api/seen", {"seen": [["g", "c1", 50], ["g", "c2", 250], ["h", "c1", 10]]})
        self.assertEqual(kept, {"g": {"c1": 100.5, "c2": 250.0}, "h": {"c1": 10.0}})   # a look only moves forward
        other = server.serve("127.0.0.1", 0)         # another dashboard: a new port, its own page origin
        threading.Thread(target=other.serve_forever, daemon=True).start()
        try:
            home = json.load(urllib.request.urlopen(f"http://127.0.0.1:{other.server_port}/api/home", timeout=10))
            self.assertEqual(home["seen"], {"g": {"c1": 100.5, "c2": 250.0}, "h": {"c1": 10.0}})
        finally:
            other.shutdown()
            other.server_close()
        self.assertEqual(data.home([])["seen"]["g"]["c2"], 250.0)          # snapshots carry it too
        for bad in ([], [["g", "c1"]], [["g", "", 1]], [["", "c", 1]], [["g", "c", "1"]], [["g", "c", True]], "g"):
            self.assertEqual(self.post("/api/seen", {"seen": bad})[0], 400, bad)
        self.assertEqual(self.post("/api/seen", {"seen": [["g", "c3", 1]]}, {"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(seen.stored(), {"g": {"c1": 100.5, "c2": 250.0}, "h": {"c1": 10.0}})
        self.assertEqual(saved.stored(), {})

    def test_what_it_refuses(self):
        self.assertEqual(self.post("/api/gatherers", {"name": "x"}, {"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.post("/api/stop", {"session_id": "none"})[0], 400)
        self.assertEqual(self.post("/api/stop", {"session_id": "x"}, {"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.post("/api/sessions", {"gatherer": "a b", "cwd": self.work})[0], 400)
        self.assertEqual(self.post("/api/send", {"session_id": "none", "text": "hi"})[0], 400)
        self.assertEqual(self.post("/api/sessions", {"gatherer": "g"}, {"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.post("/api/sessions", {"gatherer": "g"}, {"Content-Type": "text/plain"})[0], 403)
        self.assertEqual(self.post("/api/sessions", {"gatherer": "g"}, {"Host": "rebound.example:80"})[0], 403)
        self.assertEqual(sessions.stored(), [])


if __name__ == "__main__":
    unittest.main()
