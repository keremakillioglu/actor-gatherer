"""Pending events: what the model answered that no model call has carried back yet. The proxy hook
keeps each answer of a session's own call, as events, in `_pending` with the call's properties; the
next call with those properties that stores new events -- the answer among them -- deletes them. So a
reader of the gatherer sees the reply that ends a turn, which no call carries until the user writes
again, without it ever being history twice."""
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
from ag.ag_harness.store import schema  # noqa: E402
from ag.integrations.harnesses.claude.adaptor import to_events as claude  # noqa: E402
from ag.integrations.harnesses.claude.ag_orchestrator import context_manager as claude_ag  # noqa: E402
from ag.integrations.harnesses.codex.ag_orchestrator.ag_clients import AgClients  # noqa: E402
from ag.integrations.tools.hook_server.trace import response_of  # noqa: E402

C1 = {"channel": "c1", "cwd": "/w"}
C2 = {"channel": "c2", "cwd": "/w"}
REPLY = {"role": "assistant", "content": [{"type": "text", "text": "There are 42 rows."}]}


def ask(text):
    return {"role": "user", "content": text}


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

    def call(self, properties, messages):
        return {"op": "rewrite", "gatherer": "g", "properties": properties, "cwd": None,
                "events": claude.to_events(messages)}

    def pend(self, properties, answer=REPLY):
        return {"op": "pending", "gatherer": "g", "properties": properties,
                "events": claude.to_events([answer]), "answer": "msg_1", "stop": "end_turn"}

    def test_an_answer_is_pending_until_its_channel_s_next_call(self):
        first, kept, other = self.ask(self.call(C1, [ask("count the rows")]), self.pend(C1),
                                      self.call(C2, [ask("something else")]))
        self.assertEqual(kept, {"id": 2, "kept": 1})
        self.assertEqual(self.rows("SELECT type, text, answer, stop, p_channel FROM _pending"),
                         [("agent_message", "There are 42 rows.", "msg_1", "end_turn", "c1")])   # another channel's call: kept
        before = self.rows("SELECT count(*) FROM events")[0][0]
        self.assertFalse(any("42 rows" in str(t) for (t,) in self.rows("SELECT text FROM events")))  # not history
        self.ask(self.call(C1, [ask("count the rows"), REPLY, ask("and the columns?")]))
        self.assertEqual(self.rows("SELECT count(*) FROM _pending"), [(0,)])
        self.assertEqual(self.rows("SELECT count(*) FROM events")[0][0], before + 2)   # the reply, the request: once

    def test_a_call_from_another_directory_of_the_channel_clears_them(self):
        """cwd only describes where an event happened: the channel's next call carries the answer back
        whatever directory it comes from."""
        self.ask(self.call(C1, [ask("count the rows")]), self.pend(C1),
                 self.call(dict(C1, cwd="/w/sub"), [ask("count the rows"), REPLY, ask("and the columns?")]))
        self.assertEqual(self.rows("SELECT count(*) FROM _pending"), [(0,)])
        self.assertEqual(self.rows("SELECT count(*) FROM events WHERE text = 'There are 42 rows.'"), [(1,)])

    def test_a_read_only_call_clears_them_too(self):
        self.ask(self.call(C1, [ask("count the rows")]), self.pend(C1),
                 dict(self.call(C1, [ask("count the rows"), REPLY]), op="context"))   # a suggestion's
        self.assertEqual(self.rows("SELECT count(*) FROM _pending"), [(0,)])

    def test_a_call_that_stores_nothing_keeps_them(self):
        """Claude Code's idle compaction sends the history before the reply, all of it stored: the
        reply stays pending until the call that carries it back. (A compaction inserts as a context
        call does, and then builds.)"""
        self.ask(self.call(C1, [ask("count the rows")]), self.pend(C1),
                 dict(self.call(C1, [ask("count the rows")]), op="context"))
        self.assertEqual(self.rows("SELECT text FROM _pending"), [("There are 42 rows.",)])
        self.ask(self.call(C1, [ask("count the rows"), REPLY, ask("and the columns?")]))
        self.assertEqual(self.rows("SELECT count(*) FROM _pending"), [(0,)])
        self.assertEqual(self.rows("SELECT count(*) FROM events WHERE text = 'There are 42 rows.'"), [(1,)])

    def test_a_pending_event_must_be_one(self):
        answer, = self.ask({"op": "pending", "gatherer": "g", "properties": C1, "events": [{"text": "x"}]})
        self.assertIn("not an event", answer["error"])

    def test_the_manager_reads_them_back(self):
        self.ask(self.call(C1, [ask("count the rows")]), self.pend(C1))
        manager = server_for().manager("g")
        got, = manager.pending("g", properties={"channel": "c1"})
        self.assertEqual((got["type"], got["payload"], got["properties"]),
                         ("agent_message", REPLY, C1))
        self.assertEqual(manager.pending("g", properties={"channel": "c2"}), [])

    def test_a_file_from_before_gets_the_table_with_its_properties(self):
        self.ask(self.call(C1, [ask("count the rows")]))
        conn = sqlite3.connect(paths.db_path("g"))
        conn.execute("DROP TABLE _pending")
        conn.commit()
        schema.create(conn)
        self.assertTrue({"p_channel", "p_cwd"} <= {c[1] for c in conn.execute("PRAGMA table_info(_pending)")})
        conn.close()


class Server:
    """The context manager's server, as the hook sees it: answers what it is asked, recording it."""

    def __init__(self):
        self.asked = []

    async def request(self, op, body=None, timeout=None):
        self.asked.append((op, body))
        if op == "rewrite":
            return {"context": body["events"], "note": "ok", "read_id": len(self.asked), "basis": None}
        if op == "pending":
            return {"kept": len(body["events"])}
        return {}

    async def stop(self):
        pass


def sse(blocks, stop_reason, error=None):
    """An Anthropic Messages stream of `blocks`, ending with `stop_reason`."""
    events = [{"type": "message_start", "message": {"id": "msg_1", "role": "assistant", "content": [],
                                                    "usage": {"input_tokens": 10}}}]
    for i, b in enumerate(blocks):
        if b["type"] == "text":
            events += [{"type": "content_block_start", "index": i, "content_block": {"type": "text", "text": ""}},
                       {"type": "content_block_delta", "index": i, "delta": {"type": "text_delta", "text": b["text"]}}]
        else:
            events += [{"type": "content_block_start", "index": i, "content_block": dict(b, input={})},
                       {"type": "content_block_delta", "index": i,
                        "delta": {"type": "input_json_delta", "partial_json": json.dumps(b["input"])}}]
        events.append({"type": "content_block_stop", "index": i})
    if error:
        events.append({"type": "error", "error": error})
    events += [{"type": "message_delta", "delta": {"stop_reason": stop_reason}, "usage": {"output_tokens": 5}},
               {"type": "message_stop"}]
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


CALL = {"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {"command": "wc -l rows.csv"}}
TEXT = {"type": "text", "text": "There are 42 rows."}


class HookTest(unittest.TestCase):
    def setUp(self):
        self.server = Server()
        self.hook = claude_ag.ClaudeContextManager(ag_clients=AgClients(lambda g: self.server), log=lambda g, l: None,
                                                   count="off")

    def call(self, messages, answer, status=200, headers=None):
        req = SimpleNamespace(method="POST", path="/v1/messages", label="g", limit=None, state={}, upstream=None,
                              headers=dict({"X-Claude-Code-Session-Id": "s"}, **(headers or {})),
                              body={"model": "m", "tools": [{"name": "Bash"}], "messages": messages})

        async def go():
            await self.hook(req)
            await self.hook.answered(req, status, response_of(answer))
        asyncio.run(go())

    def kept(self):
        return [b for op, b in self.server.asked if op == "pending"]

    def test_every_answer_of_the_session_s_own_calls_is_kept(self):
        self.call([ask("count the rows")], sse([CALL], "tool_use"))
        self.call([ask("count the rows")], sse([TEXT], "end_turn"))
        first, second = self.kept()
        self.assertEqual([e["type"] for e in first["events"]], ["tool_call"])
        self.assertEqual([(e["type"], e["text"]) for e in second["events"]], [("agent_message", "There are 42 rows.")])
        self.assertEqual((second["properties"], second["answer"]), ({"channel": "s"}, "msg_1"))
        self.assertEqual((first["stop"], second["stop"]), ("tool_use", "end_turn"))   # why each answer stopped
        self.assertNotIn("id", second["events"][0])                                # not history: no id

    def test_a_failed_answer_is_not_kept(self):
        self.call([ask("count the rows")], sse([TEXT], "end_turn"), status=529)
        self.call([ask("count the rows")], sse([TEXT], "end_turn", error={"type": "overloaded_error"}))
        self.assertEqual(self.kept(), [])

    def test_a_call_the_hook_does_not_answer_for_is_not_kept(self):
        self.call([ask("count the rows")], sse([TEXT], "end_turn"), headers={"X-Claude-Code-Agent-Id": "a1"})
        self.call([ask("count the rows"), ask("[SUGGESTION MODE: next?]")], sse([TEXT], "end_turn"),
                  headers={"X-Claude-Code-Request-Class": "auxiliary"})
        self.assertEqual(self.kept(), [])


RESPONSES = (
    'event: response.completed\ndata: {"type": "response.completed", "response": {"id": "resp_1", "status": '
    '"completed", "output": [{"type": "message", "role": "assistant", "id": "msg_9", "content": [{"type": '
    '"output_text", "text": "There are 42 rows."}]}], "usage": {"input_tokens": 10}}}\n\n').encode()


class CodexHookTest(unittest.TestCase):
    def test_codex_s_answer_is_kept_with_the_thread_s_properties(self):
        from ag.integrations.harnesses.codex.ag_orchestrator import context_manager as codex_ag
        server = Server()
        hook = codex_ag.CodexContextManager(ag_clients=AgClients(lambda g: server), log=lambda g, l: None)
        user = {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "count the rows"}]}
        req = SimpleNamespace(method="POST", path="/v1/responses", label="g", limit=None, state={}, upstream=None,
                              headers={"thread-id": "t1"}, body={"model": "m", "input": [user]})

        async def go(status):
            await hook(req)
            await hook.answered(req, status, response_of(RESPONSES))
        asyncio.run(go(200))
        asyncio.run(go(500))                                                          # failed: not kept
        kept = [b for op, b in server.asked if op == "pending"]
        self.assertEqual(len(kept), 1)
        self.assertEqual((kept[0]["properties"], kept[0]["answer"], kept[0]["stop"]), ({"channel": "t1"}, "resp_1", "completed"))
        self.assertEqual([(e["type"], e["text"]) for e in kept[0]["events"]], [("agent_message", "There are 42 rows.")])


if __name__ == "__main__":
    unittest.main()
