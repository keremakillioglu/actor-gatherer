"""A model call that failed, kept on the read it was for (`_reads.error_status`, `_reads.error`): its
endpoint answered an error, or could not be reached. The hook server reports it to the hook's `failed`
(test_hook_server.py), the hook to the server's `failed` op, which records it and tells the listeners --
so a reader of the gatherer (the dashboard) can tell a turn that stopped on an error from one under way."""
import asyncio
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
from ag.ag_harness.store import operations as store  # noqa: E402
from ag.ag_harness.store import paths, schema  # noqa: E402
from ag.integrations.harnesses.codex.adaptor import to_events as codex  # noqa: E402
from ag.integrations.tools.ag_orchestrator.call_ag import keep_read, report_failed  # noqa: E402

if web is not None:
    from ag.integrations.harnesses.codex.ag_orchestrator import context_manager as codex_ag  # noqa: E402
    from ag.integrations.tools.hook_server import hook_server  # noqa: E402

DEV = {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "instructions"}]}


def user(text, n):
    return {"type": "message", "role": "user", "id": f"u{n}", "content": [{"type": "input_text", "text": text}]}


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = sqlite3.connect(os.path.join(self.tmp.name, "g.db"))
        schema.create(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def failure(self, read_id):
        return self.conn.execute("SELECT error_status, error FROM _reads WHERE read_id = ?", (read_id,)).fetchone()

    def test_a_read_s_call_that_failed_is_kept_on_it(self):
        read_id = store.record_read(self.conn, None, [], manager="m")
        self.assertEqual(self.failure(read_id), (None, None))               # not failed, or not known
        self.assertTrue(store.record_failed(self.conn, read_id, 529, "overloaded_error: Overloaded"))
        self.assertEqual(self.failure(read_id), (529, "overloaded_error: Overloaded"))
        other = store.record_read(self.conn, None, [], manager="m")
        self.assertTrue(store.record_failed(self.conn, other, None, "Cannot connect to host api.anthropic.com:443"))
        self.assertEqual(self.failure(other), (None, "Cannot connect to host api.anthropic.com:443"))   # no answer came
        self.assertFalse(store.record_failed(self.conn, other + 1, 500, "x"))   # no such read

    def test_a_file_from_before_reads_kept_failures_gets_the_columns(self):
        old = sqlite3.connect(os.path.join(self.tmp.name, "old.db"))
        old.execute("CREATE TABLE _reads (read_id INTEGER PRIMARY KEY, read_at TEXT NOT NULL, row_id INTEGER, "
                    "manager TEXT, basis TEXT)")
        old.execute("INSERT INTO _reads (read_at, manager) VALUES ('t', 'm')")
        schema.create(old)
        self.assertTrue(store.record_failed(old, 1, 500, "api_error: Internal server error"))
        old.close()


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

    def test_a_failure_is_recorded_on_its_read_and_told(self):
        told = []
        import ag.ag_harness.manager as manager_module
        saved = manager_module.notify
        manager_module.notify = lambda gatherer, what, properties=None, row=None: told.append((what, row))
        try:
            first, failed, bad, none = self.ask(
                {"op": "rewrite", "gatherer": "s", "events": codex.to_events([DEV, user("q", 1)])},
                {"op": "failed", "gatherer": "s", "read_id": 1, "status": 502, "error": "bad gateway"},
                {"op": "failed", "gatherer": "s", "read_id": 1, "status": 502},          # no error: refused
                {"op": "failed", "gatherer": "s", "read_id": 99, "error": "x"})          # no such read
        finally:
            manager_module.notify = saved
        self.assertEqual((failed["recorded"], none["recorded"]), (True, False))
        self.assertIn("error", bad)
        conn = sqlite3.connect(paths.db_path("s"))
        try:
            self.assertEqual(conn.execute("SELECT read_id, error_status, error FROM _reads").fetchall(),
                             [(first["read_id"], 502, "bad gateway")])
        finally:
            conn.close()
        self.assertIn(("failed", 1), told)
        self.assertNotIn(("failed", 99), told)                                  # nothing recorded: nothing told


@unittest.skipIf(web is None, "the hook server needs aiohttp")
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


class HelpersTest(unittest.TestCase):
    def test_a_failure_is_reported_to_the_read_kept_on_the_request(self):
        sent = []

        class Client:
            async def request(self, op, body):
                sent.append((op, body))
                return {}

        class Clients:
            def client(self, gatherer):
                return Client()

        class Req:
            state = {}

        asyncio.run(report_failed(Clients(), Req(), 500, "x"))              # no read kept: nothing sent
        req = Req()
        keep_read(req, "g", {"read_id": 3})
        asyncio.run(report_failed(Clients(), req, None, "Cannot connect"))
        self.assertEqual(sent, [("failed", {"gatherer": "g", "read_id": 3, "status": None, "error": "Cannot connect"})])


if __name__ == "__main__":
    unittest.main()
