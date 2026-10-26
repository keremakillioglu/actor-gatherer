"""The dashboard reads what a harness's hook records of a session besides its conversation (records.py): the reply as it
comes, its end, a failed call, a recap, a name -- in a gatherer ag's own server wrote, as the hooks send them."""
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ag.ag_harness import home as ag_home  # noqa: E402
from ag.ag_harness.server import serve  # noqa: E402
from ag.ag_harness.server.__main__ import server_for  # noqa: E402
from ag.ag_harness.store import paths  # noqa: E402
from ag.integrations.harnesses.claude.adaptor.adaptor import ClaudeAdaptor  # noqa: E402
from ag.integrations.tools.ag_orchestrator import records  # noqa: E402
from ag_dashboard import data, files  # noqa: E402
from ag_dashboard import home as dashboard_home  # noqa: E402

ADAPTOR = ClaudeAdaptor()


def user(text):
    return {"role": "user", "content": [{"type": "text", "text": text}]}


def said(*blocks):
    return {"role": "assistant", "content": list(blocks)}


TEXT = {"type": "text", "text": "Counting."}
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
        self.record(records.call_failed(read, data.HUNG_UP, "the harness hung up before the answer was through"))
        a = self.agent()                                                     # Esc: as the hook server reports it
        self.assertEqual((a["status"], a["stopped"]["kind"], a["failing"]), (data.IDLE, "interrupted", None))

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
