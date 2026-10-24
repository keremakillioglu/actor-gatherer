"""Sessions started from the dashboard (ag_dashboard/sessions.py): its table, the agent it runs
for each through ag -- here a fake ag that answers each message with a result line -- and the
server's endpoints for them. No real agent runs."""
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
        self.assertEqual(self.post("/api/sessions", {"gatherer": "a b", "cwd": self.work})[0], 400)
        self.assertEqual(self.post("/api/send", {"session_id": "none", "text": "hi"})[0], 400)
        self.assertEqual(self.post("/api/sessions", {"gatherer": "g"}, {"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.post("/api/sessions", {"gatherer": "g"}, {"Content-Type": "text/plain"})[0], 403)
        self.assertEqual(self.post("/api/sessions", {"gatherer": "g"}, {"Host": "rebound.example:80"})[0], 403)
        self.assertEqual(sessions.stored(), [])


if __name__ == "__main__":
    unittest.main()
