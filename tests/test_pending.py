"""What the model answered that no model call has carried back yet: the proxy hook records each answer of a session's
own call as it comes (`reply_part`, `reply_end`; records.py), and what it says besides the conversation (`derive`).
A reader of the gatherer (the dashboard) sees the reply that ends a turn, which no call carries until the user writes
again, and once a call stores it as conversation, no longer as pending (data.py's `replies`)."""
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
from ag.integrations.tools.hook_server.trace import response_of, streamed_of  # noqa: E402

C1 = {"channel": "c1", "cwd": "/w"}
C2 = {"channel": "c2", "cwd": "/w"}
REPLY = {"role": "assistant", "content": [{"type": "text", "text": "There are 42 rows."}]}


def ask(text):
    return {"role": "user", "content": text}


class Server:
    """The context manager's server, as the hook sees it: answers what it is asked, recording it."""

    def __init__(self):
        self.asked = []

    async def request(self, op, body=None, timeout=None):
        self.asked.append((op, body))
        if op == "rewrite":
            return {"context": body["events"], "note": "ok", "read_id": len(self.asked), "basis": None}
        if op == "insert":
            return {"rows": [None] * len(body["events"])}
        return {}

    def answers(self):
        """What the hook recorded of each answer, by its id, in the order recorded: {parts: the conversation events
        recorded of it, each once; end: its reply_end's payload and properties, None while none; channel}."""
        out = {}
        for op, body in self.asked:
            for e in body["events"] if op == "insert" else []:
                if e["type"] not in ("reply_part", "reply_end"):
                    continue
                a = out.setdefault(e["properties"]["answer_id"], {"parts": {}, "end": None,
                                                                  "channel": body["properties"]["channel"]})
                if e["type"] == "reply_part":
                    a["parts"].setdefault(e["id"], e["payload"])
                else:
                    a["end"] = {**e["payload"], **e["properties"]}
        return [dict(a, parts=list(a["parts"].values())) for a in out.values()]

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

    def call(self, messages, answer, status=200, headers=None, answer_id="msg_1"):
        req = SimpleNamespace(method="POST", path="/v1/messages", label="g", limit=None, state={}, upstream=None,
                              headers=dict({"X-Claude-Code-Session-Id": "s"}, **(headers or {})),
                              body={"model": "m", "tools": [{"name": "Bash"}], "messages": messages})

        async def go():
            await self.hook(req)
            await self.hook.answered(req, status, response_of(answer.replace(b'"msg_1"', f'"{answer_id}"'.encode())))
        asyncio.run(go())

    def test_every_answer_of_the_session_s_own_calls_is_recorded(self):
        self.call([ask("count the rows")], sse([CALL], "tool_use"))
        self.call([ask("count the rows")], sse([TEXT], "end_turn"), answer_id="msg_2")
        first, second = self.server.answers()
        self.assertEqual([e["type"] for e in first["parts"]], ["tool_call"])
        self.assertEqual([(e["type"], e["text"]) for e in second["parts"]], [("agent_message", "There are 42 rows.")])
        self.assertEqual((first["end"]["stop"], second["end"]["stop"]), ("tool_use", "end_turn"))   # why each stopped
        self.assertEqual((second["channel"], second["end"]["answer_id"]), ("s", "msg_2"))
        self.assertNotIn("id", second["parts"][0])                                  # not history: no id of its own

    def test_each_answer_names_the_read_its_call_s_context_came_from(self):
        self.call([ask("count the rows")], sse([CALL], "tool_use"))
        self.call([ask("count the rows")], sse([TEXT], "end_turn"), answer_id="msg_2")
        reads = [i for i, (op, _) in enumerate(self.server.asked, 1) if op == "rewrite"]   # the read_id each was given
        self.assertEqual([a["end"]["read_id"] for a in self.server.answers()], reads)

    def stream(self, messages, *parts):
        """A call whose answer streams: the hook's `streamed` for each of `parts` (the bytes so far)."""
        req = SimpleNamespace(method="POST", path="/v1/messages", label="g", limit=None, state={}, upstream=None,
                              headers={"X-Claude-Code-Session-Id": "s"},
                              body={"model": "m", "tools": [{"name": "Bash"}], "messages": messages})

        async def go():
            await self.hook(req)
            for raw in parts:
                await self.hook.streamed(req, streamed_of(raw))
        asyncio.run(go())

    def test_the_parts_of_an_answer_are_recorded_while_it_streams(self):
        whole = sse([TEXT, CALL], "tool_use")
        cut = whole[:whole.index(b'"content_block_stop", "index": 1')]                # the call still streaming
        self.stream([ask("count the rows")], cut, sse([], "tool_use"))
        kept, = self.server.answers()                                                # no part complete: none kept
        self.assertEqual((kept["channel"], kept["end"]), ("s", None))                 # it streams: no end yet
        self.assertEqual([(e["type"], e["text"]) for e in kept["parts"]], [("agent_message", "There are 42 rows.")])

    def test_a_failed_answer_is_not_recorded(self):
        self.call([ask("count the rows")], sse([TEXT], "end_turn"), status=529)
        self.call([ask("count the rows")], sse([TEXT], "end_turn", error={"type": "overloaded_error"}))
        self.assertEqual(self.server.answers(), [])

    def test_a_call_the_hook_does_not_answer_for_is_not_recorded(self):
        self.call([ask("count the rows")], sse([TEXT], "end_turn"), headers={"X-Claude-Code-Agent-Id": "a1"})
        self.call([ask("count the rows"), ask("[SUGGESTION MODE: next?]")], sse([TEXT], "end_turn"),
                  headers={"X-Claude-Code-Request-Class": "auxiliary"})
        self.assertEqual(self.server.answers(), [])


class DerivedTest(unittest.TestCase):
    """What an answer asks the user, and what a call's new pieces say of it and of background tasks, recorded beside the
    session's reads, each once by the harness's own ids (proxy_hook.py's `derive`)."""

    def test_an_ask_its_result_and_a_task_started(self):
        server = Server()
        hook = claude_ag.ClaudeContextManager(ag_clients=AgClients(lambda g: server), log=lambda g, l: None, count="off")
        asks = {"type": "tool_use", "id": "toolu_q", "name": "AskUserQuestion",
                "input": {"questions": [{"question": "Which?", "options": [{"label": "A"}, {"label": "B"}]}]}}

        def call(messages, answer):
            req = SimpleNamespace(method="POST", path="/v1/messages", label="g", limit=None, state={}, upstream=None,
                                  headers={"X-Claude-Code-Session-Id": "s"},
                                  body={"model": "m", "tools": [{"name": "Bash"}], "messages": messages})

            async def go():
                await hook(req)
                await hook.answered(req, 200, response_of(answer))
                await asyncio.gather(*list(hook.under_way))
            asyncio.run(go())

        call([ask("pick one")], sse([asks], "tool_use"))
        call([ask("pick one"), {"role": "assistant", "content": [asks, dict(CALL, id="toolu_b", input={
                  "command": "sleep 99", "description": "Wait", "run_in_background": True})]},
              {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_q", "content": '"Which?"="B"'},
                                           {"type": "tool_result", "tool_use_id": "toolu_b",
                                            "content": "Command running in background with ID: b1. Output is being "
                                                       "written to: /tmp/b1.output"}]}], sse([TEXT], "end_turn"))
        inserted = [(e["type"], e["id"], body.get("lane")) for op, body in server.asked if op == "insert"
                    for e in body["events"] if e["type"] in ("asked", "ask_settled", "task_started")]
        self.assertEqual(inserted, [("asked", "asked:toolu_q", "records"), ("ask_settled", "ask_settled:toolu_q", "records"),
                                    ("task_started", "task_started:b1.toolu_b", "records")])
        calls = [e["payload"] for op, body in server.asked if op == "insert" for e in body["events"] if e["type"] == "model_call"]
        self.assertTrue(calls and all(c.get("derives") for c in calls))         # a reader may take none recorded as none


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
        kept, = server.answers()
        self.assertEqual((kept["channel"], kept["end"]["answer_id"], kept["end"]["stop"]), ("t1", "resp_1", "completed"))
        self.assertEqual(kept["end"]["read_id"], [i for i, (op, _) in enumerate(server.asked, 1) if op == "rewrite"][0])
        self.assertEqual([(e["type"], e["text"]) for e in kept["parts"]], [("agent_message", "There are 42 rows.")])

    def test_codex_s_output_items_are_kept_as_each_is_done(self):
        from ag.integrations.harnesses.codex.ag_orchestrator import context_manager as codex_ag
        server = Server()
        hook = codex_ag.CodexContextManager(ag_clients=AgClients(lambda g: server), log=lambda g, l: None)
        user = {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "count the rows"}]}
        req = SimpleNamespace(method="POST", path="/v1/responses", label="g", limit=None, state={}, upstream=None,
                              headers={"thread-id": "t1"}, body={"model": "m", "input": [user]})
        said = {"type": "message", "role": "assistant", "id": "msg_9", "content": [{"type": "output_text", "text": "Counting."}]}
        so_far = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in [
            {"type": "response.created", "response": {"id": "resp_1", "status": "in_progress"}},
            {"type": "response.output_item.done", "output_index": 0, "item": said},
            {"type": "response.output_item.added", "output_index": 1, "item": {"type": "function_call", "name": "shell"}}])

        async def go():
            await hook(req)
            await hook.streamed(req, streamed_of(so_far.encode()))
        asyncio.run(go())
        kept, = server.answers()
        self.assertEqual(kept["end"], None)                                           # it streams
        self.assertEqual([(e["type"], e["text"]) for e in kept["parts"]], [("agent_message", "Counting.")])


if __name__ == "__main__":
    unittest.main()
