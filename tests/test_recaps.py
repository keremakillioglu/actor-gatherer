"""Claude Code's away recaps. When the user has left, Claude Code forks the session's conversation with
a user message asking for a short recap (`The user stepped away and is coming back. ...`). It is not a
turn: the hook sends it as it sends a prompt suggestion -- the context read only, the recap's message
after it -- and keeps its answer as the session's recap (the server's `recap`: `_recaps`), never as
events or pending. The dashboard shows each session's newest recap."""
import asyncio
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ag.ag_harness import home as ag_home  # noqa: E402
from ag.ag_harness.server import serve  # noqa: E402
from ag.ag_harness.server.__main__ import server_for  # noqa: E402
from ag.ag_harness.store import paths  # noqa: E402
from ag.integrations.harnesses.claude.adaptor import to_events as claude  # noqa: E402
from ag.integrations.harnesses.claude.ag_orchestrator import context_manager as claude_ag  # noqa: E402
from ag.integrations.harnesses.codex.ag_orchestrator.ag_clients import AgClients  # noqa: E402
from ag.integrations.tools.hook_server.trace import response_of  # noqa: E402
from test_pending import sse  # noqa: E402

RECAP = {"role": "user", "content": [{"type": "text", "text": (
    "The user stepped away and is coming back. Recap in under 40 words, 1-2 plain sentences, no markdown. "
    "Lead with the overall goal and current task, then the one next action. Skip root-cause narrative, fix "
    "internals, secondary to-dos, and em-dash tangents.")}]}
SUMMARY = "You're counting the rows of rows.csv; there are 42. Next, count the columns."


def conversation_so_far():
    return [{"role": "user", "content": "count the rows"},
            {"role": "assistant", "content": [{"type": "text", "text": "There are 42 rows."}]}]


class Server:
    """The context manager's server, as the hook sees it: answers what it is asked, recording it."""

    def __init__(self):
        self.asked = []

    async def request(self, op, body=None, timeout=None):
        if op == "latest":                   # a gatherer with nothing stored yet
            return {"events": []}
        if op == "insert":                   # what the hook records besides the conversation: kept apart
            self.records = getattr(self, "records", []) + [dict(e, channel=body["properties"]["channel"])
                                                           for e in body["events"]]
            return {"rows": []}
        self.asked.append((op, body))
        if op in ("rewrite", "context"):
            return {"context": [{"type": "ag", "name": "earlier", "text": "SUMMARY"}] + body["events"], "note": "ok",
                    **({"read_id": len(self.asked)} if op == "rewrite" else {}), "basis": None}
        if op == "recap":
            return {"recap_id": 1}
        return {}

    async def stop(self):
        pass


class HookTest(unittest.TestCase):
    def setUp(self):
        self.server = Server()
        self.hook = claude_ag.ClaudeContextManager(ag_clients=AgClients(lambda g: self.server), log=lambda g, l: None,
                                                   count="off")

    def call(self, messages, answer=None, status=200, headers=None):
        req = SimpleNamespace(method="POST", path="/v1/messages", label="g", limit=None, state={}, upstream=None,
                              headers=dict({"X-Claude-Code-Session-Id": "s"}, **(headers or {})),
                              body={"model": "m", "tools": [{"name": "Bash"}], "messages": messages})

        async def go():
            out = await self.hook(req)
            if answer is not None:
                await self.hook.answered(req, status, response_of(answer))
            return out
        return asyncio.run(go())

    def test_a_recap_is_found_as_a_suggestion_is(self):
        self.assertEqual(claude_ag.recap_at(conversation_so_far() + [RECAP]), 2)
        self.assertIsNone(claude_ag.recap_at(conversation_so_far()))
        self.assertIsNone(claude_ag.suggestion_at(conversation_so_far() + [RECAP]))     # not a suggestion

    def test_a_recap_gets_the_context_read_only_and_its_message_after_it(self):
        for headers in ({"X-Claude-Code-Request-Class": "auxiliary"}, {}):           # with Claude Code's class or not
            self.server.asked.clear()
            out = self.call(conversation_so_far() + [RECAP], headers=headers)
            self.assertEqual([op for op, _ in self.server.asked], ["context"])      # not a rewrite: no read
            sent = self.server.asked[0][1]["events"]
            self.assertFalse(any("stepped away" in json.dumps(e) for e in sent))   # its message is not stored
            self.assertEqual(out["messages"][-1], RECAP)
            self.assertEqual(out["messages"][0]["content"][0]["text"], "SUMMARY")    # the context, before it

    def recorded(self, *types):
        return [(e["type"], e["channel"], e["payload"]) for e in getattr(self.server, "records", []) if e["type"] in types]

    def test_its_answer_is_kept_as_the_session_s_recap_not_as_its_reply(self):
        self.call(conversation_so_far() + [RECAP], sse([{"type": "text", "text": SUMMARY}], "end_turn"))
        self.assertEqual([op for op, _ in self.server.asked], ["context"])
        self.assertEqual(self.recorded("recap", "reply_part", "reply_end"), [("recap", "s", {"text": SUMMARY})])
        self.assertEqual([p["kind"] for _, _, p in self.recorded("model_call")], ["recap"])

    def test_a_failed_or_empty_recap_is_not_kept(self):
        self.call(conversation_so_far() + [RECAP], sse([{"type": "text", "text": SUMMARY}], "end_turn"), status=529)
        self.call(conversation_so_far() + [RECAP], sse([{"type": "text", "text": "  "}], "end_turn"))
        self.assertEqual(self.recorded("recap"), [])

    def test_the_session_s_own_turn_is_still_recorded_as_its_reply(self):
        self.call(conversation_so_far() + [{"role": "user", "content": "and the columns?"}],
                  sse([{"type": "text", "text": "3 columns."}], "end_turn"))
        self.assertEqual([op for op, _ in self.server.asked], ["rewrite"])
        self.assertEqual([t for t, _, _ in self.recorded("reply_part", "reply_end", "recap")], ["reply_part", "reply_end"])


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = paths.TRACE_DIR, paths.AG_HOME
        paths.AG_HOME = os.path.join(self.tmp.name, "ag")
        paths.TRACE_DIR = os.path.join(paths.AG_HOME, "gatherers")
        ag_home._HOMES.clear()

    def tearDown(self):
        paths.TRACE_DIR, paths.AG_HOME = self.saved
        ag_home._HOMES.clear()
        self.tmp.cleanup()

    def ask(self, *requests):
        out = io.StringIO()
        serve(server_for(), [json.dumps(dict(r, id=i)) for i, r in enumerate(requests, 1)], out)
        return [json.loads(line) for line in out.getvalue().splitlines()]

    def rows(self, sql):
        conn = sqlite3.connect(paths.db_path("g"))
        try:
            return conn.execute(sql).fetchall()
        finally:
            conn.close()

    def test_a_recap_is_kept_with_when_it_was_made_and_never_as_an_event(self):
        call = {"op": "rewrite", "gatherer": "g", "properties": {"channel": "c1"}, "cwd": None,
                "events": claude.to_events(conversation_so_far())}
        _, kept, again, bad = self.ask(call, {"op": "recap", "gatherer": "g", "session": "c1", "text": " First. "},
                                       {"op": "recap", "gatherer": "g", "session": "c1", "text": "Second."},
                                       {"op": "recap", "gatherer": "g", "session": "c1", "text": " "})
        self.assertEqual((kept["recap_id"], again["recap_id"]), (1, 2))
        self.assertIn("error", bad)
        recaps = self.rows("SELECT session, text, made_at FROM _recaps ORDER BY recap_id")
        self.assertEqual([(s, t) for s, t, _ in recaps], [("c1", "First."), ("c1", "Second.")])
        self.assertTrue(all(m for _, _, m in recaps))
        self.assertEqual(self.rows("SELECT count(*) FROM events WHERE text IN ('First.', 'Second.')"), [(0,)])

    def test_a_name_is_kept_per_session_and_namer_the_newest_in_place(self):
        _, first, again, other, bad = self.ask(
            {"op": "rewrite", "gatherer": "g", "properties": {"channel": "c1"}, "cwd": None,
             "events": claude.to_events(conversation_so_far())},
            {"op": "name", "gatherer": "g", "session": "c1", "text": " Tally  things ", "by": "codex"},
            {"op": "name", "gatherer": "g", "session": "c1", "text": "Tally the things", "by": "codex"},
            {"op": "name", "gatherer": "g", "session": "c2", "text": "Other", "by": "codex"},
            {"op": "name", "gatherer": "g", "session": "c1", "text": "No namer"})
        self.assertEqual((first, again, other), ({"id": 2}, {"id": 3}, {"id": 4}))
        self.assertIn("error", bad)
        self.assertEqual(self.rows("SELECT session, by, text FROM _names ORDER BY session"),
                         [("c1", "codex", "Tally the things"), ("c2", "codex", "Other")])
        self.assertEqual(self.rows("SELECT count(*) FROM events WHERE text LIKE '%Tally%'"), [(0,)])


if __name__ == "__main__":
    unittest.main()
