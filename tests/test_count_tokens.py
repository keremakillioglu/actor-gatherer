"""Counting a Claude Code context exactly before it is sent: once the policy's count reaches
COUNT_FROM of its budget, Claude's hook asks the upstream's /v1/messages/count_tokens with the
request's own credentials; a count over the budget is reported as the read's size (`measured`) and
the context read again. The server's `rewrite` answers the policy's size and budget for it."""
import asyncio
import io
import json
import os
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
from ag.ag_harness.store import paths  # noqa: E402
from ag.integrations.harnesses.claude.ag_orchestrator import context_manager as claude_ag  # noqa: E402
from ag.integrations.harnesses.codex.ag_orchestrator.ag_clients import AgClients  # noqa: E402
from ag.integrations.harnesses.codex.adaptor import to_events as codex  # noqa: E402

TOOLS = [{"name": "Bash", "input_schema": {"type": "object"}},
         {"type": "tool_search_tool_regex_20251119", "name": "tool_search_tool_regex"},
         {"name": "mcp__x__y", "defer_loading": True, "input_schema": {"type": "object"}}]


class Client:
    """The server's stand-in: each rewrite a new read of the events, of `tokens` and `budget`."""

    def __init__(self, tokens, budget=1000):
        self.asked, self.tokens, self.budget = [], tokens, budget

    async def request(self, op, body=None, timeout=None):
        self.asked.append((op, body))
        if op == "measured":
            return {"recorded": True}
        reads = sum(1 for o, _ in self.asked if o == "rewrite")
        return {"context": body["events"], "note": "ok", "read_id": reads, "tokens": self.tokens // 2, "budget": self.budget,
                "sent_tokens": self.tokens}

    async def stop(self):
        pass


def request(upstream, headers=None):
    body = {"model": "m", "system": [{"type": "text", "text": "SYS"}], "tools": TOOLS, "max_tokens": 10,
            "stream": True, "messages": [{"role": "user", "content": [{"type": "text", "text": "count the rows"}]}]}
    return SimpleNamespace(method="POST", path="/v1/messages", label="g", body=body, upstream=upstream, limit=None,
                           headers=headers or {"X-Claude-Code-Session-Id": "sess", "Authorization": "Bearer t",
                                               "anthropic-beta": "b", "User-Agent": "claude-cli"}, state={})


@unittest.skipIf(web is None, "the hook server needs aiohttp")
class CountTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.counted, self.answer = [], (200, {"input_tokens": 1500})

        async def count_tokens(req):
            self.counted.append((dict(req.headers), await req.json()))
            status, body = self.answer
            return web.json_response(body, status=status)

        app = web.Application()
        app.router.add_post("/v1/messages/count_tokens", count_tokens)
        self.upstream = TestServer(app)
        await self.upstream.start_server()
        self.url = str(self.upstream.make_url("")).rstrip("/")

    async def asyncTearDown(self):
        await self.upstream.close()

    def hook(self, client, **options):
        options.setdefault("count", "check")                # the check alone: no counting after the call
        return claude_ag.ClaudeContextManager(ag_clients=AgClients(lambda gatherer: client), log=lambda g, l: None,
                                              **options)

    async def test_far_under_the_budget_nothing_is_counted(self):
        client = Client(tokens=100)
        await self.hook(client)(request(self.url))
        self.assertEqual(self.counted, [])
        self.assertEqual([o for o, _ in client.asked], ["rewrite"])

    async def test_near_the_budget_it_is_counted_with_the_requests_credentials(self):
        client = Client(tokens=600)
        self.answer = (200, {"input_tokens": 900})
        req = request(self.url)
        await self.hook(client)(req)
        headers, body = self.counted[0]
        self.assertEqual((headers.get("Authorization"), headers.get("anthropic-beta")), ("Bearer t", "b"))
        self.assertNotIn("X-Claude-Code-Session-Id", headers)
        self.assertEqual(sorted(body), ["messages", "model", "system", "tools"])         # no max_tokens, stream
        self.assertEqual([t["name"] for t in body["tools"]], ["Bash", "mcp__x__y"])     # tool search left out
        self.assertEqual([o for o, _ in client.asked], ["rewrite"])                      # under the budget: sent
        self.assertEqual(req.state["ag_read"], ("g", 1))

    async def test_over_the_budget_by_the_count_it_is_reported_and_read_again(self):
        client = Client(tokens=600)
        self.answer = (200, {"input_tokens": 1500})
        req = request(self.url)
        await self.hook(client)(req)
        self.assertEqual([o for o, _ in client.asked], ["rewrite", "measured", "rewrite"])
        self.assertEqual(client.asked[1][1], {"gatherer": "g", "read_id": 1, "tokens": 1500})
        self.assertEqual(req.state["ag_read"], ("g", 2))                # the second read is what is sent

    async def test_an_upstream_that_cannot_count_is_not_asked_again(self):
        client = Client(tokens=600)
        self.answer = (404, {"error": "no"})
        hook = self.hook(client)
        await hook(request(self.url))
        await hook(request(self.url))
        self.assertEqual(len(self.counted), 1)
        self.assertEqual([o for o, _ in client.asked], ["rewrite", "rewrite"])

    async def test_a_failed_count_sends_the_context_as_read(self):
        client = Client(tokens=600)
        self.answer = (429, {"error": "slow down"})
        req = request(self.url)
        await self.hook(client)(req)
        self.assertEqual([o for o, _ in client.asked], ["rewrite"])
        self.assertEqual(req.state["ag_read"], ("g", 1))

    async def test_counting_off(self):
        client = Client(tokens=600)
        await self.hook(client, count="off")(request(self.url))
        self.assertEqual(self.counted, [])


class RewriteSizesTest(unittest.TestCase):
    """The server's rewrite answers the policy's size of the context and its budget."""

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

    def test_tokens_and_budget(self):
        user = {"type": "message", "role": "user", "id": "u1", "content": [{"type": "input_text", "text": "hi"}]}
        out = io.StringIO()
        serve(server_for(), [json.dumps({"id": 1, "op": "rewrite", "gatherer": "s", "properties": {"channel": "c1"},
                                         "events": codex.to_events([user]), "limit": 100000,
                                         "preamble": [{"name": "system", "text": "You are codex. " * 20}]})], out)
        answer = json.loads(out.getvalue())
        self.assertGreater(answer["tokens"], 0)
        self.assertGreater(answer["sent_tokens"], answer["tokens"] + 40)    # the preamble, and what the policy does not budget
        self.assertGreater(answer["budget"], answer["tokens"])
        self.assertLess(answer["budget"], 100000)                    # under the harness's limit


if __name__ == "__main__":
    unittest.main()
