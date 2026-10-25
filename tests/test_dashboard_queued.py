"""What the user writes to Claude Code while it works (ag_dashboard/queued.py): read from the queue Claude Code
writes to its own record of the session the moment it changes -- long before ag stores the message with the
turn's next call -- and in the Chat view, part of the turn it was written in."""
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
import unittest.mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ag_dashboard import files, live, queued  # noqa: E402
from ag_dashboard import home as dashboard_home  # noqa: E402
from test_dashboard_files import asked, call, result, said  # noqa: E402

SESSION = "0e1d2c3b-0000-4000-8000-000000000002"


def stamp(seconds):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(seconds)) + f".{int(seconds * 1000) % 1000:03d}Z"


def wrapped(text):
    """A message sent mid-turn, as Claude Code wraps it for the model."""
    return ("The user sent a new message while you were working:\n" + text + "\n\nThis is how Claude Code surfaces "
            "messages the user sends mid-turn — within the running turn, often alongside the next tool result, rather "
            "than as a separate conversation turn. Address the message above as you continue this turn.")


class RecordBase(unittest.TestCase):
    """A Claude Code config folder of the test's own, with the session's record in it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = os.path.join(self.tmp.name, "claude-config")
        env = unittest.mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": self.config})
        env.start()
        self.addCleanup(env.stop)
        self.record = os.path.join(self.config, "projects", "-work-repo", f"{SESSION}.jsonl")
        os.makedirs(os.path.dirname(self.record))
        self.now = time.time()
        self.write({"type": "user", "message": {"role": "user", "content": "start"}})

    def write(self, line, end="\n"):
        with open(self.record, "a") as fh:
            fh.write(json.dumps(line) + end)

    def op(self, operation, text=None, ago=0.0, **more):
        line = {"type": "queue-operation", "operation": operation, "timestamp": stamp(self.now - ago), "sessionId": SESSION}
        if text is not None:
            line["content"] = text
        self.write({**line, **more})


class TypedTest(RecordBase):
    def typed(self):
        return [(q["text"], q["sent"] is not None) for q in queued.typed(SESSION, now=self.now)]

    def test_written_then_sent_mid_turn(self):
        self.assertEqual(self.typed(), [])
        self.op("enqueue", "also do b", ago=5)
        self.assertEqual(self.typed(), [("also do b", False)])            # waiting for the turn's next step
        self.op("remove", "also do b", ago=2, reason="absorbed_mid_turn")
        self.assertEqual(self.typed(), [("also do b", True)])             # sent: ag stores it with that call
        self.assertEqual(queued.record(SESSION), self.record)               # found without its directory, too
        self.assertEqual(queued.record(SESSION, "/work/repo"), self.record)

    def test_one_that_opens_the_next_turn_and_one_taken_back(self):
        self.op("enqueue", "first", ago=4)
        self.op("enqueue", "second", ago=3)
        self.op("dequeue", ago=2)                                           # the turn ended: the first opens the next
        self.assertEqual(self.typed(), [("first", True), ("second", False)])
        self.op("remove", "second", ago=1, reason="cancelled")              # taken back
        self.assertEqual(self.typed(), [("first", True)])

    def test_long_sent_is_forgotten_and_claude_code_s_own_notes_are_not_the_user_s(self):
        self.op("enqueue", "old", ago=100)
        self.op("dequeue", ago=queued.SENT_SECONDS + 5)
        self.op("enqueue", "<task-notification>\n<task-id>b1</task-id>", ago=1)
        self.assertEqual(self.typed(), [])
        # a subagent's report as it hands back, as Claude Code 2.1.310 queues it (saved from a live session)
        self.op("enqueue", '<agent-message from="a6d10bbb09e189a65">\n[Subagent hand-back] The text below is the final report '
                           "of a subagent this session delegated to. ... The report follows:\n  It printed all 100 numbers.\n</agent-message>", ago=1)
        self.op("dequeue", ago=0)
        self.assertEqual(self.typed(), [])

    def test_read_on_from_where_it_was_read_to(self):
        self.op("enqueue", "one", ago=3)
        self.assertEqual(self.typed(), [("one", False)])
        with open(self.record, "a") as fh:                                  # a line still being written
            fh.write('{"type": "queue-operation", "operation": "enq')
        self.assertEqual(self.typed(), [("one", False)])
        with open(self.record, "a") as fh:
            fh.write(f'ueue", "timestamp": "{stamp(self.now)}", "content": "two"}}\n')
        self.assertEqual(self.typed(), [("one", False), ("two", False)])

    def test_held_until_the_turn_ended_is_part_of_it_but_one_written_between_turns_is_not(self):
        self.op("enqueue", "and cook's theorem?", ago=40)
        self.op("enqueue", "and karp's problems?", ago=15)
        self.op("dequeue", ago=1)
        self.op("dequeue", ago=1)                                           # both sent when the turn ended
        self.op("enqueue", "next thing", ago=0.5)
        self.op("dequeue", ago=0.5)                                         # nothing running: sent at once
        self.assertEqual([q["text"] for q in queued.meanwhile(SESSION)], ["and cook's theorem?", "and karp's problems?"])
        self.assertEqual([(q["text"], q["joins"]) for q in queued.typed(SESSION, now=self.now)],   # part of the turn, or the next's
                         [("and cook's theorem?", True), ("and karp's problems?", True), ("next thing", False)])

    def test_a_message_sent_mid_turn_unwrapped(self):
        self.assertEqual(queued.mid_turn(wrapped("change g\ntoo")), "change g\ntoo")
        self.assertIsNone(queued.mid_turn("change g"))


class WatcherTest(RecordBase):
    def test_a_shown_session_s_queue_rings_its_streams(self):
        hub = live.Hub()
        w = hub.watch("g", SESSION)
        other = hub.watch("g", "c2")
        self.assertEqual(hub.shown(), {("g", SESSION), ("g", "c2")})
        watcher = queued.Watcher.__new__(queued.Watcher)                  # its check alone, no thread
        watcher.hub, watcher.last = hub, {}
        w.take(), other.take()
        watcher.check()
        self.assertEqual(w.take(), (False, False, set()))                   # nothing written: nothing rung
        self.now = time.time()
        self.op("enqueue", "also do b")
        watcher.check()
        self.assertEqual((w.take()[1], other.take()[1]), (True, False))
        watcher.check()
        self.assertFalse(w.take()[1])                                       # unchanged
        self.op("remove", "also do b", reason="absorbed_mid_turn")
        watcher.check()
        self.assertTrue(w.take()[1])                                        # sent: the page draws it in full


class TurnTest(RecordBase):
    """In the Chat view, a message written while a turn ran is part of it, under its first message: sent mid-turn, or
    held by Claude Code until the turn ended."""

    def setUp(self):
        super().setUp()
        self.saved, dashboard_home.HOME = dashboard_home.HOME, self.tmp.name
        self.addCleanup(setattr, dashboard_home, "HOME", self.saved)
        os.makedirs(os.path.join(self.tmp.name, "gatherers", "g"))
        conn = sqlite3.connect(os.path.join(self.tmp.name, "gatherers", "g", "context.db"))
        conn.executescript("""CREATE TABLE event_types (event_type_id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL);
            CREATE TABLE events (row_id INTEGER PRIMARY KEY, inserted_at TEXT NOT NULL, event_id TEXT, event_type_id INTEGER NOT NULL,
              payload_json TEXT NOT NULL, tokens INTEGER NOT NULL, text TEXT, counted INTEGER, p_channel);""")
        for typ, payload in (asked("look at a.py"), call("r1", "Read", {"file_path": "/w/a.py"}), result("r1", "1\tx = 1"),
                             asked(wrapped("and b.py")), call("r2", "Read", {"file_path": "/w/b.py"}), result("r2", "1\ty = 2"),
                             said("Both read."), asked("now c.py"), said("Read."),
                             asked("and d.py?\n"), asked("and e.py?"), said("Both.")):
            got = conn.execute("SELECT event_type_id FROM event_types WHERE name = ?", (typ,)).fetchone()
            tid = got[0] if got else conn.execute("INSERT INTO event_types (name, created_at) VALUES (?, '')", (typ,)).lastrowid
            conn.execute("INSERT INTO events (inserted_at, event_type_id, payload_json, tokens, p_channel) VALUES "
                         "(?, ?, ?, 1, ?)", (stamp(self.now), tid, json.dumps(payload), SESSION))
        conn.commit()
        conn.close()

    def turns(self):
        return [(t["text"], [m["text"] for m in t["more"]]) for t in files.files("g", SESSION, 0, cwd="/w")["turns"]]

    def test_one_turn_with_both_messages_and_both_calls(self):
        got = files.files("g", SESSION, 0, cwd="/w")
        self.assertEqual(self.turns()[:2], [("look at a.py", ["and b.py"]), ("now c.py", [])])
        self.assertEqual(got["turns"][0]["replies"], [{"kind": "text", "text": "Both read."}])
        self.assertEqual([f["path"] for f in got["files"]], ["/w/a.py", "/w/b.py"])

    def test_held_until_the_turn_ended_part_of_it(self):
        self.assertEqual(self.turns()[2:], [("and d.py?\n", []), ("and e.py?", [])])   # its record not read: turns
        self.op("enqueue", "and d.py?", ago=20)
        self.op("enqueue", "and e.py?", ago=10)
        self.op("dequeue", ago=0.5)
        self.op("dequeue", ago=0.5)
        self.assertEqual(self.turns(), [("look at a.py", ["and b.py"]), ("now c.py", ["and d.py?", "and e.py?"])])


if __name__ == "__main__":
    unittest.main()
