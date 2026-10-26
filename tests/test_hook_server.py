"""The hook server (`ag/integrations/tools/hook_server/hook_server.py`): an HTTP server that
calls a given hook on every request and relays. It knows nothing of any
harness, so it is checked here with a hook for a made-up API whose body is
`{"messages": [...]}`: what reaches the upstream, what comes back, and that a
hook that passes, changes or fails is relayed as it should be."""

import asyncio
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer
except ImportError:
    web = None

if web is not None:
    from ag.integrations.tools.hook_server import hook_server  # noqa: E402

STREAM = b"data: one\n\ndata: two\n\n"


def _anthropic():
    events = [{"type": "message_start", "message": {"id": "msg_1", "role": "assistant", "content": [], "usage": {}}},
              {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
              {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Writing it."}},
              {"type": "content_block_stop", "index": 0},
              {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "t1",
                                                                           "name": "Write", "input": {}}},
              {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta",
                                                                    "partial_json": '{"file_path": "/a"}'}},
              {"type": "content_block_stop", "index": 1},
              {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 5}},
              {"type": "message_stop"}]
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


ANTHROPIC = _anthropic()     # an Anthropic Messages stream: a text, then a tool call


class ToyHook:
    """Upper-cases a made-up API's messages; records every request it is given."""

    def __init__(self):
        self.seen, self.closed = [], False

    async def __call__(self, request):
        self.seen.append(request)
        if request.method != "POST" or not isinstance(request.body, dict) or "messages" not in request.body:
            return None
        if request.body.get("fail"):
            raise RuntimeError("the hook broke")
        return dict(request.body, messages=[m.upper() for m in request.body["messages"]])

    def close(self):
        self.closed = True


class RouteOfTest(unittest.TestCase):
    def test_the_url_s_label(self):
        route_of = __import__("ag.integrations.tools.hook_server.hook_server", fromlist=["route_of"]).route_of if web else None
        if route_of is None:
            self.skipTest("the hook server needs aiohttp")
        self.assertEqual(route_of("/h/demo/v1/responses"), ("demo", "/v1/responses"))
        self.assertEqual(route_of("/h/a.b_c-9/v1/x?y=1"), ("a.b_c-9", "/v1/x?y=1"))
        self.assertEqual(route_of("/h/demo"), ("demo", "/"))
        self.assertEqual(route_of("/v1/x"), (None, "/v1/x"))
        self.assertEqual(route_of("/h/bad name/v1"), (None, "/h/bad name/v1"))    # not a label: as it is
        self.assertEqual(route_of("/sx/demo/v1"), (None, "/sx/demo/v1"))

    def test_the_url_s_run(self):
        run_of = __import__("ag.integrations.tools.hook_server.hook_server", fromlist=["run_of"]).run_of if web else None
        if run_of is None:
            self.skipTest("the hook server needs aiohttp")
        self.assertEqual(run_of("/r/4242/l/100/v1/responses"), ("4242", "/l/100/v1/responses"))
        self.assertEqual(run_of("/v1/x"), (None, "/v1/x"))
        self.assertEqual(run_of("/r/bad run/v1"), (None, "/r/bad run/v1"))


@unittest.skipIf(web is None, "the hook server needs aiohttp")
class HookServerTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.received = []

        async def upstream(request):
            raw = await request.read()
            self.received.append((request.method, request.path_qs, dict(request.headers), raw))
            resp = web.StreamResponse(headers={"Content-Type": "text/event-stream", "X-Up": "1"})
            await resp.prepare(request)
            for frame in STREAM.split(b"\n\n")[:-1]:
                await resp.write(frame + b"\n\n")
            await resp.write_eof()
            return resp

        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", upstream)
        self.upstream = TestServer(app)
        await self.upstream.start_server()
        self.hook = ToyHook()
        self.dir = os.path.join(self.tmp.name, "log")
        self.client = TestClient(TestServer(hook_server.make_app(str(self.upstream.make_url("")).rstrip("/"),
                                                                 self.hook, self.dir)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        await self.upstream.close()
        self.tmp.cleanup()

    async def test_the_hook_s_body_is_forwarded_and_the_answer_streams_back(self):
        resp = await self.client.post("/v1/chat", json={"model": "m", "messages": ["hi", "there"]},
                                      headers={"Authorization": "Bearer k"})
        self.assertEqual((resp.status, await resp.read(), resp.headers.get("X-Up")), (200, STREAM, "1"))
        method, path, headers, raw = self.received[-1]
        self.assertEqual((method, path, json.loads(raw)), ("POST", "/v1/chat", {"model": "m", "messages": ["HI", "THERE"]}))
        self.assertEqual(headers.get("Authorization"), "Bearer k")                 # headers relayed
        request = self.hook.seen[-1]
        self.assertEqual((request.method, request.path, request.label, request.body["messages"]),
                         ("POST", "/v1/chat", None, ["hi", "there"]))
        with open(os.path.join(self.dir, "0001.json")) as fh:
            record = json.load(fh)                         # written before forwarding (status and time follow)
        self.assertEqual((record["body_in"]["messages"], record["body_out"]["messages"]),
                         (["hi", "there"], ["HI", "THERE"]))

    async def test_each_request_names_the_process_that_sent_it(self):
        await self.client.post("/v1/chat", json={"model": "m", "messages": ["hi"]})
        await self.client.post("/v1/chat", json={"model": "m", "messages": ["again"]})
        from ag.integrations.tools.hook_server import peer
        if not os.path.isdir("/proc/net"):
            self.skipTest("no /proc: the process cannot be told")
        me = peer.identity(os.getpid())                     # the test's client is this process
        self.assertEqual([r.process for r in self.hook.seen[-2:]], [me, me])

    async def test_none_forwards_the_original_bytes(self):
        raw = b'{"model": "m",   "other": [1, 2]}'                                   # odd spacing, kept
        await self.client.post("/v1/chat", data=raw, headers={"Content-Type": "application/json"})
        self.assertEqual(self.received[-1][3], raw)
        await self.client.post("/v1/chat", data=b"\x1f\x8bnot json")               # the hook gets body None
        self.assertEqual((self.received[-1][3], self.hook.seen[-1].body), (b"\x1f\x8bnot json", None))
        resp = await self.client.get("/v1/models")                                 # any method, any path
        self.assertEqual((resp.status, self.received[-1][:2]), (200, ("GET", "/v1/models")))
        self.assertEqual(os.listdir(self.dir) if os.path.isdir(self.dir) else [], [])   # nothing changed: no log

    async def test_a_zstd_compressed_request_reaches_the_hook_decoded(self):
        try:
            from compression import zstd                                          # Python 3.14+
        except ImportError:
            from backports import zstd                                            # a dependency before 3.14
        body = {"model": "m", "messages": ["hi"]}                                 # Codex on a ChatGPT login
        resp = await self.client.post("/v1/chat", data=zstd.compress(json.dumps(body).encode()),
                                      headers={"Content-Type": "application/json", "Content-Encoding": "zstd"})
        self.assertEqual(resp.status, 200)
        self.assertEqual(self.hook.seen[-1].body, body)
        _, _, headers, raw = self.received[-1]                                    # sent on decoded
        self.assertEqual((json.loads(raw), headers.get("Content-Encoding")), ({"model": "m", "messages": ["HI"]}, None))

    async def test_a_websocket_upgrade_is_refused_not_relayed(self):
        resp = await self.client.get("/v1/responses", headers={"Upgrade": "websocket", "Connection": "Upgrade"})
        self.assertEqual((resp.status, self.received, self.hook.seen), (426, [], []))   # codex then uses HTTP

    async def test_a_failing_hook_leaves_the_request_alone(self):
        body = {"messages": ["hi"], "fail": True}
        resp = await self.client.post("/v1/chat", json=body)
        self.assertEqual(resp.status, 200)
        self.assertEqual(json.loads(self.received[-1][3]), body)

    async def test_the_label_is_given_to_the_hook_and_stripped(self):
        await self.client.post("/h/demo/v1/chat", json={"messages": ["x"]})
        self.assertEqual((self.hook.seen[-1].label, self.hook.seen[-1].path), ("demo", "/v1/chat"))
        self.assertEqual(self.received[-1][1], "/v1/chat")
        self.assertIsNone(self.hook.seen[-1].run)

    async def test_the_run_is_given_to_the_hook_and_stripped_with_the_label_and_limit(self):
        await self.client.post("/h/demo/r/4242/l/1000/v1/chat", json={"messages": ["x"]})
        seen = self.hook.seen[-1]
        self.assertEqual((seen.label, seen.run, seen.limit, seen.path), ("demo", "4242", 1000, "/v1/chat"))
        self.assertEqual(self.received[-1][1], "/v1/chat")

    async def test_answered_gets_the_whole_answer_after_the_harness_has_it(self):
        class Answered(ToyHook):
            async def __call__(self, request):
                request.state["kept"] = True                 # only a request the hook kept something on
                return await super().__call__(request)

            async def answered(self, request, status, answer):
                self.answers.append((request.path, status, answer))

        hook = Answered()
        hook.answers = []
        client = TestClient(TestServer(hook_server.make_app(str(self.upstream.make_url("")).rstrip("/"), hook)))
        await client.start_server()
        try:
            resp = await client.post("/v1/chat", json={"messages": ["hi"]})
            self.assertEqual(await resp.read(), STREAM)
            await client.get("/v1/models")                                           # not a POST: not reported
        finally:
            await client.close()
        (path, status, answer), = hook.answers
        self.assertEqual((path, status), ("/v1/chat", 200))
        self.assertEqual(answer["output_items"], [])                                 # not a model's answer: nothing in it

    async def test_before_end_gets_the_answer_before_answered(self):
        class Ending(ToyHook):
            async def __call__(self, request):
                request.state["kept"] = True
                return await super().__call__(request)

            async def before_end(self, request, status, answer):
                self.order.append(("before_end", status, request.answer_started is not None))

            async def answered(self, request, status, answer):
                self.order.append(("answered", status))

        hook = Ending()
        hook.order = []
        client = TestClient(TestServer(hook_server.make_app(str(self.upstream.make_url("")).rstrip("/"), hook)))
        await client.start_server()
        try:
            resp = await client.post("/v1/chat", json={"messages": ["hi"]})
            self.assertEqual(await resp.read(), STREAM)
        finally:
            await client.close()
        self.assertEqual(hook.order, [("before_end", 200, True), ("answered", 200)])   # when the answer began: known

    async def test_answered_even_when_the_harness_hangs_up_before_the_stream_s_end(self):
        class HangUp(ToyHook):                               # codex closes once it has the whole answer
            async def __call__(self, request):
                request.state["kept"] = True
                return await super().__call__(request)

            async def before_end(self, request, status, answer):
                await asyncio.sleep(0.3)                     # the harness hangs up meanwhile

            async def answered(self, request, status, answer):
                self.answers.append(status)

        hook = HangUp()
        hook.answers = []
        runner = web.AppRunner(hook_server.make_app(str(self.upstream.make_url("")).rstrip("/"), hook))
        await runner.setup()                                 # as run_app serves it: a hang-up cancels no handler
        site = web.TCPSite(runner, "127.0.0.1", 0)           # (TestServer's would)
        await site.start()
        try:
            reader, writer = await asyncio.open_connection(*runner.addresses[0][:2])
            body = json.dumps({"messages": ["hi"]}).encode()
            writer.write(b"POST /v1/chat HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
                         + f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
            got = b""
            while b"data: two" not in got:                   # the whole answer, not yet its end
                got += await asyncio.wait_for(reader.read(4096), 5)
            writer.close()
            for _ in range(50):
                if hook.answers:
                    break
                await asyncio.sleep(0.05)
        finally:
            await runner.cleanup()
        self.assertEqual(hook.answers, [200])

    async def _hang_up(self, hook, upstream, until: bytes) -> None:
        """A request to a hook server served as run_app serves it (a hang-up cancels no handler) in front of `upstream`
        (an aiohttp handler), the harness hanging up once it has read `until` (b"": at once): until the hook reported."""
        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", upstream)
        up = TestServer(app)
        await up.start_server()
        runner = web.AppRunner(hook_server.make_app(str(up.make_url("")).rstrip("/"), hook))
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        try:
            reader, writer = await asyncio.open_connection(*runner.addresses[0][:2])
            body = json.dumps({"messages": ["hi"]}).encode()
            writer.write(b"POST /v1/chat HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
                         + f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
            await writer.drain()
            got = b""
            while until and until not in got:
                got += await asyncio.wait_for(reader.read(4096), 5)
            writer.close()                                   # Esc: Claude Code drops the call
            for _ in range(60):
                if hook.failures:
                    break
                await asyncio.sleep(0.05)
            await asyncio.sleep(0.2)
        finally:
            await runner.cleanup()
            await up.close()

    async def test_a_call_the_harness_hung_up_on_while_the_hook_ran_is_not_sent_and_is_reported_stopped(self):
        class Slow(ToyHook):                                 # as ag reads, behind other sessions' calls
            async def __call__(self, request):
                request.state["kept"] = True
                await asyncio.sleep(0.4)                     # the harness hangs up meanwhile
                return await super().__call__(request)

            async def failed(self, request, status, error):
                self.failures.append((status, error))

            async def answered(self, request, status, answer):
                self.answers.append(status)

        hook, sent = Slow(), []
        hook.failures, hook.answers = [], []

        async def upstream(request):
            sent.append(await request.read())
            return web.Response(text="{}")
        await self._hang_up(hook, upstream, b"")
        self.assertEqual(sent, [])                           # no model call for no one
        self.assertEqual(hook.failures, [(hook_server.HUNG_UP, hook_server.HUNG_UP_WHY)])
        self.assertEqual(hook.answers, [])

    async def test_a_call_the_harness_hung_up_on_as_the_answer_came_is_broken_off_and_reported_stopped(self):
        class Kept(ToyHook):
            async def __call__(self, request):
                request.state["kept"] = True
                return await super().__call__(request)

            async def failed(self, request, status, error):
                self.failures.append((status, error))

            async def answered(self, request, status, answer):
                self.answers.append(status)

        hook, frames = Kept(), []
        hook.failures, hook.answers = [], []

        async def upstream(request):                         # the model, answering slowly
            await request.read()
            resp = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
            await resp.prepare(request)
            try:
                for i in range(40):
                    await resp.write(f"data: {i}\n\n".encode())
                    frames.append(i)
                    await asyncio.sleep(0.05)
            except (ConnectionResetError, asyncio.CancelledError):
                pass
            return resp
        await self._hang_up(hook, upstream, b"data: 1\n")
        self.assertEqual(hook.failures, [(hook_server.HUNG_UP, hook_server.HUNG_UP_WHY)])
        self.assertEqual(hook.answers, [])
        self.assertLess(len(frames), 40)                     # the model's call given up with it

    async def test_streamed_gets_each_part_as_it_ends_while_the_answer_streams(self):
        """The upstream holds the rest of its answer until the hook has been given the text that came
        first: had the hook to wait for the end, the answer would never end."""
        given = asyncio.Event()

        async def upstream(request):
            await request.read()
            resp = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
            await resp.prepare(request)
            await resp.write(ANTHROPIC[:ANTHROPIC.index(b"event: content_block_start\ndata: {\"type\": "
                                                        b"\"content_block_start\", \"index\": 1")])
            await asyncio.wait_for(given.wait(), 5)
            await resp.write(ANTHROPIC[ANTHROPIC.index(b"event: content_block_start\ndata: {\"type\": "
                                                       b"\"content_block_start\", \"index\": 1"):])
            await resp.write_eof()
            return resp

        class Streamed(ToyHook):
            async def __call__(self, request):
                request.state["kept"] = True
                return await super().__call__(request)

            async def streamed(self, request, answer):
                self.order.append(("streamed", [b.get("type") for b in answer["output_items"]], answer["response_id"]))
                given.set()

            async def answered(self, request, status, answer):
                self.order.append(("answered", [b.get("type") for b in answer["output_items"]]))

        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", upstream)
        up = TestServer(app)
        await up.start_server()
        hook = Streamed()
        hook.order = []
        client = TestClient(TestServer(hook_server.make_app(str(up.make_url("")).rstrip("/"), hook)))
        await client.start_server()
        try:
            resp = await client.post("/v1/messages", json={"messages": ["hi"]})
            self.assertEqual(await resp.read(), ANTHROPIC)                          # relayed as it came
        finally:
            await client.close()
            await up.close()
        self.assertEqual(hook.order[0], ("streamed", ["text"], "msg_1"))           # before the rest was sent
        self.assertEqual(hook.order[-1], ("answered", ["text", "tool_use"]))      # after every part
        self.assertTrue(all(o == ("streamed", ["text", "tool_use"], "msg_1") for o in hook.order[1:-1]))

    async def test_the_hook_is_closed_with_the_server(self):
        await self.client.close()
        self.assertTrue(self.hook.closed)


class Failing(ToyHook):
    """Keeps something on each request (so it is reported), and records each failure reported."""

    def __init__(self):
        super().__init__()
        self.failures, self.answers = [], []

    async def __call__(self, request):
        request.state["kept"] = True
        return await super().__call__(request)

    async def failed(self, request, status, error):
        self.failures.append((status, error))

    async def answered(self, request, status, answer):
        self.answers.append(status)


class Unkept(Failing):
    """The same, but keeps nothing on a request: none of its reports are called."""

    async def __call__(self, request):
        return await ToyHook.__call__(self, request)


@unittest.skipIf(web is None, "the hook server needs aiohttp")
class FailedTest(unittest.IsolatedAsyncioTestCase):
    """A call that fails is reported to the hook's `failed`; one that got no answer is answered 502, saying why."""

    async def serve(self, upstream_url: str, hook) -> TestClient:
        client = TestClient(TestServer(hook_server.make_app(upstream_url, hook)))
        await client.start_server()
        self.addAsyncCleanup(client.close)
        return client

    async def upstream(self, handler) -> str:
        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", handler)
        up = TestServer(app)
        await up.start_server()
        self.addAsyncCleanup(up.close)
        return str(up.make_url("")).rstrip("/")

    async def test_an_endpoint_that_cannot_be_reached_is_reported_and_answered_502(self):
        hook = Failing()
        client = await self.serve("http://api.example.invalid", hook)       # .invalid never resolves
        resp = await client.post("/v1/messages", json={"messages": ["hi"]})
        self.assertEqual(resp.status, 502)
        body = await resp.json()
        self.assertEqual(body["type"], "error")
        self.assertEqual(body["error"]["type"], "api_error")
        self.assertIn("ag's hook server got no answer from http://api.example.invalid", body["error"]["message"])
        (status, error), = hook.failures
        self.assertIsNone(status)                                            # no answer came at all
        self.assertIn("api.example.invalid", error)
        self.assertEqual(hook.answers, [])                                   # nothing was answered

    async def test_an_error_status_reaches_the_harness_as_it_is_and_is_reported(self):
        overloaded = {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}

        async def upstream(request):
            if (await request.json()).get("messages") == ["BAD"]:
                return web.json_response(overloaded, status=529)
            return web.Response(body=STREAM, content_type="text/event-stream")

        hook = Failing()
        client = await self.serve(await self.upstream(upstream), hook)
        resp = await client.post("/v1/messages", json={"messages": ["bad"]})
        self.assertEqual((resp.status, await resp.json()), (529, overloaded))
        ok = await client.post("/v1/messages", json={"messages": ["fine"]})
        self.assertEqual(await ok.read(), STREAM)
        self.assertEqual(hook.failures, [(529, "overloaded_error: Overloaded")])   # the good call: not a failure
        self.assertEqual(hook.answers, [529, 200])

    async def test_an_error_in_an_answer_that_came_back_200_is_a_failure_too(self):
        async def upstream(request):                                         # overloaded once it had begun
            return web.Response(body=b'event: message_start\ndata: {"type": "message_start", "message": {"id": "m1"}}\n\n'
                                     b'event: error\ndata: {"type": "error", "error": {"type": "overloaded_error", '
                                     b'"message": "Overloaded"}}\n\n', content_type="text/event-stream")

        hook = Failing()
        client = await self.serve(await self.upstream(upstream), hook)
        await (await client.post("/v1/messages", json={"messages": ["hi"]})).read()
        self.assertEqual(hook.failures, [(200, "overloaded_error: Overloaded")])

    async def test_a_request_the_hook_kept_nothing_on_is_not_reported(self):
        hook = Unkept()
        client = await self.serve("http://api.example.invalid", hook)
        resp = await client.post("/v1/messages", json={"messages": ["hi"]})
        self.assertEqual(resp.status, 502)                                   # told why all the same
        self.assertEqual(hook.failures, [])


RESPONSES_STREAM = (
    b'event: response.created\ndata: {"type": "response.created", "response": {"id": "r1"}}\n\n'
    b'event: response.output_item.done\ndata: {"type": "response.output_item.done", '
    b'"item": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "hi"}]}}\n\n'
    b'event: response.completed\ndata: {"type": "response.completed", "response": {"id": "r1", "status": '
    b'"completed", "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", '
    b'"text": "hi"}]}], "usage": {"input_tokens": 10, "input_tokens_details": {"cached_tokens": 4}, '
    b'"output_tokens": 3, "output_tokens_details": {"reasoning_tokens": 1}, "total_tokens": 13}}}\n\n')


@unittest.skipIf(web is None, "the hook server needs aiohttp")
class ModelTraceTest(unittest.IsolatedAsyncioTestCase):
    """--trace-root: each model call as the model got it, and its answer, in codex's trace layout."""

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()

        async def upstream(request):
            await request.read()
            resp = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
            await resp.prepare(request)
            for frame in RESPONSES_STREAM.split(b"\n\n")[:-1]:
                await resp.write(frame + b"\n\n")
            await resp.write_eof()
            return resp

        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", upstream)
        self.upstream = TestServer(app)
        await self.upstream.start_server()
        self.root = os.path.join(self.tmp.name, "trace")
        self.client = TestClient(TestServer(hook_server.make_app(str(self.upstream.make_url("")).rstrip("/"),
                                                                 ToyHook(), None, self.root, ("x-thread",))))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        await self.upstream.close()
        self.tmp.cleanup()

    def trace(self):
        (name,) = os.listdir(self.root)
        d = os.path.join(self.root, name)
        with open(os.path.join(d, "trace.jsonl")) as fh:
            events = [json.loads(line) for line in fh]
        def load(ref):
            with open(os.path.join(d, ref["path"])) as fh:
                return json.load(fh)
        return d, events, load

    async def test_the_model_s_request_and_answer_are_traced(self):
        resp = await self.client.post("/h/demo/v1/responses", json={"model": "m", "messages": ["hi"]},
                                      headers={"x-thread": "t1"})
        self.assertEqual(await resp.read(), RESPONSES_STREAM)                  # relayed untouched
        d, events, load = self.trace()
        self.assertEqual(load({"path": "manifest.json"})["raw_event_log"], "trace.jsonl")
        kinds = [e["payload"]["type"] for e in events]
        self.assertEqual(kinds, ["rollout_started", "inference_started", "inference_completed"])
        started, done = events[1]["payload"], events[2]["payload"]
        self.assertEqual((started["label"], started["thread_id"], started["hooked"], started["model"]),
                         ("demo", "t1", True, "m"))
        self.assertEqual(load(started["request_payload"]), {"model": "m", "messages": ["HI"]})   # as forwarded
        answer = load(done["response_payload"])
        self.assertEqual((done["inference_call_id"], done["response_id"], done["http_status"]),
                         (started["inference_call_id"], "r1", 200))
        self.assertEqual(answer["token_usage"], {"input_tokens": 10, "cached_input_tokens": 4,
                                                 "cache_write_input_tokens": 0, "output_tokens": 3,
                                                 "reasoning_output_tokens": 1, "total_tokens": 13})
        self.assertEqual(answer["output_items"][0]["content"][0]["text"], "hi")

    async def test_an_unchanged_call_is_traced_too_and_the_rest_is_not(self):
        await self.client.post("/v1/responses", json={"model": "m", "input": []})   # the hook leaves it
        await self.client.get("/v1/models")                                         # not a model call
        await self.client.close()
        _, events, load = self.trace()
        self.assertEqual([e["payload"]["type"] for e in events],
                         ["rollout_started", "inference_started", "inference_completed", "rollout_ended"])
        self.assertFalse(events[1]["payload"]["hooked"])
        self.assertEqual(load(events[1]["payload"]["request_payload"]), {"model": "m", "input": []})


class StreamedOfTest(unittest.TestCase):
    def test_the_parts_complete_so_far(self):
        from ag.integrations.tools.hook_server.trace import streamed_of
        cut = ANTHROPIC[:ANTHROPIC.index(b'"content_block_stop", "index": 1')]
        self.assertEqual(streamed_of(cut), {"response_id": "msg_1",
                                            "output_items": [{"type": "text", "text": "Writing it."}]})
        self.assertEqual(len(streamed_of(ANTHROPIC)["output_items"]), 2)
        self.assertEqual(streamed_of(ANTHROPIC[:ANTHROPIC.index(b'"content_block_stop", "index": 0')])["output_items"], [])
        self.assertEqual(streamed_of(b"data: one\n\n"), {"response_id": None, "output_items": []})   # no stream of either


class LoadHookTest(unittest.TestCase):
    def test_a_hook_or_a_class_built_with_the_options(self):
        if web is None:
            self.skipTest("the hook server needs aiohttp")
        hook = hook_server.load_hook("ag.integrations.harnesses.codex.ag_orchestrator.context_manager:CodexContextManager", {"cwd": "/w"})
        self.assertEqual(hook.cwd, "/w")
        self.assertIs(hook_server.load_hook("ag.integrations.harnesses.codex.ag_orchestrator.context_manager:is_model_call", {}),
                      __import__("ag.integrations.harnesses.codex.ag_orchestrator.context_manager", fromlist=["x"]).is_model_call)
        with self.assertRaises(ValueError):
            hook_server.load_hook("ag.integrations.harnesses.codex.ag_orchestrator.context_manager:is_model_call", {"cwd": "/w"})


if __name__ == "__main__":
    unittest.main()
