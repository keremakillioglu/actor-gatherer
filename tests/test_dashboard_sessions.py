"""Sessions started from the dashboard (ag_dashboard/sessions.py): its table, the agent it runs
for each through ag -- here a fake ag that answers each message with a result line -- and the
server's endpoints for them. No real agent runs."""
import base64
import json
import os
import sqlite3
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

from ag_dashboard import data, hiding, server, sessions  # noqa: E402
from ag_dashboard import home as dashboard_home  # noqa: E402

# A fake `ag`: writes its arguments, then each message it is sent, to $FAKE_AG_LOG; answers each
# after $FAKE_AG_DELAY seconds with a result line; exits when its stdin closes. `new G` makes G's
# config in $AG_HOME, as ag's does.
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
        signal.signal(signal.SIGWINCH, lambda *_: os.write(1, ("[resized %s]\\r\\n" % size()).encode()))
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
        self.s = sessions.Sessions()

    def tearDown(self):
        self.s.close()
        self.env.stop()
        dashboard_home.HOME = self.saved
        self.tmp.cleanup()

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
        self.assertEqual(run["argv"][:3], ["--gatherer", "g", "claude"])
        self.assertEqual(run["argv"][-2:], ["--session-id", sid])
        self.assertEqual(run["cwd"], self.work)
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
        conn.execute(sessions.SCHEMA.replace(",\n    kept            REAL NOT NULL DEFAULT 0", ""))
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
