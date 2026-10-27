"""A model call that failed, recorded on the read it was for (`call_failed`, records.py): its endpoint answered an
error, or could not be reached. The hook server reports it to the hook's `failed` (test_hook_server.py), which records
it -- so a reader of the gatherer (the dashboard) can tell a turn that stopped on an error from one under way."""
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

from ag.integrations.harnesses.codex.adaptor import to_events as codex  # noqa: E402

if web is not None:
    from ag.integrations.harnesses.codex.ag_orchestrator import context_manager as codex_ag  # noqa: E402
    from ag.integrations.tools.hook_server import hook_server  # noqa: E402

DEV = {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "instructions"}]}


def user(text, n):
    return {"type": "message", "role": "user", "id": f"u{n}", "content": [{"type": "input_text", "text": text}]}


class ProxyTest(unittest.IsolatedAsyncioTestCase):
    """The codex hook behind the real hook server, the real context manager server behind it: a call its
    endpoint answers with an error, and one with no endpoint to reach, each end up on the read they were for."""

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = os.environ.get("AG_HOME")
        os.environ["AG_HOME"] = self.home = os.path.join(self.tmp.name, "ag")

        async def upstream(request):
            await request.read()
            return web.json_response({"error": {"message": "Rate limit reached", "type": "rate_limit_error"}},
                                     status=429)

        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", upstream)
        self.upstream = TestServer(app)
        await self.upstream.start_server()
        self.hooks = []

    async def serve(self, upstream_url):
        hook = codex_ag.CodexContextManager(log=lambda g, line: None)
        client = TestClient(TestServer(hook_server.make_app(upstream_url, hook)))
        await client.start_server()
        self.hooks.append(client)
        return client

    async def asyncTearDown(self):
        for client in self.hooks:
            await client.close()
        await self.upstream.close()
        if self.saved is None:
            os.environ.pop("AG_HOME", None)
        else:
            os.environ["AG_HOME"] = self.saved
        self.tmp.cleanup()

    def failures(self):
        """Each call_failed recorded: (its read, the status, why), in order -- each on the read it was for."""
        conn = sqlite3.connect(os.path.join(self.home, "gatherers", "t1", "context.db"))
        try:
            rows = conn.execute("SELECT e.p_read_id, e.payload_json FROM events e JOIN event_types t USING (event_type_id) "
                                "WHERE t.name = 'call_failed' ORDER BY e.row_id").fetchall()
            reads = [r for (r,) in conn.execute("SELECT read_id FROM _reads ORDER BY read_id")]
        finally:
            conn.close()
        return [(read, json.loads(p)["status"], json.loads(p)["error"]) for read, p in rows], reads

    async def call(self, client, items):
        resp = await client.post("/v1/responses", json={"model": "m", "input": items, "stream": True},
                                 headers={"thread-id": "t1"})
        return resp.status, await resp.read()

    async def test_an_error_answer_and_no_answer_are_each_kept_on_their_read(self):
        status, _ = await self.call(await self.serve(str(self.upstream.make_url("")).rstrip("/")), [DEV, user("q", 1)])
        self.assertEqual(status, 429)                                        # codex gets its endpoint's answer
        status, body = await self.call(await self.serve("http://api.example.invalid"), [DEV, user("q", 1)])
        self.assertEqual(status, 502)
        self.assertIn(b"ag's hook server got no answer", body)
        ((first_read, first_status, first), (second_read, second_status, second)), reads = self.failures()
        self.assertEqual((first_status, first), (429, "rate_limit_error: Rate limit reached"))
        self.assertIsNone(second_status)
        self.assertIn("api.example.invalid", second)
        self.assertEqual([first_read, second_read], reads)                   # each on the read it was for


if __name__ == "__main__":
    unittest.main()
