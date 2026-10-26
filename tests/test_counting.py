"""Claude's own counts of Claude Code's calls (ag/integrations/harnesses/claude/ag_orchestrator/
counting.py), against a stand-in for the API's count_tokens whose every count is known: each block
costs what its content says, each message 2 more, and a thinking block counts only after a history
the model wrote it in -- here, when no `SUMMARY` (a build's section) comes before it. And the
server's `counted`, which sets the counts in place of the tokenizer's."""
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

try:
    from aiohttp import web
    from aiohttp.test_utils import TestServer
except ImportError:
    web = None

from ag.ag_harness import home as ag_home  # noqa: E402
from ag.ag_harness.server import serve  # noqa: E402
from ag.ag_harness.server.__main__ import server_for  # noqa: E402
from ag.ag_harness.manager import Manager  # noqa: E402
from ag.ag_harness.store import operations as store_ops  # noqa: E402
from ag.ag_harness.store import paths  # noqa: E402
from ag.ag_interface.policy import Context  # noqa: E402
from ag.ag_interface.store import Ref  # noqa: E402
from ag.integrations.harnesses.claude.adaptor import to_events as claude  # noqa: E402
from ag.integrations.harnesses.claude.ag_orchestrator import context_manager as claude_ag  # noqa: E402
from ag.integrations.harnesses.claude.ag_orchestrator.counting import Counter, fresh_thinking  # noqa: E402
from ag.integrations.harnesses.codex.ag_orchestrator.ag_clients import AgClients  # noqa: E402
from ag.integrations.harnesses.codex.adaptor import to_events as codex  # noqa: E402

SYSTEM, TOOLS = "You are Claude Code." * 4, [{"name": "Bash", "input_schema": {"type": "object"}}]
THINK = {"type": "thinking", "thinking": "", "signature": "sig-1"}


def cost(block) -> int:
    """The stand-in's price of a block (thinking aside)."""
    kind = block.get("type")
    if kind == "text":
        return len(block["text"]) // 4 + 1
    if kind == "tool_use":
        return len(json.dumps(block.get("input"))) // 4 + 3
    if kind == "tool_result":
        content = block.get("content")
        return len(content if isinstance(content, str) else json.dumps(content)) // 4 + 2
    return len(json.dumps(block)) // 4


def price(body) -> int:
    """The stand-in's count of a whole request."""
    n = 10 + (len(json.dumps(body["system"])) // 4 if body.get("system") else 0) \
        + (len(json.dumps(body["tools"])) // 4 if body.get("tools") else 0)
    summarized = False
    for m in body["messages"]:
        n += 2
        content = m["content"] if isinstance(m["content"], list) else [{"type": "text", "text": m["content"]}]
        for b in content:
            if b.get("type") == "text" and "SUMMARY" in b["text"]:
                summarized = True
            n += (0 if summarized else 50) if b.get("type") == "thinking" else cost(b)
    return n


def turn():
    """A user's request, the agent's thinking, words and tool call, the result, the next request."""
    return [{"role": "user", "content": "count the rows"},
            {"role": "assistant", "content": [THINK, {"type": "text", "text": "Checking."},
                                              {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "wc -l t"}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "42 rows in the table"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "There are 42 rows."}]},
            {"role": "user", "content": [{"type": "text", "text": "And the columns?", "cache_control": {"type": "ephemeral"}}]}]


class Client:
    def __init__(self):
        self.asked = []

    async def request(self, op, body=None, timeout=None):
        if op == "latest":                   # a gatherer with nothing stored yet
            return {"events": []}
        self.asked.append((op, body))
        return {}


@unittest.skipIf(web is None, "the hook server needs aiohttp")
class CounterTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.asked = []

        async def count_tokens(req):
            body = await req.json()
            self.asked.append(body)
            return web.json_response({"input_tokens": price(body)})

        app = web.Application()
        app.router.add_post("/v1/messages/count_tokens", count_tokens)
        self.upstream = TestServer(app)
        await self.upstream.start_server()
        self.request = SimpleNamespace(path="/v1/messages", upstream=str(self.upstream.make_url("")).rstrip("/"),
                                       headers={"Authorization": "Bearer t"})

    async def asyncTearDown(self):
        await self.upstream.close()

    async def run_call(self, counter, messages, sent=None, ag_items=(), **out):
        client = Client()
        body = {"model": "m", "system": SYSTEM, "tools": TOOLS, "messages": messages}
        await counter.count_call(self.request, client, "g", {"channel": "c"}, body, messages,
                                 sent if sent is not None else messages,
                                 dict({"events": claude.to_events(messages), "ag_items": list(ag_items)}, **out))
        return client.asked[0][1] if client.asked else None

    async def test_every_event_counted_and_together_the_whole_request(self):
        messages = turn()
        events = claude.to_events(messages)
        sent = await self.run_call(Counter(), messages)
        self.assertEqual(set(sent["counts"]), {e["id"] for e in events})            # thinking too
        thinking = next(e["id"] for e in events if e["type"] == claude.AGENT_REASONING)
        self.assertEqual(sent["counts"][thinking], 50)
        preamble = sum(p["tokens"] for p in sent["preamble_counts"])
        whole = price({"system": SYSTEM, "tools": TOOLS, "messages": messages})
        self.assertEqual(preamble + sum(sent["counts"].values()), whole - 10)       # all but the count's own

    async def test_a_block_s_count_is_what_it_costs(self):
        messages = turn()
        events = {e["payload"]["content"][0].get("text") or e["payload"]["content"][0].get("type"): e["id"]
                  for e in claude.to_events(messages)}
        sent = await self.run_call(Counter(), messages)
        result = {"type": "tool_result", "tool_use_id": "t1", "content": "42 rows in the table"}
        self.assertEqual(sent["counts"][events["tool_result"]], cost(result) - cost({"type": "tool_result", "content": "x"}) + 1)
        self.assertEqual(sent["counts"][events["Checking."]], cost({"type": "text", "text": "Checking."}))
        self.assertEqual(sent["counts"][events["There are 42 rows."]], cost({"type": "text", "text": "There are 42 rows."}) + 2)

    async def test_what_was_counted_is_not_counted_again(self):
        counter, messages = Counter(), turn()
        await self.run_call(counter, messages)
        more = messages + [{"role": "assistant", "content": [{"type": "text", "text": "Three columns."}]},
                           {"role": "user", "content": "Thanks."}]
        sent = await self.run_call(counter, more)
        new = {e["id"] for e in claude.to_events(more)} - {e["id"] for e in claude.to_events(messages)}
        self.assertEqual(set(sent["counts"]), new)
        self.assertEqual(sent["preamble_counts"], [])                               # once per version

    async def test_started_again_it_counts_only_what_the_store_has_not(self):
        messages = turn()
        events = claude.to_events(messages)
        context = [dict(e, tokens=50 if e["type"] == claude.AGENT_REASONING else 1, counted=True) for e in events]
        sent = await self.run_call(Counter(), messages, context=context, uncounted=[])   # a new process: all counted
        self.assertEqual(sent["counts"] if sent else {}, {})
        last = events[-1]["id"]
        context[-1] = dict(context[-1], counted=False)
        sent = await self.run_call(Counter(), messages, context=context, uncounted=[last])
        self.assertEqual(set(sent["counts"]), {last})

    async def test_started_again_it_takes_the_thinking_s_cost_from_the_store(self):
        later = turn() + [{"role": "assistant", "content": [{"type": "thinking", "thinking": "", "signature": "sig-9"},
                                                            {"type": "text", "text": "Five."}]},
                          {"role": "user", "content": "Thanks."}]
        events = claude.to_events(later)
        first, ninth = [e["id"] for e in events if e["type"] == claude.AGENT_REASONING]
        context = [dict(e, tokens=50, counted=True) if e["id"] == first else dict(e, tokens=1, counted=False)
                   for e in events]
        sent = await self.run_call(Counter(), later, context=context, uncounted=[])
        self.assertEqual(sent["counts"], {ninth: 50})          # the new block alone, at its own cost

    async def test_ag_s_own_items_once_per_text(self):
        counter = Counter()
        sent = await self.run_call(counter, turn(), ag_items=[(7, "SUMMARY of earlier tasks")])
        self.assertEqual(sent["made"], {"7": cost({"type": "text", "text": "SUMMARY of earlier tasks"}) + 2})
        before = len(self.asked)
        sent = await self.run_call(counter, turn(), ag_items=[(8, "SUMMARY of earlier tasks")])
        self.assertEqual(sent["made"], {"8": cost({"type": "text", "text": "SUMMARY of earlier tasks"}) + 2})
        self.assertFalse(any("SUMMARY" in json.dumps(b) for b in self.asked[before:]))   # not asked again

    async def test_a_step_the_api_will_not_take_alone_is_counted_in_the_history(self):
        refused = {"role": "system", "content": [{"type": "text", "text": "gone"}]}

        async def count_tokens(req):
            body = await req.json()
            if body["messages"][:1] == [{"role": "user", "content": [{"type": "text", "text": "x"}]}] \
                    and refused in body["messages"]:
                return web.json_response({"error": {"message": "references unknown tool"}}, status=400)
            return web.json_response({"input_tokens": price(body)})

        app = web.Application()
        app.router.add_post("/v1/messages/count_tokens", count_tokens)
        server = TestServer(app)
        await server.start_server()
        self.request.upstream = str(server.make_url("")).rstrip("/")
        messages = turn()[:1] + [refused] + turn()[1:]
        events = claude.to_events(messages)
        sent = await self.run_call(Counter(), messages)
        gone = next(e["id"] for e in events if e["payload"] == {"role": "system", "content": [refused["content"][0]]})
        self.assertEqual(sent["counts"][gone], cost(refused["content"][0]) + 2)
        await server.close()


class FreshThinkingTest(unittest.TestCase):
    """The thinking from before a build is left out, as the server marks the context: nothing is
    remembered by the hook, so a hook started again leaves out what the last one did."""

    def history(self, tool_loop=False):
        out = [{"role": "system", "content": [{"type": "text", "text": "SUMMARY"}]}] + turn()[:4]
        if tool_loop:
            out += [{"role": "user", "content": "go on"},
                    {"role": "assistant", "content": [{"type": "thinking", "thinking": "", "signature": "sig-2"},
                                                      {"type": "tool_use", "id": "t2", "name": "Bash", "input": {}}]},
                    {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t2", "content": "ok"}]}]
        return out

    def context(self, messages, opens, tokens=None):
        """The server's context for `messages`: an ag item for the summary, each piece a stored event with
        its id, the events before the piece at `opens` (an index into the pieces) marked before the basis
        and that one as opening it -- None: no basis."""
        out = []
        for i, e in enumerate(claude.to_events(messages[1:])):
            event = dict(e, tokens=(tokens or {}).get(i, 5), counted=True)
            if opens is not None and i <= opens:
                event["before_basis" if i < opens else "opens_basis"] = True
            out.append(event)
        return [{"type": "ag", "name": "earlier", "text": "SUMMARY", "made_id": 1}] + out

    def piece(self, messages, match):
        return next(i for i, e in enumerate(claude.to_events(messages[1:])) if match(e["payload"]))

    def signatures(self, messages):
        return [b.get("signature") for m in messages for b in (m["content"] if isinstance(m["content"], list) else [])
                if b.get("type") == "thinking"]

    def test_none_under_the_history_itself(self):
        messages = self.history()
        self.assertEqual(fresh_thinking(self.context(messages, None), messages), (messages, {}))

    def test_the_thinking_before_the_switch_is_left_out_and_after_it_kept(self):
        later = self.history() + [{"role": "user", "content": "more"},
                                  {"role": "assistant", "content": [{"type": "thinking", "thinking": "", "signature": "sig-3"},
                                                                    {"type": "text", "text": "ok"}]},
                                  {"role": "user", "content": "and?"}]
        opens = self.piece(later, lambda p: p.get("content") == [{"type": "text", "text": "more"}])
        out, gone = fresh_thinking(self.context(later, opens), later)
        self.assertEqual(self.signatures(out), ["sig-3"])                              # made after it

    def test_a_tool_loop_keeps_its_own_turn_s_thinking(self):
        messages = self.history(tool_loop=True)
        opens = self.piece(messages, lambda p: p["content"][0].get("type") == "tool_result" and
                           p["content"][0]["tool_use_id"] == "t2")
        out, _ = fresh_thinking(self.context(messages, opens), messages)
        self.assertEqual(self.signatures(out), ["sig-2"])

    def test_the_tool_loop_s_thinking_stays_once_its_turn_is_over(self):
        messages = self.history(tool_loop=True)
        opens = self.piece(messages, lambda p: p["content"][0].get("type") == "tool_result" and
                           p["content"][0]["tool_use_id"] == "t2")
        later = messages + [{"role": "assistant", "content": [{"type": "text", "text": "Done."}]},
                            {"role": "user", "content": "next"}]
        out, _ = fresh_thinking(self.context(later, opens), later)
        self.assertEqual(self.signatures(out), ["sig-2"])                    # sent from the switch: sent after it

    def test_what_it_leaves_out_is_what_the_store_has_it_at(self):
        messages = self.history() + [{"role": "user", "content": "more"}]
        opens = len(claude.to_events(messages[1:])) - 1
        thinking = self.piece(messages, lambda p: p["content"][0].get("type") == "thinking")
        _, gone = fresh_thinking(self.context(messages, opens, {thinking: 120}), messages)
        event = claude.to_events(messages[1:])[thinking]["id"]
        self.assertEqual(gone, {event: 120})
        _, gone = fresh_thinking(self.context(messages, opens, {thinking: 0}), messages)   # since set to 0
        self.assertEqual(sum(gone.values()), 0)


@unittest.skipIf(web is None, "the hook server needs aiohttp")
class HookTest(unittest.IsolatedAsyncioTestCase):
    """The hook: counts after the call; the rule before it."""

    async def asyncSetUp(self):
        async def count_tokens(req):
            return web.json_response({"input_tokens": price(await req.json())})
        app = web.Application()
        app.router.add_post("/v1/messages/count_tokens", count_tokens)
        self.upstream = TestServer(app)
        await self.upstream.start_server()

    async def asyncTearDown(self):
        await self.upstream.close()

    async def test_the_call_is_sent_then_counted(self):
        class Server:
            def __init__(self):
                self.asked = []

            async def request(self, op, body=None, timeout=None):
                if op == "latest":                   # a gatherer with nothing stored yet
                    return {"events": []}
                self.asked.append((op, body))
                if op != "rewrite":
                    return {}
                events = [dict(e, before_basis=True) for e in body["events"][:-1]] + \
                    [dict(e, opens_basis=True) for e in body["events"][-1:]]      # the first read of build 1
                ctx = [{"type": "ag", "name": "earlier", "text": "SUMMARY", "made_id": 3}] + events
                return {"context": ctx, "note": "ok", "read_id": 1, "basis": "1", "tokens": 10, "budget": 100000,
                        "sent_tokens": 10}

            async def stop(self):
                pass

        server = Server()
        hook = claude_ag.ClaudeContextManager(ag_clients=AgClients(lambda g: server), log=lambda g, l: None)
        req = SimpleNamespace(method="POST", path="/v1/messages", label="g", upstream=str(self.upstream.make_url("")).rstrip("/"),
                              headers={"X-Claude-Code-Session-Id": "s"}, limit=None, state={},
                              body={"model": "m", "system": SYSTEM, "tools": TOOLS, "messages": turn()})
        out = await hook(req)
        thinking = [b for m in out["messages"] for b in (m["content"] if isinstance(m["content"], list) else [])
                    if b.get("type") == "thinking"]
        self.assertEqual(thinking, [])                       # under a build: the thinking from before it, out
        await hook.counter.close()
        ops = [op for op, _ in server.asked]
        self.assertEqual(ops, ["rewrite", "counted"])
        counted = server.asked[1][1]
        self.assertEqual(counted["made"], {"3": cost({"type": "text", "text": "SUMMARY"}) + 2})
        self.assertEqual(counted["properties"], {"channel": "s"})


    async def test_a_hook_started_again_keeps_the_thinking_from_after_the_switch(self):
        class Server:
            def __init__(self):
                self.asked = []

            async def request(self, op, body=None, timeout=None):
                if op == "latest":                   # a gatherer with nothing stored yet
                    return {"events": []}
                self.asked.append((op, body))
                if op != "rewrite":
                    return {}
                events = [dict(e, opens_basis=True) if i == 0 else e for i, e in enumerate(body["events"])]
                return {"context": events, "note": "ok", "read_id": 9, "basis": "1", "tokens": 10, "budget": 100000,
                        "sent_tokens": 10, "uncounted": []}      # build 1 since the first message: none before it

            async def stop(self):
                pass

        later = turn() + [{"role": "assistant", "content": [{"type": "thinking", "thinking": "", "signature": "sig-2"},
                                                            {"type": "text", "text": "Five."}]},
                          {"role": "user", "content": "Thanks."}]
        for _ in range(2):                                     # a hook, then one started again
            server = Server()
            hook = claude_ag.ClaudeContextManager(ag_clients=AgClients(lambda g: server), log=lambda g, l: None)
            req = SimpleNamespace(method="POST", path="/v1/messages", label="g",
                                  upstream=str(self.upstream.make_url("")).rstrip("/"),
                                  headers={"X-Claude-Code-Session-Id": "s"}, limit=None, state={},
                                  body={"model": "m", "system": SYSTEM, "tools": TOOLS, "messages": later})
            out = await hook(req)
            await hook.counter.close()
            sent = out["messages"] if out else later
            thinking = [b["signature"] for m in sent for b in (m["content"] if isinstance(m["content"], list) else [])
                        if b.get("type") == "thinking"]
            self.assertEqual(thinking, ["sig-1", "sig-2"])
            counted = [b for op, b in server.asked if op == "counted"]
            self.assertFalse(any(b.get("left_out") for b in counted))


class ServerTest(unittest.TestCase):
    """`counted` sets the provider's counts in place of the tokenizer's, and the reads size by them."""

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

    def test_counts_replace_the_tokenizer_s(self):
        user = {"type": "message", "role": "user", "id": "u1", "content": [{"type": "input_text", "text": "hi there"}]}
        events = codex.to_events([user])
        pre = [{"name": "instructions", "text": "You are codex."}]
        first, = self.ask({"op": "rewrite", "gatherer": "s", "properties": {"channel": "c"}, "events": events, "preamble": pre})
        stored = [e["id"] for e in events if e.get("id")]
        found, = self.ask({"op": "counted", "gatherer": "s", "properties": {"channel": "c"},
                           "counts": {i: 1000 for i in stored}, "preamble_counts": [dict(pre[0], tokens=500)]})
        self.assertEqual(found, {"id": 1, "events": len(stored), "made": 0, "preamble": 1})
        again, = self.ask({"op": "rewrite", "gatherer": "s", "properties": {"channel": "c"}, "events": events, "preamble": pre})
        conn = sqlite3.connect(paths.db_path("s"))                  # the gatherer guide, by ag's count: not counted
        guide, = conn.execute("SELECT tokens FROM _made_items WHERE name = 'gatherer_guide'").fetchone()
        conn.close()
        self.assertEqual(again["sent_tokens"], 1000 * len(stored) + 500 + guide)
        self.assertGreater(again["sent_tokens"], first["sent_tokens"])
        other, = self.ask({"op": "counted", "gatherer": "s", "properties": {"channel": "elsewhere"},
                           "counts": {i: 7 for i in stored}})
        self.assertEqual(other["events"], 0)                  # another channel's are not touched

    def test_a_read_answers_each_event_s_size_and_those_the_provider_has_not_counted(self):
        events = codex.to_events([{"type": "message", "role": "user", "id": "u1",
                                   "content": [{"type": "input_text", "text": "hi there"}]}])
        stored = [e["id"] for e in events if e.get("id")]
        first, = self.ask({"op": "rewrite", "gatherer": "s", "properties": {"channel": "c"}, "events": events})
        self.assertEqual(sorted(first["uncounted"]), sorted(stored))
        mine = [e for e in first["context"] if e.get("id") in stored]
        self.assertTrue(mine and all(e["counted"] is False and e["tokens"] > 0 for e in mine))
        self.ask({"op": "counted", "gatherer": "s", "properties": {"channel": "c"}, "counts": {i: 1000 for i in stored}})
        again, = self.ask({"op": "rewrite", "gatherer": "s", "properties": {"channel": "c"}, "events": events})
        self.assertEqual(again["uncounted"], [])
        self.assertTrue(all(e["counted"] is True and e["tokens"] == 1000 for e in again["context"] if e.get("id") in stored))
        other, = self.ask({"op": "rewrite", "gatherer": "s", "properties": {"channel": "elsewhere"}, "events": events})
        self.assertEqual(sorted(other["uncounted"]), sorted(stored))       # another channel's events are its own

    def test_the_switch_to_a_basis_is_the_event_its_first_read_responded_to(self):
        self.ask({"op": "rewrite", "gatherer": "s", "properties": {"channel": "c"},
                  "events": codex.to_events([{"type": "message", "role": "user", "id": "u1",
                                              "content": [{"type": "input_text", "text": "hi"}]}])})
        conn = sqlite3.connect(paths.db_path("s"))
        for row, basis in ((10, None), (20, "5"), (30, "5")):
            store_ops.record_read(conn, {"channel": "c"}, [], manager="m", basis=basis, row_id=row)
        store_ops.record_read(conn, {"channel": "d"}, [], manager="m", basis="5", row_id=25)
        self.assertEqual(store_ops.basis_opened(conn, {"channel": "c"}, "5"), 20)      # not 30, nor d's
        self.assertIsNone(store_ops.basis_opened(conn, {"channel": "c"}, None))
        store_ops.record_read(conn, {"channel": "c"}, [], manager="m", basis="6", row_id=40)
        self.assertEqual(store_ops.basis_opened(conn, {"channel": "c"}, "6"), 40)
        self.assertIsNone(store_ops.basis_opened(conn, {"channel": "c"}, "5"))         # no longer its basis
        store_ops.record_read(conn, {"channel": "c"}, [], manager="m", basis="6", row_id=50)
        self.assertEqual(store_ops.basis_opened(conn, {"channel": "c"}, "6"), 40)      # still: a restart changes nothing
        conn.close()

    def test_the_context_marks_the_events_before_its_switch(self):
        events = claude.to_events(turn())
        self.ask({"op": "rewrite", "gatherer": "s", "properties": {"channel": "c"}, "events": events})
        conn = sqlite3.connect(paths.db_path("s"))
        rows = [r for (r,) in conn.execute("SELECT row_id FROM events WHERE p_channel = 'c' ORDER BY row_id")]
        ctx = Context(items=[{}] * len(rows), refs=[Ref(r) for r in rows], basis="5")
        out = Manager.as_events(conn, ctx, opened=rows[2])
        conn.close()
        self.assertEqual([bool(e.get("before_basis")) for e in out], [True, True] + [False] * (len(rows) - 2))
        self.assertEqual([bool(e.get("opens_basis")) for e in out], [False, False, True] + [False] * (len(rows) - 3))
        self.assertEqual([e["id"] for e in out], [e["id"] for e in events])

    def test_the_read_log_keeps_what_each_call_sent_as_counted_then(self):
        user = {"type": "message", "role": "user", "id": "u1", "content": [{"type": "input_text", "text": "hi there"}]}
        events = codex.to_events([user])
        first, = self.ask({"op": "rewrite", "gatherer": "s", "properties": {"channel": "c"}, "events": events})
        stored = [e["id"] for e in events if e.get("id")]
        self.ask({"op": "counted", "gatherer": "s", "properties": {"channel": "c"}, "counts": {i: 1000 for i in stored},
                  "left_out": {str(first["read_id"]): 3}})
        second, = self.ask({"op": "rewrite", "gatherer": "s", "properties": {"channel": "c"}, "events": events})
        conn = sqlite3.connect(paths.db_path("s"))
        sent = dict(conn.execute("SELECT read_id, sent_tokens FROM _reads"))
        conn.close()
        self.assertEqual(sent[first["read_id"]], first["sent_tokens"] - 3)    # as counted then, less what was left out
        self.assertEqual(sent[second["read_id"]], second["sent_tokens"])     # with the counts set since
        self.assertNotEqual(sent[first["read_id"]], sent[second["read_id"]])


if __name__ == "__main__":
    unittest.main()
