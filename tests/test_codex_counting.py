"""The provider's own counts of codex's calls (ag/integrations/harnesses/codex/ag_orchestrator/counting.py),
against a stand-in for OpenAI's /v1/responses/input_tokens whose every count is known: each item costs
what its content says, and 2 more; a tool output refuses to be counted without its call; and codex's
encrypted reasoning counts as nothing, as the API counts a ChatGPT login's. The call's own count (its
reported input tokens) does count the reasoning: what the endpoint falls short of it by is the reasoning's.
Without the endpoint, the calls' own counts are differenced. And the hook: counted before sending near
the budget, counted after."""
import asyncio
import json
import os
import sys
import unittest
import unittest.mock
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from aiohttp import web
    from aiohttp.test_utils import TestServer
except ImportError:
    web = None

from ag.integrations.harnesses.codex.adaptor import to_events as codex  # noqa: E402
from ag.integrations.harnesses.codex.ag_orchestrator import context_manager as codex_ag  # noqa: E402
from ag.integrations.harnesses.codex.ag_orchestrator import counting  # noqa: E402
from ag.integrations.harnesses.codex.ag_orchestrator.ag_clients import AgClients  # noqa: E402
from ag.integrations.harnesses.codex.ag_orchestrator.counting import Counter  # noqa: E402
from ag.integrations.harnesses.codex.adaptor.adaptor import CodexAdaptor  # noqa: E402
from ag.integrations.harnesses.codex.adaptor.to_messages import ag_message  # noqa: E402

REASONING_COST = 40          # what a reasoning item costs the call itself (its own count), not the endpoint


def cost(item) -> int:
    """The stand-in's price of an item, its framing (2) with it; reasoning, 0."""
    kind = item.get("type")
    if kind == "reasoning":
        return 0
    if kind == "message":
        return 2 + sum(len(p.get("text", "")) // 4 + 1 for p in item.get("content") or [])
    if kind in ("function_call", "custom_tool_call"):
        return 2 + len(item.get("arguments") or item.get("input") or "") // 4 + 3
    if kind in ("function_call_output", "custom_tool_call_output"):
        out = item.get("output")
        return 2 + len(out if isinstance(out, str) else json.dumps(out)) // 4 + 2
    return 2 + len(json.dumps(item)) // 4


def price(body) -> int:
    """The stand-in endpoint's count of a request; a ValueError for an output with no call before it."""
    seen = set()
    for item in body["input"]:
        if item.get("type", "").endswith("_output") and item.get("call_id") not in seen:
            raise ValueError(f"No tool call found for output with call_id {item.get('call_id')}")
        if item.get("call_id"):
            seen.add(item["call_id"])
    return 10 + (len(body["instructions"]) // 4 if body.get("instructions") else 0) \
        + (len(json.dumps(body["tools"])) // 4 if body.get("tools") else 0) + sum(cost(i) for i in body["input"])


def own_count(body) -> int:
    """What the call itself reports: the endpoint's count, and each reasoning item it sends."""
    return price(body) + REASONING_COST * sum(1 for i in body["input"] if i.get("type") == "reasoning")


def user(text, n):
    return {"type": "message", "role": "user", "id": f"u{n}", "content": [{"type": "input_text", "text": text}]}


def turn():
    """Codex's tool definitions, a request, the model's reasoning and tool call, the output, its reply,
    the next request."""
    return [{"type": "additional_tools", "id": "at1", "role": "developer", "tools": [{"name": "exec", "type": "custom"}]},
            user("count the rows", 1),
            {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "gAAAA" * 40},
            {"type": "function_call", "id": "fc_1", "call_id": "c1", "name": "exec_command",
             "arguments": json.dumps({"cmd": "wc -l t"})},
            {"type": "function_call_output", "call_id": "c1", "output": "42 rows in the table"},
            {"type": "message", "role": "assistant", "id": "msg_1", "content": [{"type": "output_text", "text": "There are 42 rows."}]},
            user("And the columns?", 2)]


def body_of(items, model="gpt-6-luna"):
    return {"model": model, "input": items, "reasoning": {"effort": "low", "context": "all_turns"}, "stream": True,
            "store": False, "include": ["reasoning.encrypted_content"], "prompt_cache_key": "t"}


class Client:
    def __init__(self):
        self.asked = []

    async def request(self, op, body=None, timeout=None):
        self.asked.append((op, body))
        return {}


@unittest.skipIf(web is None, "the hook server needs aiohttp")
class Base(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.asked, self.unknown_models = [], set()

        async def input_tokens(req):
            body = await req.json()
            self.asked.append((dict(req.headers), body))
            if body.get("model") in self.unknown_models:
                return web.json_response({"error": {"message": f"The model `{body['model']}` does not exist",
                                                     "code": "model_not_found"}}, status=404)
            try:
                return web.json_response({"object": "response.input_tokens", "input_tokens": price(body)})
            except ValueError as exc:
                return web.json_response({"error": {"message": str(exc)}}, status=400)

        app = web.Application()
        app.router.add_post("/v1/responses/input_tokens", input_tokens)
        self.upstream = TestServer(app)
        await self.upstream.start_server()
        self.url = str(self.upstream.make_url("")).rstrip("/")
        self.request = SimpleNamespace(path="/v1/responses", upstream=self.url, headers={"Authorization": "Bearer k"})

    async def asyncTearDown(self):
        await self.upstream.close()

    async def run_call(self, counter, items, sent=None, ag_items=(), read_id=1):
        client = Client()
        sent = items if sent is None else sent
        out = {"events": codex.to_events(items), "ag_items": list(ag_items), "read_id": read_id, "basis": None}
        counter.sent("g", "c", out, sent, [])
        counter.start(self.request, client, "g", {"channel": "c"}, body_of(items), items, sent, out)
        await counter.close()
        return client, client.asked[0][1] if client.asked else None


class CounterTest(Base):
    async def test_every_event_but_reasoning_counted_and_together_the_whole_request(self):
        items = turn()
        _, sent = await self.run_call(Counter(CodexAdaptor()), items)
        events = codex.to_events(items)
        self.assertEqual(set(sent["counts"]), {e["id"] for e in events if e["type"] != codex.AGENT_REASONING})
        self.assertEqual(sum(sent["counts"].values()), price(body_of(items)) - 10)       # all but the count's own
        self.assertEqual(sent["preamble_counts"], [])            # codex's tools are an item: an event's count

    async def test_an_item_s_count_is_what_it_costs(self):
        items = turn()
        _, sent = await self.run_call(Counter(CodexAdaptor()), items)
        output = items[4]
        self.assertEqual(sent["counts"][codex.item_id(output)], cost(output) - cost(dict(output, output="x")) + 1)
        self.assertEqual(sent["counts"]["msg_1"], cost(items[5]))
        self.assertEqual(sent["counts"]["at1"], cost(items[0]))
        self.assertEqual(sent["counts"]["fc_1"] + sent["counts"][codex.item_id(output)],
                         cost(items[3]) + cost(output))         # the call, what is left of its step

    async def test_what_was_counted_is_not_counted_again(self):
        counter, items = Counter(CodexAdaptor()), turn()
        await self.run_call(counter, items)
        more = items + [{"type": "message", "role": "assistant", "id": "msg_2",
                         "content": [{"type": "output_text", "text": "Three columns."}]}, user("Thanks.", 3)]
        _, sent = await self.run_call(counter, more, read_id=2)
        self.assertEqual(set(sent["counts"]), {"msg_2", "u3"})

    async def test_ag_s_own_items_once_per_text_as_they_are_sent(self):
        counter = Counter(CodexAdaptor())
        _, sent = await self.run_call(counter, turn(), ag_items=[(7, "SUMMARY of earlier tasks")])
        self.assertEqual(sent["made"], {"7": cost(ag_message("SUMMARY of earlier tasks"))})
        before = len(self.asked)
        _, sent = await self.run_call(counter, turn(), ag_items=[(8, "SUMMARY of earlier tasks")], read_id=2)
        self.assertEqual(sent["made"], {"8": cost(ag_message("SUMMARY of earlier tasks"))})
        self.assertFalse(any("SUMMARY" in json.dumps(b) for _, b in self.asked[before:] if b["input"] != turn()))

    async def test_a_step_the_endpoint_will_not_take_alone_is_counted_in_the_history(self):
        refused = {"type": "message", "role": "developer", "id": "d9", "content": [{"type": "input_text", "text": "gone"}]}

        async def input_tokens(req):
            body = await req.json()
            if body["input"][:1] == counting.PLACEHOLDER and refused in body["input"]:
                return web.json_response({"error": {"message": "references an item since gone"}}, status=400)
            return web.json_response({"input_tokens": price(body)})

        app = web.Application()
        app.router.add_post("/v1/responses/input_tokens", input_tokens)
        server = TestServer(app)
        await server.start_server()
        self.request.upstream = str(server.make_url("")).rstrip("/")
        items = turn()[:2] + [refused] + turn()[2:]
        _, sent = await self.run_call(Counter(CodexAdaptor()), items)
        self.assertEqual(sent["counts"]["d9"], cost(refused))
        await server.close()

    async def test_counted_where_codex_s_calls_go_with_their_credentials(self):
        await self.run_call(Counter(CodexAdaptor()), turn())
        headers, body = self.asked[0]
        self.assertEqual(headers.get("Authorization"), "Bearer k")
        self.assertEqual(sorted(body), ["input", "model", "reasoning"])      # not stream, store, include, ...

    async def test_under_a_chatgpt_login_the_api_is_asked_with_the_key_it_has(self):
        self.request = SimpleNamespace(path="/backend-api/codex/responses", upstream="https://chatgpt.com",
                                       headers={"Authorization": "Bearer chatgpt-token"})
        with unittest.mock.patch.object(counting, "API", self.url + "/v1/responses/input_tokens"), \
                unittest.mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            _, sent = await self.run_call(Counter(CodexAdaptor()), turn())
        self.assertEqual(self.asked[0][0].get("Authorization"), "Bearer sk-test")          # never codex's token
        self.assertTrue(sent["counts"])
        self.asked.clear()
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            client, sent = await self.run_call(Counter(CodexAdaptor()), turn())
        self.assertEqual((self.asked, client.asked), ([], []))                              # no key: not asked

    async def test_a_model_the_endpoint_does_not_know_is_not_asked_for_again(self):
        self.unknown_models.add("gpt-reserve")
        counter, items = Counter(CodexAdaptor()), turn()
        client = Client()
        out = {"events": codex.to_events(items), "ag_items": [], "read_id": 1}
        counter.start(self.request, client, "g", {"channel": "c"}, body_of(items, "gpt-reserve"), items, items, out)
        await counter.close()
        asked = len(self.asked)
        self.assertFalse(counter.can_count(self.request, body_of(items, "gpt-reserve")))
        self.assertTrue(counter.can_count(self.request, body_of(items)))
        counter.start(self.request, client, "g", {"channel": "c"}, body_of(items, "gpt-reserve"), items, items, out)
        await counter.close()
        self.assertEqual(len(self.asked), asked)


class ReasoningTest(Base):
    """What the endpoint does not count, the call's own count does: the reasoning, by the difference."""

    async def call(self, counter, items, read_id):
        client = Client()
        out = {"events": codex.to_events(items), "ag_items": [], "read_id": read_id, "basis": None}
        counter.sent("g", "c", out, items, [])
        counter.start(self.request, client, "g", {"channel": "c"}, body_of(items), items, items, out)
        counter.reported(self.request, client, "g", "c", read_id, own_count(body_of(items)), body_of(items))
        await counter.close()
        await counter.close()
        return [b for op, b in client.asked if op == "counted" and not b.get("preamble_counts") and set(b) >= {"counts"}
                and all(k.startswith("rs_") for k in b["counts"]) and b["counts"]]

    async def test_a_new_reasoning_item_costs_what_the_call_s_count_is_over_the_endpoint_s(self):
        counter, items = Counter(CodexAdaptor()), turn()
        got = await self.call(counter, items, 1)
        self.assertEqual(got[-1]["counts"], {"rs_1": REASONING_COST})

    async def test_reasoning_costed_already_is_not_again_and_two_new_share_what_they_cost(self):
        counter, items = Counter(CodexAdaptor()), turn()
        await self.call(counter, items, 1)
        more = items + [{"type": "reasoning", "id": "rs_2", "summary": [], "encrypted_content": "b"},
                        {"type": "reasoning", "id": "rs_3", "summary": [], "encrypted_content": "c"},
                        {"type": "message", "role": "assistant", "id": "msg_2", "content": [{"type": "output_text", "text": "3."}]}]
        got = await self.call(counter, more, 2)
        self.assertEqual(got[-1]["counts"], {"rs_2": REASONING_COST, "rs_3": REASONING_COST})   # 80, shared evenly
        self.assertEqual(counter.channel("g", "c").reasoning["rs_1"], REASONING_COST)

    async def test_the_count_before_sending_takes_the_reasoning_at_what_it_costs(self):
        counter, items = Counter(CodexAdaptor()), turn()
        await self.call(counter, items, 1)
        exact = await counter.exact("g", "c", self.request, body_of(items))
        self.assertEqual(exact, own_count(body_of(items)))


class DifferencedTest(unittest.TestCase):
    """No endpoint: the calls' own counts, differenced."""

    def setUp(self):
        self.counter = Counter(CodexAdaptor())
        self.request = SimpleNamespace(path="/backend-api/codex/responses", upstream="https://chatgpt.com", headers={})
        self.client = Client()
        patcher = unittest.mock.patch.dict(os.environ, {}, clear=True)      # no key: the endpoint is not asked
        patcher.start()
        self.addCleanup(patcher.stop)

    def call(self, items, read_id, tokens, basis=None, preamble=(), ag_items=()):
        out = {"events": codex.to_events(items), "ag_items": list(ag_items), "read_id": read_id, "basis": basis}
        self.counter.sent("g", "c", out, items, list(preamble))

        async def go():
            self.counter.reported(self.request, self.client, "g", "c", read_id, tokens, body_of(items))
            await self.counter.close()
        asyncio.run(go())
        got = [b for op, b in self.client.asked if op == "counted"]
        self.client.asked.clear()
        return got[-1] if got else None

    def test_a_channel_s_first_call_is_differenced_from_nothing_its_preamble_too(self):
        items = turn()[:2]
        got = self.call(items, 1, 1000, preamble=[{"name": "instructions", "text": "You are codex."}])
        self.assertEqual(sum(got["counts"].values()) + sum(p["tokens"] for p in got["preamble_counts"]), 1000)
        self.assertEqual(set(got["counts"]), {"at1", "u1"})

    def test_the_next_call_s_new_items_are_what_the_counts_differ_by(self):
        items = turn()
        self.call(items[:2], 1, 1000)
        got = self.call(items, 2, 1300)
        self.assertEqual(set(got["counts"]), {codex.item_id(i) for i in items[2:]})
        self.assertEqual(sum(got["counts"].values()), 300)
        self.assertGreater(got["counts"]["u2"], 0)

    def test_after_a_build_or_with_something_taken_out_nothing_is_differenced(self):
        items = turn()
        self.call(items[:2], 1, 1000)
        self.assertIsNone(self.call(items, 2, 1300, basis="7"))                # a build since
        self.call(items, 3, 1300, basis="7")
        self.assertIsNone(self.call(items[:1] + items[2:], 4, 1200, basis="7"))   # an item taken out

    def test_ag_s_own_items_new_in_a_call_get_their_share(self):
        items = turn()[:2]
        sent = [ag_message("SUMMARY of earlier tasks")] + items
        out = {"events": codex.to_events(items), "ag_items": [(5, "SUMMARY of earlier tasks")], "read_id": 1, "basis": None}
        self.counter.sent("g", "c", out, sent, [])

        async def go():
            self.counter.reported(self.request, self.client, "g", "c", 1, 900, body_of(items))
            await self.counter.close()
        asyncio.run(go())
        (op, got), = self.client.asked
        self.assertIn("5", got["made"])
        self.assertEqual(sum(got["counts"].values()) + sum(got["made"].values()), 900)


@unittest.skipIf(web is None, "the hook server needs aiohttp")
class HookTest(Base):
    """The hook: counted before sending once near the budget, read again when over; counted after."""

    def hook(self, server, **options):
        return codex_ag.CodexContextManager(ag_clients=AgClients(lambda g: server), log=lambda g, l: None, files="off",
                                            **options)

    def server(self, tokens, budget=100000):
        class Server:
            def __init__(self):
                self.asked = []

            async def request(self, op, body=None, timeout=None):
                self.asked.append((op, body))
                if op != "rewrite":
                    return {}
                reads = sum(1 for o, _ in self.asked if o == "rewrite")
                ctx = [{"type": "ag", "name": "earlier", "text": "SUMMARY", "made_id": 3}] + body["events"]
                return {"context": ctx, "note": "ok", "read_id": reads, "basis": None, "tokens": tokens // 2,
                        "budget": budget, "sent_tokens": tokens}

            async def stop(self):
                pass
        return Server()

    def req(self):
        return SimpleNamespace(method="POST", path="/v1/responses", label="g", upstream=self.url, limit=None, state={},
                               headers={"thread-id": "t", "Authorization": "Bearer k"}, body=body_of(turn()), run=None)

    async def test_the_call_is_sent_then_counted(self):
        server = self.server(tokens=100)
        hook = self.hook(server)
        out = await hook(self.req())
        self.assertEqual(out["input"][0], ag_message("SUMMARY"))
        await hook.counter.close()
        self.assertEqual([op for op, _ in server.asked], ["rewrite", "counted"])
        counted = server.asked[1][1]
        self.assertEqual(counted["made"], {"3": cost(ag_message("SUMMARY"))})
        self.assertEqual(counted["properties"], {"channel": "t"})

    async def test_near_the_budget_it_is_counted_first_and_over_it_read_again(self):
        req = self.req()
        whole = price(body_of([ag_message("SUMMARY")] + turn()))
        server = self.server(tokens=whole, budget=whole - 5)             # ag's count at the budget's edge
        await self.hook(server, count="check")(req)
        self.assertEqual([op for op, _ in server.asked], ["rewrite", "measured", "rewrite"])
        self.assertEqual(server.asked[1][1]["tokens"], whole)              # the endpoint's count, reported
        self.assertEqual(req.state["ag_read"], ("g", 2))

    async def test_far_under_the_budget_nothing_is_counted_before_sending(self):
        server = self.server(tokens=100)
        await self.hook(server, count="check")(self.req())
        self.assertEqual(self.asked, [])
        self.assertEqual([op for op, _ in server.asked], ["rewrite"])

    async def test_the_call_s_own_count_is_given_to_the_counter(self):
        server = self.server(tokens=100)
        hook, req = self.hook(server), self.req()
        await hook(req)
        req.state[codex_ag.ANSWERED] = ("g", "t", None)
        await hook.measured(req, own_count(dict(body_of(turn()), input=[ag_message("SUMMARY")] + turn())))
        await hook.counter.close()
        await hook.counter.close()
        reasoning = [b for op, b in server.asked if op == "counted" and "rs_1" in b.get("counts", {})]
        self.assertEqual(reasoning[-1]["counts"]["rs_1"], REASONING_COST)

    async def test_counting_off(self):
        server = self.server(tokens=10 ** 6, budget=10)
        hook = self.hook(server, count="off")
        await hook(self.req())
        await hook.counter.close()
        self.assertEqual(self.asked, [])
        self.assertEqual([op for op, _ in server.asked], ["rewrite"])


if __name__ == "__main__":
    unittest.main()
