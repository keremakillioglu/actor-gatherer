"""What a harness sends besides its messages -- its system prompt, its tool definitions --
stated with each call (`rewrite`'s `preamble`), kept once per distinct text
(`_preambles`) and named by the read (`_reads.preamble_json`); the proxy hooks take it
from the request, and the dashboard shows it with the provider's count beyond it all."""
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer
except ImportError:
    web = None

from ag.ag_harness import home as ag_home  # noqa: E402
from ag.ag_harness.server import serve  # noqa: E402
from ag.ag_harness.server.__main__ import server_for  # noqa: E402
from ag.ag_harness.store import paths  # noqa: E402
from ag_dashboard import data  # noqa: E402
from ag_dashboard import home as dashboard_home  # noqa: E402
from ag.integrations.harnesses.codex.adaptor import to_events as codex  # noqa: E402
from ag.integrations.tools.ag_orchestrator.call_ag import preamble_of  # noqa: E402

if web is not None:
    from ag.integrations.harnesses.codex.ag_orchestrator import context_manager as codex_ag  # noqa: E402
    from ag.integrations.tools.hook_server import hook_server  # noqa: E402

DEV = {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "instructions"}]}


def user(text, n):
    return {"type": "message", "role": "user", "id": f"u{n}", "content": [{"type": "input_text", "text": text}]}


class HomeBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = paths.TRACE_DIR, paths.AG_HOME
        paths.AG_HOME = os.path.join(self.tmp.name, "ag")
        paths.TRACE_DIR = os.path.join(paths.AG_HOME, "gatherers")
        self.saved_home, dashboard_home.HOME = dashboard_home.HOME, paths.AG_HOME   # the dashboard reads the same home
        ag_home._HOMES.clear()

    def tearDown(self):
        paths.TRACE_DIR, paths.AG_HOME = self.saved
        dashboard_home.HOME = self.saved_home
        ag_home._HOMES.clear()
        self.tmp.cleanup()

    def ask(self, *requests):
        out = io.StringIO()
        serve(server_for(), [json.dumps(dict(r, id=i)) for i, r in enumerate(requests, 1)], out)
        return [json.loads(line) for line in out.getvalue().splitlines()]

    def db(self, gatherer="s"):
        conn = sqlite3.connect(paths.db_path(gatherer))
        conn.row_factory = sqlite3.Row
        return conn


class StoredTest(HomeBase):
    def test_each_distinct_text_once_and_each_call_names_its_own(self):
        pre = [{"name": "instructions", "text": "You are codex."}, {"name": "tools", "text": '[{"name": "shell"}]'}]
        changed = [{"name": "instructions", "text": "You are codex."}, {"name": "tools", "text": '[{"name": "apply_patch"}]'}]
        self.ask({"op": "rewrite", "gatherer": "s", "events": codex.to_events([DEV, user("q", 1)]), "preamble": pre},
                 {"op": "rewrite", "gatherer": "s", "events": codex.to_events([DEV, user("q", 1), user("r", 2)]), "preamble": pre},
                 {"op": "rewrite", "gatherer": "s", "events": codex.to_events([DEV, user("q", 1), user("s", 3)]),
                  "preamble": changed + [{"name": "", "text": "x"}, {"name": "empty", "text": ""}, "junk"]})
        conn = self.db()
        stored = conn.execute("SELECT name, text, tokens FROM _preambles ORDER BY preamble_id").fetchall()
        self.assertEqual([(r["name"], r["text"]) for r in stored],
                         [("instructions", "You are codex."), ("tools", '[{"name": "shell"}]'), ("tools", '[{"name": "apply_patch"}]')])
        self.assertTrue(all(r["tokens"] > 0 for r in stored))
        per_read = [json.loads(r[0]) for r in conn.execute("SELECT preamble_json FROM _reads ORDER BY read_id")]
        self.assertEqual(per_read, [[1, 2], [1, 2], [1, 3]])     # what was not a part is left out
        conn.close()

    def test_the_dashboard_shows_it_first_and_what_the_provider_counted_beyond_it(self):
        pre = [{"name": "instructions", "text": "You are codex. " * 50}]
        first, = self.ask({"op": "rewrite", "gatherer": "s", "properties": {"channel": "c1"},
                           "events": codex.to_events([DEV, user("q", 1)]), "preamble": pre})
        self.ask({"op": "measured", "gatherer": "s", "read_id": first["read_id"], "tokens": 5000})
        c = data.context("s", first["read_id"])
        self.assertEqual([p["name"] for p in c["preamble"]], ["instructions"])
        self.assertEqual(c["not_counted"], 5000 - c["tokens"] - c["preamble"][0]["tokens"])
        a = data.agent("s", "c1", [])
        self.assertEqual(a["reads"][0]["preamble_tokens"], c["preamble"][0]["tokens"])   # in the chart's count too
        u = a["usage"]
        self.assertIn("Harness preamble", {e["group"] for e in u["entries"]})
        self.assertEqual(u["not_counted"], c["not_counted"])


class PartsTest(unittest.TestCase):
    def test_a_request_s_parts_as_texts(self):
        self.assertEqual(preamble_of({"instructions": "Be brief.", "tools": [{"name": "b", "x": 1}], "none": None, "blank": " "}),
                         [{"name": "instructions", "text": "Be brief."}, {"name": "tools", "text": '[{"name": "b", "x": 1}]'}])
        system = [{"type": "text", "text": "You are Claude Code."}, {"type": "text", "text": "Be careful."}]
        self.assertEqual(preamble_of({"system": system})[0]["text"], "You are Claude Code.\n\nBe careful.")
        self.assertEqual(preamble_of({"tools": [{"b": 1, "a": 2}]})[0]["text"], '[{"a": 2, "b": 1}]')   # sorted: stable


@unittest.skipIf(web is None, "the hook server needs aiohttp")
class CodexProxyTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = os.environ.get("AG_HOME")
        os.environ["AG_HOME"] = self.home = os.path.join(self.tmp.name, "ag")

        async def upstream(request):
            await request.read()
            resp = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
            await resp.prepare(request)
            await resp.write(b'event: response.completed\ndata: {"type": "response.completed", "response": {"output": []}}\n\n')
            await resp.write_eof()
            return resp

        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", upstream)
        self.upstream = TestServer(app)
        await self.upstream.start_server()
        self.client = TestClient(TestServer(hook_server.make_app(
            str(self.upstream.make_url("")).rstrip("/"), codex_ag.CodexContextManager(log=lambda g, line: None))))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        await self.upstream.close()
        if self.saved is None:
            os.environ.pop("AG_HOME", None)
        else:
            os.environ["AG_HOME"] = self.saved
        self.tmp.cleanup()

    async def test_codex_s_instructions_and_tools_are_kept_with_the_call(self):
        tools = [{"type": "function", "name": "shell", "parameters": {"type": "object"}}]
        resp = await self.client.post("/v1/responses", headers={"thread-id": "t1"},
                                      json={"model": "m", "instructions": "You are codex.", "tools": tools,
                                            "input": [DEV, user("q", 1)], "stream": True})
        await resp.read()
        conn = sqlite3.connect(os.path.join(self.home, "gatherers", "t1", "context.db"))
        try:
            names = [r[0] for r in conn.execute("SELECT name FROM _preambles ORDER BY preamble_id")]
            per_read = conn.execute("SELECT preamble_json FROM _reads").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(names, ["instructions", "tools"])
        self.assertEqual(json.loads(per_read), [1, 2])


if __name__ == "__main__":
    unittest.main()
