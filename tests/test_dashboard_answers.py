"""Answering from the page what Claude Code asks in its terminal: the keys a choice is typed as (answers.py),
the plan a call to ExitPlanMode asks about (data.py's `asking`, from Claude Code's plan file), whether
Claude Code recorded what was picked, and the dashboard typing the keys into its terminal (sessions.py's
`answer`, POST /api/answer)."""
import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import unittest.mock
import urllib.error
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ag_dashboard import answers, data, server, sessions  # noqa: E402
from ag_dashboard import home as dashboard_home  # noqa: E402
from test_dashboard_sessions import SessionsBase  # noqa: E402


def question(text, labels, multi=False, header=None):
    return {"header": header, "question": text, "multiSelect": multi,
            "options": [{"label": x, "description": None} for x in labels]}


COLOR = question("Which color?", ["Red", "Blue", "Green"])
SIZE = question("Which size?", ["Small", "Large"])
PETS = question("Which pets?", ["Cat", "Dog", "Fish"], multi=True)


def ask(*questions):
    return {"kind": "question", "call": "toolu_1", "at": time.time() - 5, "questions": list(questions)}


PLAN = {"kind": "plan", "call": "toolu_2", "at": time.time() - 5, "plan": "1. Do it"}


class KeysTest(unittest.TestCase):
    """The keys, as typed live into Claude Code 2.1.310's dialog -- and what it then told its model."""

    def test_a_question_answered_by_its_option_s_number(self):
        self.assertEqual(answers.keys(ask(COLOR), {"answers": [{"options": [1]}]}), ["2"])
        self.assertEqual(answers.expected(ask(COLOR), {"answers": [{"options": [1]}]}), ['"Which color?"="Blue"'])

    def test_one_s_own_words_follow_the_options(self):
        choice = {"answers": [{"text": " Teal please "}]}
        self.assertEqual(answers.keys(ask(COLOR), choice), ["4", "Teal please", "\r"])     # "4. Type something."
        self.assertEqual(answers.expected(ask(COLOR), choice), ['"Which color?"="Teal please"'])

    def test_a_multiselect_question_is_ticked_then_left_then_submitted(self):
        choice = {"answers": [{"options": [2, 1]}]}
        self.assertEqual(answers.keys(ask(PETS), choice), ["2", "3", "\t", "1"])          # on to the review, submitted
        self.assertEqual(answers.expected(ask(PETS), choice), ['"Which pets?"="Dog, Fish"'])

    def test_several_questions_end_on_the_review_s_submit(self):
        choice = {"answers": [{"text": "Teal please"}, {"options": [1]}, {"options": [0, 2]}]}
        self.assertEqual(answers.keys(ask(COLOR, SIZE, PETS), choice), ["4", "Teal please", "\r", "2", "1", "3", "\t", "1"])
        self.assertEqual(answers.expected(ask(COLOR, SIZE, PETS), choice),
                         ['"Which color?"="Teal please"', '"Which size?"="Large"', '"Which pets?"="Cat, Fish"'])
        self.assertEqual(answers.summary(ask(COLOR, SIZE, PETS), choice),
                         "Which color? → Teal please · Which size? → Large · Which pets? → Cat, Fish")
        self.assertEqual(answers.keys(ask(PETS, SIZE), {"answers": [{"options": [0]}, {"options": [0]}]}), ["1", "\t", "1", "1"])

    def test_a_plan_approved_or_sent_back(self):
        self.assertEqual(answers.keys(PLAN, {"plan": "auto"}), ["1"])
        self.assertEqual(answers.keys(PLAN, {"plan": "manual"}), ["2"])
        self.assertEqual(answers.keys(PLAN, {"plan": "change", "text": "Say bye"}), ["3", "Say bye", "\r"])
        self.assertEqual(answers.expected(PLAN, {"plan": "manual"}), [answers.PLAN_APPROVED])
        self.assertEqual(answers.expected(PLAN, {"plan": "change", "text": "Say bye"}), ["Say bye"])

    def test_a_choice_that_does_not_answer_is_refused(self):
        for a, choice in ((ask(COLOR, SIZE), {"answers": [{"options": [0]}]}),          # one answer for two
                          (ask(COLOR), {"answers": [{"options": [3]}]}),                 # no such option
                          (ask(COLOR), {"answers": [{"options": [0, 1]}]}),              # two for a single choice
                          (ask(COLOR), {"answers": [{"options": []}]}),                  # nothing
                          (ask(COLOR), {"answers": [{"text": "two\nlines"}]}),
                          (ask(PETS), {"answers": [{"text": "a parrot"}]}),             # own words: single choice only
                          (ask(COLOR), {"answers": [{"options": [0], "text": "and"}]}),
                          (PLAN, {"plan": "yes"}), (PLAN, {"plan": "change", "text": " "})):
            with self.assertRaises(answers.AnswerError, msg=choice):
                answers.keys(a, choice)

    def test_recorded_when_the_result_holds_every_answer(self):
        expect = ['"Which color?"="Blue"', '"Which pets?"="Cat, Fish"']
        self.assertIsNone(answers.recorded(None, expect))
        self.assertTrue(answers.recorded('Your questions have been answered: "Which color?"="Blue", "Which pets?"="Cat, Fish". '
                                         "You can now continue with these answers in mind.", expect))
        self.assertFalse(answers.recorded('Your questions have been answered: "Which color?"="Blue", "Which pets?"="Cat". ', expect))


def event(kind, payload, text=None):
    return kind, payload, text


def call(cid, name, inp):
    return event("tool_call", {"role": "assistant", "content": [{"type": "tool_use", "id": cid, "name": name, "input": inp}]},
                 f"{name}(...)")


class GathererBase(unittest.TestCase):
    """A home of the test's own, gatherer `g` holding Claude Code's events as they reach ag, and its pending answer."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.saved, dashboard_home.HOME = dashboard_home.HOME, self.tmp.name
        self.addCleanup(setattr, dashboard_home, "HOME", self.saved)
        os.makedirs(os.path.join(self.tmp.name, "gatherers", "g"))
        self.path = os.path.join(self.tmp.name, "gatherers", "g", "context.db")
        conn = sqlite3.connect(self.path)
        conn.executescript("""CREATE TABLE event_types (event_type_id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL);
            CREATE TABLE events (row_id INTEGER PRIMARY KEY, inserted_at TEXT NOT NULL, event_id TEXT, event_type_id INTEGER NOT NULL,
              payload_json TEXT NOT NULL, tokens INTEGER NOT NULL, text TEXT, counted INTEGER, p_channel);
            CREATE TABLE _pending (pending_id INTEGER PRIMARY KEY, received_at TEXT NOT NULL, answer TEXT, stop TEXT,
              type TEXT NOT NULL, payload_json TEXT NOT NULL, text TEXT, p_channel);""")
        conn.commit()
        conn.close()
        self.add([event("user_message", {"role": "user", "content": [{"type": "text", "text": "plan it"}]}, "plan it")])

    def add(self, events, channel="s1"):
        stamp = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(self.path)
        for typ, payload, text in events:
            conn.execute("INSERT OR IGNORE INTO event_types (name, created_at) VALUES (?, ?)", (typ, stamp))
            tid = conn.execute("SELECT event_type_id FROM event_types WHERE name = ?", (typ,)).fetchone()[0]
            conn.execute("INSERT INTO events (inserted_at, event_type_id, payload_json, tokens, text, p_channel) "
                         "VALUES (?, ?, ?, 1, ?, ?)", (stamp, tid, json.dumps(payload), text, channel))
        conn.commit()
        conn.close()

    def pend(self, events, channel="s1", answer="msg_1"):
        conn = sqlite3.connect(self.path)
        conn.execute("DELETE FROM _pending WHERE p_channel = ?", (channel,))
        for typ, payload, text in events:
            conn.execute("INSERT INTO _pending (received_at, answer, stop, type, payload_json, text, p_channel) "
                         "VALUES (?, ?, 'tool_use', ?, ?, ?, ?)",
                         (datetime.now(timezone.utc).isoformat(), answer, typ, json.dumps(payload), text, channel))
        conn.commit()
        conn.close()

    def plan_file(self, name, text):
        d = os.path.join(self.tmp.name, "user", ".claude", "plans")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, name)
        with open(path, "w") as fh:
            fh.write(text)
        return path


class PlanTest(GathererBase):
    """ExitPlanMode's call carries no plan (Claude Code 2.1.310): it is the plan file Claude Code wrote."""

    def test_the_plan_written_in_the_same_answer(self):
        path = self.plan_file("plan-a.md", "1. Move it\n2. Test it\n")
        self.pend([call("t1", "Write", {"file_path": path, "content": "1. Move it\n"}), call("t2", "ExitPlanMode", {})])
        got = data.asking_of("g", "s1")
        self.assertEqual((got["kind"], got["call"], got["plan"]), ("plan", "t2", "1. Move it\n2. Test it\n"))   # the file, as it is now

    def test_the_plan_written_before_and_its_write_once_the_file_is_gone(self):
        path = os.path.join(self.tmp.name, "user", ".claude", "plans", "plan-gone.md")
        self.add([call("t1", "Write", {"file_path": path, "content": "1. As written\n"}),
                  call("t9", "Write", {"file_path": os.path.join(self.tmp.name, "notes.md"), "content": "not a plan"})])
        self.pend([call("t2", "ExitPlanMode", {})])
        self.assertEqual(data.asking_of("g", "s1")["plan"], "1. As written\n")
        self.pend([call("t3", "ExitPlanMode", {"plan": "1. Carried"})])                   # an older Claude Code: in the call
        self.assertEqual(data.asking_of("g", "s1")["plan"], "1. Carried")

    def test_none_written_none_shown(self):
        self.pend([call("t2", "ExitPlanMode", {})])
        self.assertIsNone(data.asking_of("g", "s1")["plan"])
        self.assertIsNone(data.asking_of("g", "nobody"))


SESSION = "0e1d2c3b-0000-4000-8000-000000000001"


class SettledTest(GathererBase):
    """Claude Code's own record of the session (<config>/projects/<dir>/<session>.jsonl), written as it happens: a
    question answered or dismissed there is not asked any more -- dismissed (Esc), no call tells ag, and the turn is over."""

    def setUp(self):
        super().setUp()
        self.config = os.path.join(self.tmp.name, "claude-config")
        env = unittest.mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": self.config})
        env.start()
        self.addCleanup(env.stop)
        self.cwd = "/work/my repo"
        self.record = os.path.join(self.config, "projects", "-work-my-repo", f"{SESSION}.jsonl")
        os.makedirs(os.path.dirname(self.record))
        self.write({"type": "user", "message": {"role": "user", "content": "ask me"}})
        self.write({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_q", "name": "AskUserQuestion", "input": {"questions": [SIZE]}}]}})
        self.add([event("user_message", {"role": "user", "content": [{"type": "text", "text": "ask me"}]}, "ask me")], channel=SESSION)
        self.pend([call("toolu_q", "AskUserQuestion", {"questions": [SIZE]})], channel=SESSION)

    def write(self, line):
        with open(self.record, "a") as fh:
            fh.write(json.dumps(line) + "\n")

    def result(self, text, error=False):
        self.write({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_q", "content": text, "is_error": error}]}})

    def actor(self):
        return next(a for g in data.home([])["gatherers"] for a in g["agents"] if a["channel"] == SESSION)

    def test_dismissed_there_the_turn_is_over(self):
        self.assertEqual(self.actor()["status"], data.ASKING)
        self.assertIsNone(data.settled(SESSION, self.cwd, "toolu_q"))
        self.result("The user doesn't want to proceed with this tool use. The tool use was rejected", error=True)
        self.write({"type": "user", "message": {"role": "user", "content": [
            {"type": "text", "text": "[Request interrupted by user for tool use]"}]}})
        self.assertEqual(data.settled(SESSION, self.cwd, "toolu_q"), "dismissed")
        self.assertEqual(data.settled(SESSION, None, "toolu_q"), "dismissed")          # found by the session's id alone
        a = self.actor()
        self.assertEqual((a["status"], a["turn_over"], a["asking"]), (data.IDLE, True, None))
        self.assertIsNone(data.asking_of("g", SESSION, self.cwd))

    def test_answered_there_it_goes_on(self):
        self.result('Your questions have been answered: "Which size?"="Large".')
        self.write({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "Large it is."}]}})
        self.write({"type": "user", "message": {"role": "user", "content": [
            {"type": "text", "text": "[Request interrupted by user]"}]}})                  # later, another turn's
        self.assertEqual(data.settled(SESSION, self.cwd, "toolu_q"), "answered")
        a = self.actor()
        self.assertEqual((a["status"], a["asking"]), (data.RUNNING, None))              # until the next call says more

    def test_no_record_no_change(self):
        os.remove(self.record)
        self.assertIsNone(data.settled(SESSION, self.cwd, "toolu_q"))
        self.assertEqual(self.actor()["status"], data.ASKING)

    def test_its_record_is_watched_while_it_asks_and_a_change_rings_its_gatherer(self):
        from ag_dashboard import live
        hub = live.Hub()
        rung = []
        hub.ring = lambda gatherer, channel=None, what="": rung.append(gatherer)
        fallback = live.Fallback(hub, seconds=3600)
        self.addCleanup(fallback.close)
        self.addCleanup(live.watch_records, {})
        self.assertEqual(self.actor()["status"], data.ASKING)                    # read: watched from now on
        self.assertEqual(list(live._RECORDS), [self.record])
        fallback.check_records()
        self.assertEqual(rung, [])                                                # unchanged since it was read
        time.sleep(0.01)
        self.result("The user doesn't want to proceed with this tool use.", error=True)   # Esc, in its terminal
        fallback.check_records()
        self.assertEqual(rung, ["g"])
        fallback.check_records()
        self.assertEqual(rung, ["g"])                                             # rung once for a change
        self.write({"type": "user", "message": {"role": "user", "content": [
            {"type": "text", "text": "[Request interrupted by user for tool use]"}]}})
        self.assertEqual(self.actor()["status"], data.IDLE)                       # read again: not asking, not watched
        self.assertEqual(live._RECORDS, {})


class RecordedTest(GathererBase):
    """An answer typed from the page, and what Claude Code's result for the call then says."""

    def actor(self, answer):
        session = {"session_id": "s1", "gatherer": "g", "cwd": "/", "harness": "claude", "permission_mode": "auto",
                   "created_at": "2026-01-01T00:00:00+00:00", "turns": 0, "status": "terminal", "last_error": None, "kept": 0,
                   "queued": [], "terminal": True, "fullscreen": False, "pid": None, "since": None, "answer": answer, "typed": None}
        return next(a for g in data.home([session])["gatherers"] for a in g["agents"] if a["channel"] == "s1")

    def test_recorded_once_the_result_comes_and_only_if_it_holds_the_answer(self):
        a = ask(COLOR, PETS)
        choice = {"answers": [{"options": [1]}, {"options": [0, 2]}]}
        sent = {"call": "t1", "summary": answers.summary(a, choice), "expect": answers.expected(a, choice), "at": time.time()}
        self.add([call("t1", "AskUserQuestion", {"questions": a["questions"]})])
        self.assertIsNone(self.actor(sent)["answer"]["recorded"])                        # no result yet
        result = 'Your questions have been answered: "Which color?"="Blue", "Which pets?"="Cat". You can now continue.'
        self.add([event("tool_output", {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": result}]}, result)])
        got = self.actor(sent)["answer"]
        self.assertEqual((got["recorded"], got["result"], got["summary"]), (False, result, "Which color? → Blue · Which pets? → Cat, Fish"))
        sent2 = dict(sent, call="t2", expect=['"Which color?"="Blue"'])
        self.add([call("t2", "AskUserQuestion", {}),
                  event("tool_output", {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t2", "content": result}]}, result)])
        self.assertTrue(self.actor(sent2)["answer"]["recorded"])


@unittest.skipUnless(sessions.TERMINALS, "a terminal needs a Unix pseudo-terminal")
class TypedTest(SessionsBase):
    """The keys typed into the dashboard's terminal for the session (the fake ag echoes each read)."""

    def typed(self):
        return [x["typed"] for x in self.logged() if "typed" in x]

    def started(self):
        sid = self.s.create("g", self.work)["session_id"]
        self.s.terminal(sid, 100, 30)
        self.until(lambda: "fake terminal" in self.s.output(sid, -1)[0].decode("utf-8", "replace"))
        return sid

    def test_each_key_on_its_own_and_the_answer_kept(self):
        sid = self.started()
        a = ask(COLOR, PETS)
        sent = self.s.answer(sid, a, {"answers": [{"options": [1]}, {"options": [0, 2]}]})
        self.assertEqual((sent["call"], sent["expect"]), ("toolu_1", ['"Which color?"="Blue"', '"Which pets?"="Cat, Fish"']))
        self.until(lambda: len(self.typed()) == 5)
        self.assertEqual(self.typed(), ["2", "1", "3", "\t", "1"])                       # five reads: one key each
        self.assertEqual(self.session(sid)["answer"], sent)

    def test_refused_once_something_was_typed_since_it_asked(self):
        sid = self.started()
        a = ask(COLOR)
        self.s.type(sid, "\x1b[I\x1b[O")                                                  # focus in and out: not typing
        self.s.type(sid, "\x1b[?1;2c")                                                    # the terminal's own reply
        self.assertIsNone(self.session(sid)["typed"] or None)
        self.s.type(sid, "\x1b[B")                                                        # Down, in the dialog
        self.assertGreater(self.session(sid)["typed"], a["at"])
        with self.assertRaisesRegex(sessions.SessionError, "typed into its terminal since it asked"):
            self.s.answer(sid, a, {"answers": [{"options": [0]}]})
        self.s.answer(sid, dict(a, at=time.time() + 1), {"answers": [{"options": [0]}]})   # asked after it: answered

    def test_no_terminal_here_no_answer(self):
        sid = self.s.create("g", self.work)["session_id"]
        with self.assertRaisesRegex(sessions.SessionError, "does not run this session's terminal"):
            self.s.answer(sid, ask(COLOR), {"answers": [{"options": [0]}]})


@unittest.skipUnless(sessions.TERMINALS, "a terminal needs a Unix pseudo-terminal")
class EndpointTest(SessionsBase):
    def setUp(self):
        super().setUp()
        self.httpd = server.serve("127.0.0.1", 0)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        super().tearDown()

    def typed(self):
        return [x["typed"] for x in self.logged() if "typed" in x]

    def post(self, body, path="/api/answer"):
        req = urllib.request.Request(self.url + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as exc:
            return exc.code, json.load(exc)

    def test_the_page_answers_what_the_gatherer_says_it_asks(self):
        sid = self.post({"gatherer": "g", "cwd": self.work}, "/api/sessions")[1]["session_id"]   # the server's own sessions
        self.assertEqual(self.post({"session_id": sid, "call": "toolu_q", "choice": {}})[0], 400)    # asking nothing
        self.post({"session_id": sid, "cols": 100, "rows": 30}, "/api/terminal")
        self.until(lambda: os.path.exists(self.log) and self.logged())                      # its fake ag is up
        time.sleep(0.3)                                                                      # and reading its terminal
        os.makedirs(os.path.join(dashboard_home.HOME, "gatherers", "g"), exist_ok=True)
        db = os.path.join(dashboard_home.HOME, "gatherers", "g", "context.db")
        conn = sqlite3.connect(db)
        conn.executescript("""CREATE TABLE event_types (event_type_id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL);
            CREATE TABLE events (row_id INTEGER PRIMARY KEY, inserted_at TEXT NOT NULL, event_id TEXT, event_type_id INTEGER NOT NULL,
              payload_json TEXT NOT NULL, tokens INTEGER NOT NULL, text TEXT, counted INTEGER, p_channel);
            CREATE TABLE _pending (pending_id INTEGER PRIMARY KEY, received_at TEXT NOT NULL, answer TEXT, stop TEXT,
              type TEXT NOT NULL, payload_json TEXT NOT NULL, text TEXT, p_channel);""")
        conn.execute("INSERT INTO _pending (received_at, answer, stop, type, payload_json, p_channel) VALUES (?, 'm', 'tool_use', 'tool_call', ?, ?)",
                     (datetime.now(timezone.utc).isoformat(),
                      json.dumps(call("toolu_q", "AskUserQuestion", {"questions": [SIZE]})[1]), sid))
        conn.commit()
        conn.close()
        self.assertEqual(self.post({"session_id": sid, "call": "toolu_old", "choice": {"answers": [{"options": [0]}]}})[0], 400)
        code, got = self.post({"session_id": sid, "call": "toolu_q", "choice": {"answers": [{"options": [5]}]}})
        self.assertEqual((code, "no such option" in got["error"]), (400, True))
        code, got = self.post({"session_id": sid, "call": "toolu_q", "choice": {"answers": [{"options": [1]}]}})
        self.assertEqual((code, got["summary"]), (200, "Which size? → Large"))
        self.until(lambda: self.typed() == ["2"])


if __name__ == "__main__":
    unittest.main()
