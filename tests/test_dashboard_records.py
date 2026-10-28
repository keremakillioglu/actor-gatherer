"""The dashboard reads what a harness's hook records of a session besides its conversation (records.py): the reply as it
comes, its end, a failed call, a recap, a name -- in a gatherer ag's own server wrote, as the hooks send them."""
import io
import json
import os
import sys
import tempfile
import time
import unittest
import unittest.mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ag.ag_harness import home as ag_home  # noqa: E402
from ag.ag_harness.server import serve  # noqa: E402
from ag.ag_harness.server.__main__ import server_for  # noqa: E402
from ag.ag_harness.store import paths  # noqa: E402
from ag.integrations.harnesses.claude.adaptor.adaptor import ClaudeAdaptor  # noqa: E402
from ag.integrations.tools.ag_orchestrator import records  # noqa: E402
from ag_dashboard import data, files, sessions  # noqa: E402
from harness_kit.base import Fact, Facts  # noqa: E402
from ag_dashboard import home as dashboard_home  # noqa: E402

ADAPTOR = ClaudeAdaptor()


def user(text):
    return {"role": "user", "content": [{"type": "text", "text": text}]}


def said(*blocks):
    return {"role": "assistant", "content": list(blocks)}


TEXT = {"type": "text", "text": "Counting."}
INTERRUPT = {"role": "user", "content": [{"type": "text", "text": "[Request interrupted by user]"}]}
CALL = {"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {"command": "wc -l rows.csv"}}
RESULT = {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "42 rows.csv"}]}


class RecordsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.saved = paths.TRACE_DIR, paths.AG_HOME, dashboard_home.HOME
        paths.AG_HOME = dashboard_home.HOME = os.path.join(self.tmp.name, "ag")
        paths.TRACE_DIR = os.path.join(paths.AG_HOME, "gatherers")
        ag_home._HOMES.clear()

    def tearDown(self):
        paths.TRACE_DIR, paths.AG_HOME, dashboard_home.HOME = self.saved
        ag_home._HOMES.clear()

    def ask(self, *requests):
        out = io.StringIO()
        serve(server_for(), [json.dumps(dict(r, id=i)) for i, r in enumerate(requests, 1)], out)
        return [json.loads(line) for line in out.getvalue().splitlines()]

    def turn(self, messages):
        """A turn's call: its conversation stored, as the hook's rewrite does, and the call recorded."""
        got, = self.ask({"op": "rewrite", "gatherer": "g", "properties": {"channel": "s"}, "cwd": "/w",
                         "events": ADAPTOR.to_events(messages)})
        self.record(records.model_call("turn", "claude", "2.1.310", got.get("read_id")))
        return got.get("read_id")

    def record(self, *events):
        self.ask({"op": "insert", "gatherer": "g", "properties": {"channel": "s"}, "events": list(events)})

    def reply(self, answer_id, blocks, stop=None, read_id=None):
        parts = records.reply_parts(answer_id, ADAPTOR.to_events([said(*blocks)]))
        self.record(*parts, *([records.reply_end(answer_id, stop, read_id)] if stop else []))

    def agent(self):
        a, = [a for g in data.home([])["gatherers"] if g["name"] == "g" for a in g["agents"]]
        return a

    def test_a_reply_shows_until_a_call_carries_it_back(self):
        first = [user("count the rows")]
        read = self.turn(first)
        self.reply("msg_1", [TEXT])                                          # streaming: its first part
        self.reply("msg_1", [TEXT, CALL], "tool_use", read)                  # whole: the same part once, and the call
        pending = data.history("g", "s", 0)["items"][-2:]
        self.assertEqual([(i["group"], i["name"]) for i in pending], [("Pending", "agent_message"), ("Pending", "tool_call")])
        self.assertEqual(self.agent()["status"], data.RUNNING)                # it waits on a tool: not over
        self.turn(first + [said(TEXT, CALL), RESULT])                          # the next call carries it back
        self.reply("msg_2", [{"type": "text", "text": "There are 42 rows."}], "end_turn")
        items = data.transcript("g", "s")["items"]
        self.assertEqual([i["type"] for i in items], ["user_message", "agent_message", "tool_call", "tool_output",
                                                      "agent_message"])        # no record among them; the reply once
        self.assertEqual(items[-1]["row_id"], None)                            # still pending: no call has carried it
        self.assertEqual(self.agent()["status"], data.IDLE)                    # it ended its turn
        turns = files.files("g", "s", cwd="/w")["turns"]
        self.assertEqual([r["text"] for r in turns[0]["replies"] if r["kind"] == "text"], ["Counting.", "There are 42 rows."])

    def test_an_answer_that_broke_off_as_it_streamed_is_dropped_at_the_next_turn(self):
        read = self.turn([user("count the rows")])
        self.reply("msg_1", [TEXT])                                          # streams, then breaks off: no end
        self.assertEqual(len(data.replies(data._connect("g"), "s")), 1)
        self.record(records.model_call("turn", "claude", None, read))        # Claude Code tries again
        self.assertEqual(data.replies(data._connect("g"), "s"), [])

    def test_a_call_the_user_stopped_ends_the_turn_and_is_no_failure(self):
        read = self.turn([user("count the rows")])
        self.assertEqual(self.agent()["status"], data.RUNNING)
        self.assertFalse(sessions.took_back("g", "s", time.time()))
        self.record(records.call_failed(read, data.HUNG_UP, "the harness hung up before the answer was through"))
        a = self.agent()                                                     # Esc: as the hook server reports it
        self.assertEqual((a["status"], a["stopped"]["kind"], a["failing"]), (data.IDLE, "interrupted", None))
        self.assertTrue(sessions.took_back("g", "s", time.time()))          # its message back in Claude Code's box

    def hang_up(self, messages, reached=None):
        """A call stored, then hung up on (Esc): reported so by the hook server -- with what of the answer had reached the
        harness in words, as one that says does (`reached`) -- and its events withdrawn, as the hook does on any Esc. Its
        read."""
        got, = self.ask({"op": "rewrite", "gatherer": "g", "properties": {"channel": "s"}, "cwd": "/w",
                         "events": ADAPTOR.to_events(messages)})
        self.record(records.model_call("turn", "claude", "2.1.310", got["read_id"]))
        self.record(records.call_failed(got["read_id"], data.HUNG_UP, "the harness hung up before the answer was through",
                                        reached))
        self.ask({"op": "withdraw", "gatherer": "g", "properties": {"channel": "s"}, "rows": got["inserted"],
                  "read_id": got["read_id"]})
        return got["read_id"]

    def test_a_message_stopped_before_its_answer_is_taken_back(self):
        """Esc before any of the answer came: Claude Code puts the user's message back in its input box, recording nothing
        of it, and the hook has ag withdraw what the call stored. Once its record has said nothing of the turn for
        TAKEN_SECONDS, the actor has the message as taken back, in the user's words, until it is sent again. A call hung
        up on later in a turn takes no message back."""
        self.record(records.session_file("claude", "/c/s.jsonl"))          # its record followed
        first = [user("count the rows")]
        read = self.turn(first)
        self.reply("msg_1", [TEXT, CALL], "tool_use", read)
        later = first + [said(TEXT, CALL), RESULT]
        self.hang_up(later)
        with unittest.mock.patch.object(data, "TAKEN_SECONDS", 0.0):
            self.assertIsNone(self.agent()["taken_back"])                   # later in the turn: nothing to take back
        nxt = later + [said({"type": "text", "text": "There are 42 rows."}), user("and the columns?")]
        self.hang_up(nxt)
        a = self.agent()                                                     # not yet: its record may still say
        self.assertEqual((a["status"], a["taken_back"]), (data.IDLE, None))
        self.assertTrue(sessions.took_back("g", "s", time.time()))          # the box emptied before a message: at once
        with unittest.mock.patch.object(data, "TAKEN_SECONDS", 0.0):
            a = self.agent()
        self.assertEqual(a["taken_back"]["text"], "and the columns?")
        turns = files.files("g", "s", cwd="/w")["turns"]
        self.assertEqual([t["text"] for t in turns], ["count the rows"])     # in no turn; the steps before it still shown
        self.assertEqual([r["text"] for r in turns[0]["replies"] if r["kind"] == "text"], ["Counting.", "There are 42 rows."])
        self.turn(nxt)                                                       # sent again (Enter on it)
        with unittest.mock.patch.object(data, "TAKEN_SECONDS", 0.0):
            self.assertIsNone(self.agent()["taken_back"])

    def test_a_message_stopped_once_its_answer_began_is_kept(self):
        """Esc once some of the answer came: Claude Code keeps the message and records the turn interrupted. The hook
        withdrew the call's events all the same; the message is not taken back, and Chat shows its turn, interrupted."""
        self.record(records.session_file("claude", "/c/s.jsonl"))
        first = [user("count the rows")]
        read = self.turn(first)
        self.reply("msg_1", [{"type": "text", "text": "There are 42 rows."}], "end_turn", read)
        nxt = first + [said({"type": "text", "text": "There are 42 rows."}), user("and the columns?")]
        self.hang_up(nxt)
        cut = self.agent()["stopped"]["at"]                                  # as the hang-up says
        at = time.time() + 1
        self.record(records.fact(Fact(Facts.TURN_STOPPED, "7", at, {"how": "interrupted"}), "/c/s.jsonl"))
        self.assertEqual(self.agent()["stopped"]["at"], at)                  # as its record says, once it does: the
        self.assertNotEqual(cut, at)                                         # actor changed, Chat loads its turns again
        with unittest.mock.patch.object(data, "TAKEN_SECONDS", 0.0):
            self.assertIsNone(self.agent()["taken_back"])
        self.assertFalse(sessions.took_back("g", "s", time.time()))         # nothing in its box to empty
        turns = files.files("g", "s", cwd="/w")["turns"]
        self.assertEqual([(t["text"], t["stopped"] and t["stopped"]["kind"]) for t in turns],
                         [("count the rows", None), ("and the columns?", "interrupted")])

    def test_a_message_stopped_after_a_turn_that_was_kept_is_taken_back(self):
        """A turn interrupted once its answer began (kept), then the next message stopped before any of its answer came.
        Its call sends the turn before again, and the hook withdraws that with it (re-kept, stored long before): the
        interrupt of the turn before is not this call's, the message taken back is the newest, and the turn before stays
        in Chat."""
        self.record(records.session_file("claude", "/c/s.jsonl"))
        first = [user("count the rows")]
        self.hang_up(first)                                                  # Esc once its answer began: withdrawn too
        time.sleep(0.05)
        self.record(records.fact(Fact(Facts.TURN_STOPPED, "7", time.time(), {"how": "interrupted"}), "/c/s.jsonl"))
        time.sleep(0.05)
        self.hang_up(first + [said({"type": "text", "text": "Count"}), INTERRUPT, user("and the columns?")])
        with unittest.mock.patch.object(data, "TAKEN_SECONDS", 0.0):
            a = self.agent()
        self.assertEqual(a["taken_back"]["text"], "and the columns?")
        self.assertTrue(sessions.took_back("g", "s", time.time()))          # its box emptied before a message from Chat
        turns = files.files("g", "s", cwd="/w")["turns"]
        self.assertEqual([(t["text"], t["stopped"] and t["stopped"]["kind"]) for t in turns], [("count the rows", "interrupted")])

    def test_what_reached_the_harness_says_at_once_whether_the_message_was_taken_back(self):
        """The hook server saw what of the answer it relayed: none of its words -- taken back, at once, with or without
        Claude Code's record; its text begun -- kept, at once."""
        first = [user("count the rows")]
        self.turn(first)
        nxt = first + [said({"type": "text", "text": "42."}), user("and the columns?")]
        self.hang_up(nxt, "nothing")                                         # no record followed, no wait
        self.assertEqual(self.agent()["taken_back"]["text"], "and the columns?")
        self.assertTrue(sessions.took_back("g", "s", time.time()))
        self.hang_up(nxt + [said({"type": "text", "text": "The columns"}), INTERRUPT, user("and the rows?")], "text")
        self.assertIsNone(self.agent()["taken_back"])
        self.assertFalse(sessions.took_back("g", "s", time.time()))
        self.assertEqual([t["text"] for t in files.files("g", "s", cwd="/w")["turns"]],
                         ["count the rows", "and the columns?", "and the rows?"])   # kept: its turn shown

    def test_a_call_carrying_a_message_written_mid_turn_takes_nothing_back(self):
        """Claude Code sends what the user wrote as it worked with a tool's result: that call hung up on is later in a
        turn, and takes no message back."""
        self.record(records.session_file("claude", "/c/s.jsonl"))
        first = [user("count the rows")]
        read = self.turn(first)
        self.reply("msg_1", [TEXT, CALL], "tool_use", read)
        mid = {"role": "user", "content": [RESULT["content"][0], {"type": "text", "text": (
            "The user sent a new message while you were working:\nalso the columns\n\nThis is how Claude Code surfaces "
            "messages the user sends mid-turn -- within the running turn, often alongside the next tool result, rather "
            "than as a separate conversation turn. Address the message above as you continue this turn.")}]}
        self.hang_up(first + [said(TEXT, CALL), mid])
        with unittest.mock.patch.object(data, "TAKEN_SECONDS", 0.0):
            self.assertIsNone(self.agent()["taken_back"])

    def test_a_message_sent_again_is_had_once_a_call_is_read_after_it(self):
        """A message taken back and sent again is kept again where it was first stored, at its first time: a call ag read
        after it was sent says it was had, so it is no longer shown as one the agent has not had (`_unstored`)."""
        first = [user("count the rows")]
        self.turn(first)
        time.sleep(0.05)
        sent = time.time()                                                   # Claude Code sends it again
        q = {"text": "count the rows", "at": sent, "sent": sent, "joins": False}
        conn = data._connect("g")
        self.assertEqual(data._unstored(conn, "s", [q]), [q])               # not yet read: not had
        self.turn(first)                                                     # its call: nothing new stored
        self.assertEqual(data._unstored(data._connect("g"), "s", [q]), [])

    def test_one_actor_s_records_are_found_by_its_channel_not_by_their_type(self):
        """Searched by type, each actor's would go through every actor's records newer than its own last event: the
        actor list slowed with every record in the gatherer."""
        read = self.turn([user("count the rows")])
        self.reply("msg_1", [TEXT, CALL], "tool_use", read)
        self.record(records.call_failed(read, 529, "overloaded_error: Overloaded"))
        conn, plans = data._connect("g"), []

        class Planned:                                                       # the plan of each query on events
            def execute(self, sql, args=()):
                if " FROM events e JOIN event_types t" in sql:
                    plans.append(" ".join(r[3] for r in conn.execute("EXPLAIN QUERY PLAN " + sql, args)))
                return conn.execute(sql, args)

            def __getattr__(self, name):
                return getattr(conn, name)
        data.replies(Planned(), "s")
        data._harness(Planned(), "s")
        data._newest_reads(Planned(), "s", 2)
        conn.close()
        self.assertEqual(len(plans), 3)
        for plan in plans:
            self.assertIn("events_id", plan)
            self.assertNotIn("events_type", plan)

    def test_a_failed_call_a_recap_and_a_name(self):
        read = self.turn([user("count the rows")])
        self.record(records.call_failed(read, 529, "overloaded_error: Overloaded"))
        failing = self.agent()["failing"]
        self.assertEqual((failing["status"], failing["error"], failing["attempts"]), (529, "overloaded_error: Overloaded", 1))
        self.record(records.recap("Counted the rows."), records.name("Row count", "codex"))
        a = self.agent()
        self.assertEqual((a["recap"]["text"], a["name"]), ("Counted the rows.", {"text": "Row count", "by": "codex"}))
        self.assertEqual(a["harness"], "claude")                              # as its model calls say
        self.assertEqual(a["events"], 1)                                      # the conversation's: no record


if __name__ == "__main__":
    unittest.main()
