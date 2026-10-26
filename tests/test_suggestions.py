"""Claude Code's prompt suggestions, and the read-only context they get. A suggestion forks the
session's conversation with a user message asking what the user might type next; it is not a
turn. The hook inserts the conversation's events, asks the server for the context the next call
would get -- read only (`context`): nothing else of the gatherer changes -- puts the suggestion's
message after it, and sends that. Claude Code's other side calls with tools go through as they are."""
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

from ag.ag_harness import Manager  # noqa: E402
from ag.ag_harness import home as ag_home  # noqa: E402
from ag.ag_harness.server import serve  # noqa: E402
from ag.ag_harness.server.__main__ import server_for  # noqa: E402
from ag.ag_harness.store import operations as store  # noqa: E402
from ag.ag_harness.store import paths  # noqa: E402
from ag.ag_policies.proactive_context_manager import ProactiveContextManager  # noqa: E402
from ag.integrations.harnesses.claude.adaptor import to_events as claude  # noqa: E402
from ag.integrations.harnesses.claude.ag_orchestrator import context_manager as claude_ag  # noqa: E402
from ag.integrations.harnesses.codex.ag_orchestrator.ag_clients import AgClients  # noqa: E402
from ag.integrations.harnesses.codex.adaptor import to_events as codex  # noqa: E402
from channels import ch  # noqa: E402
from test_core import PREAMBLE, SMALL, Recording, ScriptedLLM, conversation, user  # noqa: E402
import codex_items  # noqa: E402

SUGGEST = {"role": "user", "content": [{"type": "text", "text": "[SUGGESTION MODE: Suggest what the user might "
                                                                "naturally type next into Claude Code.]\n\n..."}]}


def tables(path):
    conn = sqlite3.connect(path)
    try:
        return {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                for t in ("events", "_reads", "_read_items", "_made_items", "_builds", "_boundaries")}
    finally:
        conn.close()


class ReadOnlyTest(unittest.TestCase):
    """The manager's context_only: the context, and the gatherer's state as it was."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = paths.TRACE_DIR
        paths.TRACE_DIR = os.path.join(self.tmp.name, "traces")
        self.spawned = []
        self.policy = ProactiveContextManager(codex_items.FORMAT, ScriptedLLM(), options=dict(SMALL))
        self.policy.jobs = Recording(lambda s, c, job, job_id: self.spawned.append(job))
        self.m = Manager(self.policy)
        self.m.init("s")
        self.items = codex_items.CodexItems(self.m)

    def tearDown(self):
        paths.TRACE_DIR = self.saved
        self.tmp.cleanup()

    def put(self, items):
        for item in items:
            self.items.insert("s", item, channel_id="c1")

    def test_nothing_of_the_gatherer_changes(self):
        self.put(PREAMBLE + conversation(4) + [user("one more", 9)])     # at a user message: a check is due
        before = tables(paths.db_path("s"))
        row = store.high_water(self.m._conn("s"))
        events, sizes = self.m.context_only("s", row, properties=ch("c1"))
        self.assertTrue(events)
        self.assertEqual(tables(paths.db_path("s")), before)              # no read, no claim, no notice
        self.assertEqual(self.spawned, [])                                 # no check started
        self.assertIs(type(self.policy.jobs), Recording)                   # the policy's own, back
        real = self.m.read_logged("s", row, properties=ch("c1"))[0]
        self.assertEqual(self.spawned, ["check"])                          # a real read: the check
        self.assertEqual([(e["type"], e.get("id")) for e in events], [(e["type"], e.get("id")) for e in real])
        self.assertGreater(sizes["sent_tokens"], 0)


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
        answers = [json.loads(line) for line in out.getvalue().splitlines()]
        return sorted(answers, key=lambda a: a["id"])        # as asked: each comes out as it is ready

    def test_context_inserts_the_events_and_logs_no_read(self):
        u1 = {"type": "message", "role": "user", "id": "u1", "content": [{"type": "input_text", "text": "hi"}]}
        a1 = {"type": "message", "role": "assistant", "id": "a1", "content": [{"type": "output_text", "text": "hello"}]}
        first, = self.ask({"op": "rewrite", "gatherer": "s", "properties": {"channel": "c"}, "events": codex.to_events([u1])})
        before = tables(paths.db_path("s"))
        side, = self.ask({"op": "context", "gatherer": "s", "properties": {"channel": "c"},
                          "events": codex.to_events([u1, a1])})
        after = tables(paths.db_path("s"))
        self.assertEqual(after["events"], before["events"] + 1)            # the reply is the conversation's
        self.assertEqual({k: v for k, v in after.items() if k != "events"},
                         {k: v for k, v in before.items() if k != "events"})
        self.assertNotIn("read_id", {k: v for k, v in side.items() if v is not None})
        self.assertEqual([e["type"] for e in side["context"]][-1], "agent_message")
        self.assertIn("read only", side["note"])


class Server:
    """The context manager's server, as the hook sees it: answers what it is asked, recording it."""

    def __init__(self):
        self.asked = []

    async def request(self, op, body=None, timeout=None):
        if op == "latest":                   # the channel's newest stored, as the gatherer answers it
            kept = {e["id"]: e for _, b in self.asked for e in b.get("events", [])}
            return {"events": [{"id": e["id"], "payload": e["payload"]} for e in list(kept.values())[-body["n"]:]]}
        self.asked.append((op, body))
        if op in ("rewrite", "context"):
            return {"context": [{"type": "ag", "name": "earlier", "text": "SUMMARY"}] + body["events"], "note": "ok",
                    **({"read_id": len(self.asked)} if op == "rewrite" else {}), "basis": None}
        return {}

    async def stop(self):
        pass


def conversation_so_far():
    return [{"role": "user", "content": "count the rows"},
            {"role": "assistant", "content": [{"type": "text", "text": "There are 42 rows."}]}]


class HookTest(unittest.TestCase):
    def call(self, hook, messages, headers=None):
        req = SimpleNamespace(method="POST", path="/v1/messages", label="g", limit=None, state={}, upstream=None,
                              headers=dict({"X-Claude-Code-Session-Id": "s"}, **(headers or {})),
                              body={"model": "m", "tools": [{"name": "Bash"}], "messages": messages})
        return asyncio.run(hook(req))

    def hook(self, server):
        return claude_ag.ClaudeContextManager(ag_clients=AgClients(lambda g: server), log=lambda g, l: None)

    def test_a_suggestion_gets_the_context_read_only_and_its_message_after_it(self):
        server = Server()
        hook = self.hook(server)
        out = self.call(hook, conversation_so_far() + [SUGGEST], {"X-Claude-Code-Request-Class": "auxiliary"})
        self.assertEqual([op for op, _ in server.asked], ["context"])     # not a rewrite: no read, nothing counted
        sent = server.asked[0][1]["events"]
        self.assertFalse(any("SUGGESTION MODE" in json.dumps(e) for e in sent))   # its message is not stored
        self.assertEqual(out["messages"][-1], SUGGEST)
        self.assertEqual(out["messages"][0]["content"][0]["text"], "SUMMARY")      # the context, before it
        self.assertEqual(claude_ag.suggestion_at(conversation_so_far()), None)

    def test_a_suggestion_that_called_a_tool_is_still_the_suggestion(self):
        server = Server()
        hook = self.hook(server)
        called = [{"role": "assistant", "content": [{"type": "tool_use", "id": "toolu_1", "name": "ScheduleWakeup",
                                                     "input": {"stop": True}}]},
                  {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "is_error": True,
                                                "content": "No tools needed for suggestion"}]}]
        req = SimpleNamespace(method="POST", path="/v1/messages", label="g", limit=None, state={}, upstream=None,
                              headers={"X-Claude-Code-Session-Id": "s"},
                              body={"model": "m", "tools": [{"name": "Bash"}],
                                    "messages": conversation_so_far() + [SUGGEST] + called})
        out = asyncio.run(hook(req))                                    # asked again, the refusal after the call
        self.assertEqual([op for op, _ in server.asked], ["context"])
        sent = json.dumps(server.asked[0][1]["events"])
        self.assertNotIn("SUGGESTION MODE", sent)                         # none of it stored
        self.assertNotIn("No tools needed", sent)
        self.assertEqual(out["messages"][-3:], [SUGGEST] + called)
        self.assertNotIn(claude_ag.ANSWERED, req.state)                   # its answer is not kept as the session's
        self.assertIsNone(claude_ag.suggestion_at(conversation_so_far() + [{"role": "user", "content": "next"}]
                                                  + called))              # a turn's own tool call: a turn

    def test_the_next_turn_carries_on_from_the_conversation_not_the_suggestion(self):
        server = Server()
        hook = self.hook(server)
        self.call(hook, conversation_so_far())                                     # the turn
        self.call(hook, conversation_so_far() + [SUGGEST])                         # its suggestion
        nxt = conversation_so_far() + [{"role": "user", "content": "And the columns?"}]
        self.call(hook, nxt)                                                       # the next turn
        op, body = server.asked[-1]
        self.assertEqual(op, "rewrite")
        self.assertLessEqual(len(body["events"]), len(claude.pieces(nxt)))
        self.assertEqual(body["events"][-1]["payload"]["content"][0]["text"], "And the columns?")
        stored = {e["id"]: e for _, b in server.asked for e in b["events"]}
        self.assertEqual(len(stored), len(claude.pieces(nxt)))                     # each piece one event: no resend

    def test_another_side_call_goes_through_as_it_is(self):
        server = Server()
        out = self.call(self.hook(server), conversation_so_far() + [{"role": "user", "content": "Summarize this session."}],
                        {"X-Claude-Code-Request-Class": "auxiliary"})
        self.assertIsNone(out)
        self.assertEqual(server.asked, [])

    def test_a_main_call_is_a_turn(self):
        server = Server()
        self.call(self.hook(server), conversation_so_far() + [{"role": "user", "content": "next"}],
                  {"X-Claude-Code-Request-Class": "main"})
        self.assertEqual([op for op, _ in server.asked], ["rewrite"])


if __name__ == "__main__":
    unittest.main()
