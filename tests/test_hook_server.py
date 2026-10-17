"""The hook server (`ag/integrations/tools/hook_server/hook_server.py`): an HTTP server that
calls a given hook on every request and relays. It knows nothing of any
harness, so it is checked here with a hook for a made-up API whose body is
`{"messages": [...]}`: what reaches the upstream, what comes back, and that a
hook that passes, changes or fails is relayed as it should be."""

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

    async def test_the_hook_is_closed_with_the_server(self):
        await self.client.close()
        self.assertTrue(self.hook.closed)


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
