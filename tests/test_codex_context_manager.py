"""The context manager as codex's hook (`ag/integrations/harnesses/codex/ag_orchestrator/context_manager.py`): codex's model calls through
the context manager, as the hook server calls it.

What it decides -- which requests are model calls, the thread, the working
directory -- is checked on its own; then requests go through the real hook
server (`ag/integrations/tools/hook_server/hook_server.py`) calling the hook, to a stand-in
upstream that records what it receives and answers with a short event stream,
so what is checked is what reaches the model and what reaches codex. Behind
the hook, a fake server client (what it asks, what it is answered), then the
real one: a context manager server per gatherer, over stdio. Nothing of the
context manager is imported here.
"""

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
except ImportError:                                   # the proxy's one dependency
    web = None

from ag.integrations.harnesses.codex.adaptor import to_events as codex_format  # noqa: E402

from ag.integrations.harnesses.codex.ag_orchestrator import context_manager as codex_ag  # noqa: E402
from ag.integrations.harnesses.codex.ag_orchestrator.ag_clients import AgClients  # noqa: E402
from channels import ch, on  # noqa: E402

if web is not None:
    from ag.integrations.tools.hook_server import hook_server  # noqa: E402

SSE = b'event: response.created\ndata: {"type": "response.created"}\n\n' \
      b'event: response.completed\ndata: {"type": "response.completed", "response": {"output": []}}\n\n'
DEV = {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "instructions"}]}
MANAGED = {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "MANAGED"}]}


def env(cwd):
    return {"type": "message", "role": "user",
            "content": [{"type": "input_text", "text": f"<environment_context>\n  <cwd>{cwd}</cwd>\n"
                                                        "  <shell>bash</shell>\n</environment_context>"}]}


def roots_env(*roots):
    """The npm codex 0.146's environment context: no <cwd>, the workspace roots instead."""
    listed = "".join(f"<root>{r}</root>" for r in roots)
    return {"type": "message", "role": "user",
            "content": [{"type": "input_text", "text": "<environment_context>\n  <current_date>2026-09-28</current_date>\n"
                                                        f"  <filesystem><workspace_roots>{listed}</workspace_roots>"
                                                        "<permission_profile type=\"managed\"></permission_profile>"
                                                        "</filesystem>\n</environment_context>"}]}


def user(text, n):
    return {"type": "message", "role": "user", "id": f"u{n}", "content": [{"type": "input_text", "text": text}]}


def agent(text, n):
    return {"type": "message", "role": "assistant", "id": f"a{n}",
            "content": [{"type": "output_text", "text": text}]}


def cat(name, n):
    """The agent's own call reading `name`, and its output: what makes a file seen for a notice."""
    return [{"type": "function_call", "id": f"fc{n}", "call_id": f"c{n}", "name": "exec_command",
             "arguments": json.dumps({"cmd": f"cat {name}"})},
            {"type": "function_call_output", "id": f"fco{n}", "call_id": f"c{n}", "output": "x = 1"}]


class FakeClient:
    """Stands in for a gatherer's server client (`ag.integrations.tools.ag_connection.ag_client.AgClient`):
    records each request and answers a rewrite with an `ag` message before
    the events, as sent; `answer` can be replaced."""

    made = []

    def __init__(self, gatherer):
        self.gatherer, self.requests, self.records, self.stopped = gatherer, [], [], False
        self.answer = lambda body: {"context": [{"type": "ag", "name": "earlier", "text": "MANAGED"}]
                                    + [{"type": e["type"], "id": e["id"], "payload": e["payload"]}
                                       for e in body["events"]],
                                    "note": f"{len(body['events'])} items in"}
        FakeClient.made.append(self)

    async def request(self, op, body=None):
        if op == "insert":                     # what the hook records besides the conversation (a model call, ...)
            self.records += [dict(e, channel=body["properties"]["channel"]) for e in body["events"]]
            return {"rows": []}
        self.requests.append((op, body))
        return self.answer(body)

    async def stop(self):
        self.stopped = True


class ParsingTest(unittest.TestCase):
    def test_the_gatherer_is_the_thread_id(self):
        self.assertEqual(codex_ag.thread_of({"Thread-Id": "t", "session-id": "s"}, {"prompt_cache_key": "k"}), "t")
        self.assertEqual(codex_ag.thread_of({"session-id": "s"}, {"prompt_cache_key": "k"}), "s")
        self.assertEqual(codex_ag.thread_of({}, {"prompt_cache_key": "k"}), "k")
        self.assertIsNone(codex_ag.thread_of({}, {}))

    def test_the_cwd_is_the_last_environment_context(self):
        self.assertEqual(codex_ag.cwd_of([DEV, env("/a"), user("q", 1), env("/b")]), "/b")
        self.assertIsNone(codex_ag.cwd_of([user("my <cwd>/x</cwd>", 1)]))       # only inside an environment context
        self.assertIsNone(codex_ag.cwd_of([DEV, user("q", 1), "not a dict"]))

    def test_without_a_cwd_the_cwd_is_the_first_workspace_root(self):
        self.assertEqual(codex_ag.cwd_of([DEV, roots_env("/ws", "/other"), user("q", 1)]), "/ws")
        self.assertEqual(codex_ag.cwd_of([env("/a"), user("q", 1), roots_env("/b")]), "/b")
        self.assertIsNone(codex_ag.cwd_of([user("<workspace_roots><root>/x</root></workspace_roots>", 1)]))

    def test_what_is_rewritten(self):
        body = {"input": [DEV, user("q", 1)]}
        self.assertTrue(codex_ag.is_model_call("POST", "/v1/responses", body))
        self.assertTrue(codex_ag.is_model_call("POST", "/v1/responses/", body))
        self.assertFalse(codex_ag.is_model_call("GET", "/v1/responses", body))
        self.assertFalse(codex_ag.is_model_call("POST", "/v1/responses/compact", body))
        self.assertFalse(codex_ag.is_model_call("POST", "/v1/models", body))
        self.assertFalse(codex_ag.is_model_call("POST", "/v1/responses", {"input": [DEV]}))   # no user message
        self.assertFalse(codex_ag.is_model_call("POST", "/v1/responses", {"input": "text"}))
        self.assertFalse(codex_ag.is_model_call("POST", "/v1/responses", None))


class HookTest(unittest.TestCase):
    """The hook called directly -- no server: it takes any request-shaped
    object, so how it is called is not its business."""

    def request(self, body, method="POST", path="/v1/responses", label=None, headers=None):
        from types import SimpleNamespace
        return SimpleNamespace(method=method, path=path, label=label,
                               headers={"thread-id": "t1"} if headers is None else headers, body=body)

    def hook(self, answer=None):
        FakeClient.made = []
        hook = codex_ag.CodexContextManager(ag_clients=AgClients(FakeClient), log=lambda s, l: None)
        if answer is not None:
            hook.ag_clients.client("t1").answer = answer
            hook.ag_clients.client("demo").answer = answer
        return hook

    def call(self, hook, request):
        import asyncio
        return asyncio.run(hook(request))

    def test_none_when_there_is_nothing_to_change(self):
        items = [DEV, user("q", 1)]
        same = lambda body: {"context": [{"type": e["type"], "id": e["id"], "payload": e["payload"]}
                                         for e in body["events"]], "note": "same"}
        self.assertIsNone(self.call(self.hook(), self.request({"input": items}, method="GET")))   # not a model call
        self.assertIsNone(self.call(self.hook(), self.request({"input": items}, headers={})))    # no thread
        self.assertIsNone(self.call(self.hook(same), self.request({"input": items})))           # context = input
        self.assertIsNone(self.call(self.hook(lambda b: {"error": "down"}), self.request({"input": items})))

    def test_a_new_body_when_the_context_changed(self):
        items = [DEV, user("q", 1)]
        out = self.call(self.hook(), self.request({"model": "m", "input": items, "stream": True}))
        self.assertEqual(out, {"model": "m", "input": [MANAGED] + items, "stream": True})

    def test_the_label_is_the_gatherer_and_the_thread_its_channel(self):
        hook = self.hook()
        self.call(hook, self.request({"input": [user("q", 1)]}, label="demo"))
        self.call(hook, self.request({"input": [user("q", 1)]}))
        self.assertEqual([(c.gatherer, c.requests[0][1]["gatherer"], c.requests[0][1]["properties"]["channel"])
                          for c in FakeClient.made], [("demo", "demo", "t1"), ("t1", "t1", "t1")])


def meta(**fields):
    """Codex's turn metadata header, as it sends it."""
    return {"thread-id": "t1", "x-codex-turn-metadata": json.dumps({"thread_id": "t1", "request_kind": "turn", **fields})}


TRIGGER = {"type": "compaction_trigger"}
SUMMARY = {"type": "compaction", "id": "cmp_1", "encrypted_content": "gAAAA"}


class SideCallTest(HookTest):
    """Codex's own side calls, by what its turn metadata says they are for: passed through, nothing
    stored; and its compaction, built in its place."""

    def test_what_codex_says_a_call_is_for(self):
        self.assertEqual(codex_ag.metadata_of(meta(thread_source="user"), {})["thread_source"], "user")
        inside = {"client_metadata": {"x-codex-turn-metadata": json.dumps({"thread_source": "system"})}}
        self.assertEqual(codex_ag.metadata_of({}, inside), {"thread_source": "system"})       # the body's copy
        self.assertEqual(codex_ag.metadata_of({"x-codex-turn-metadata": "not json"}, {}), {})
        for fields, kind in (({"thread_source": "user"}, None), ({}, None),             # a turn; an older codex's
                             ({"thread_source": "thread_title"}, "thread_title"), ({"thread_source": "system"}, "system"),
                             ({"thread_source": "subagent", "parent_thread_id": "t0"}, "subagent"),
                             ({"thread_source": "guardian_review"}, "guardian_review"),
                             ({"thread_source": "memory_consolidation"}, "memory_consolidation"),
                             ({"parent_thread_id": "t0"}, "subagent")):
            self.assertEqual(codex_ag.side_call(fields), kind, fields)

    def test_a_side_call_goes_through_as_it_is_and_nothing_is_stored(self):
        title = user("Generate a concise, single-line task title of at most 36 characters", 1)
        for source in ("thread_title", "system", "subagent", "guardian_review"):
            hook = self.hook()
            request = self.request({"input": [DEV, title]}, headers=meta(thread_source=source))
            request.state = {}
            self.assertIsNone(self.call(hook, request), source)
            self.assertEqual(FakeClient.made, [], source)                # no server asked: nothing stored
            self.assertNotIn(codex_ag.ANSWERED, request.state)           # its answer not kept either

    def test_a_title_and_a_recap_are_kept_for_the_thread_their_run_last_turned_in(self):
        import asyncio
        hook = self.hook()
        turn = self.request({"input": [DEV, user("Add 2 and 3", 1)]}, label="demo", headers=meta(thread_source="user"))
        turn.run, turn.state = "4242", {}
        self.call(hook, turn)
        said = lambda text: {"output_items": [{"type": "message", "role": "assistant",
                                               "content": [{"type": "output_text", "text": text}]}]}
        for source, text in (("thread_title", '{"title": "Add 2 and 3"}'),
                             ("system", '{"summary": "2 + 3 is 5.", "next_action": "Multiply it."}')):
            side = self.request({"input": [DEV, user("...", 1)]}, label="demo", headers={**meta(thread_source=source),
                                                                                        "thread-id": "side"})
            side.run, side.state = "4242", {}
            self.assertIsNone(self.call(hook, side))                      # as it is
            asyncio.run(hook.answered(side, 200, said(text)))
        client = hook.ag_clients.client("demo")
        kept = [(e["type"], e["channel"], e["payload"]) for e in client.records if e["type"] in ("name", "recap")]
        self.assertEqual(kept, [("name", "t1", {"text": "Add 2 and 3", "by": "codex"}),
                                ("recap", "t1", {"text": "2 + 3 is 5.\n\nNext: Multiply it."})])
        self.assertNotIn("reply_part", [e["type"] for e in client.records])   # never the thread's own answer

    def test_an_answer_a_later_call_has_carried_back_is_not_kept_as_pending(self):
        """Codex sends its next call once it has the whole answer, before the hook server is done with
        it: that call stores the answer, so keeping it as pending then would show it twice."""
        import asyncio
        hook = self.hook()
        reads = iter(range(1, 10))
        hook.ag_clients.client("t1").answer = lambda body: {"context": body["events"], "note": "ok", "read_id": next(reads)}
        first, second = (self.request({"input": [DEV, user("q", 1)]}, headers=meta(thread_source="user")) for _ in range(2))
        for r in (first, second):
            r.state = {}
            self.call(hook, r)                              # reads 1 and 2
        said = {"output_items": [{"type": "message", "role": "assistant", "id": "m1",
                                  "content": [{"type": "output_text", "text": "done"}]}], "response_id": "resp_1"}
        asyncio.run(hook.streamed(first, said))
        asyncio.run(hook.answered(first, 200, said))       # read 2 is under way: read 1's answer is in it
        asyncio.run(hook.answered(second, 200, dict(said, response_id="resp_2")))
        kept = {e["properties"]["answer_id"] for e in hook.ag_clients.client("t1").records if e["type"] == "reply_part"}
        self.assertEqual(kept, {"resp_2"})

    def test_a_turn_s_run_is_sent_with_it(self):
        hook = self.hook()
        for run in ("4242", None):
            turn = self.request({"input": [DEV, user("q", 1)]}, headers=meta(thread_source="user"))
            turn.run, turn.state = run, {}
            self.call(hook, turn)
        (_, first), (_, second) = [r for r in hook.ag_clients.client("t1").requests if r[0] == "rewrite"]
        self.assertEqual((first.get("run"), "run" in second), ("4242", False))

    def test_a_side_call_from_no_run_another_run_or_before_a_turn_is_not_kept(self):
        import asyncio
        title = {"output_items": [{"type": "message", "content": [{"type": "output_text", "text": '{"title": "T"}'}]}]}
        for runs in ((None, None), ("1", "2"), (None, "1")):        # no run said; another run's turn; no turn yet
            hook = self.hook()
            if runs[0] is not None:
                turn = self.request({"input": [DEV, user("q", 1)]}, headers=meta(thread_source="user"))
                turn.run, turn.state = runs[0], {}
                self.call(hook, turn)
            side = self.request({"input": [DEV, user("q", 1)]}, headers=meta(thread_source="thread_title"))
            side.run, side.state = runs[1], {}
            self.call(hook, side)
            self.assertNotIn(codex_ag.SIDE, side.state, runs)
            asyncio.run(hook.answered(side, 200, title))
            self.assertNotIn("name", [op for c in FakeClient.made for op, _ in c.requests], runs)

    def test_a_side_answer_that_is_not_what_codex_asked_for_is_not_kept(self):
        import asyncio
        hook = self.hook()
        said = lambda text: {"output_items": [{"type": "message", "content": [{"type": "output_text", "text": text}]}]}
        for status, answer in ((200, said("Add 2 and 3")), (200, said('{"title": " "}')), (500, said('{"title": "T"}')),
                               (200, {"error": "x"}), (200, said('{"summary": ""}'))):
            asyncio.run(hook.side_answered(("thread_title" if "summary" not in str(answer) else "system", "demo", "t1"),
                                           status, answer))
        self.assertEqual([op for c in FakeClient.made for op, _ in c.requests], [])
        self.assertEqual(codex_ag.answer_object(said('{"title": "T"}')), {"title": "T"})
        self.assertEqual(codex_ag.answer_object(said("[1]")), {})

    def test_a_turn_is_rewritten(self):
        out = self.call(self.hook(), self.request({"input": [DEV, user("q", 1)]}, headers=meta(thread_source="user")))
        self.assertEqual(out["input"], [MANAGED, DEV, user("q", 1)])

    def test_a_compaction_builds_and_gets_the_context_with_the_trigger_last(self):
        hook = self.hook()
        items = [DEV, user("q", 1), agent("a", 1), TRIGGER]
        out = self.call(hook, self.request({"input": items}, headers=meta(thread_source="user", request_kind="compaction")))
        op, body = FakeClient.made[0].requests[0]
        self.assertEqual(op, "compaction")
        self.assertEqual([e["payload"] for e in body["events"]], items[:-1])   # the trigger is no event
        self.assertEqual(out["input"], [MANAGED] + items[:-1] + [TRIGGER])

    def test_after_a_compaction_only_what_follows_its_summary_is_new(self):
        again = [{**DEV, "id": "dev2"}, user("q", 1), SUMMARY, user("next", 2)]   # codex's window, started again
        self.assertEqual([e["payload"] for e in codex_format.to_events(again)], [user("next", 2)])
        self.assertEqual(len(codex_format.to_events([DEV, user("q", 1)])), 2)       # nothing compacted: all of it


if web is not None:
    class ProxyBase(unittest.IsolatedAsyncioTestCase):
        async def asyncSetUp(self):
            self.tmp = tempfile.TemporaryDirectory()
            self.saved = os.environ.get("AG_HOME")
            os.environ["AG_HOME"] = self.home = os.path.join(self.tmp.name, "ag")   # what a real server sees
            self.received, self.lines = [], []

            async def upstream(request):
                raw = await request.read()
                self.received.append((request.method, request.path_qs, json.loads(raw) if raw else None))
                if request.path.endswith("/responses"):
                    resp = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
                    await resp.prepare(request)
                    for frame in SSE.split(b"\n\n")[:-1]:
                        await resp.write(frame + b"\n\n")
                    await resp.write_eof()
                    return resp
                return web.json_response({"data": []})

            app = web.Application()
            app.router.add_route("*", "/{tail:.*}", upstream)
            self.upstream = TestServer(app)
            await self.upstream.start_server()

        async def start(self, hook, log_dir=None):
            self.hook = hook
            self.client = TestClient(TestServer(hook_server.make_app(str(self.upstream.make_url("")).rstrip("/"),
                                                                     hook, log_dir)))
            await self.client.start_server()

        async def asyncTearDown(self):
            await self.client.close()                     # the app's cleanup closes the hook: its servers stop
            await self.upstream.close()
            if self.saved is None:
                os.environ.pop("AG_HOME", None)
            else:
                os.environ["AG_HOME"] = self.saved
            self.tmp.cleanup()

        async def call(self, items, thread="t1", **extra):
            body = dict({"model": "m", "input": items, "stream": True}, **extra)
            headers = {"thread-id": thread} if thread else {}
            resp = await self.client.post("/v1/responses", json=body, headers=headers)
            return resp.status, await resp.read()

        def log(self, gatherer, line):
            self.lines.append((gatherer, line))
else:
    ProxyBase = unittest.TestCase


@unittest.skipIf(web is None, "the hook server needs aiohttp")
class FakeServerTest(ProxyBase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        FakeClient.made = []
        self.dir = os.path.join(self.tmp.name, "log")
        await self.start(codex_ag.CodexContextManager(ag_clients=AgClients(FakeClient), log=self.log), self.dir)

    async def test_the_input_is_the_server_s_and_the_stream_comes_back_unchanged(self):
        items = [DEV, env("/w"), user("q", 1)]
        status, body = await self.call(items)
        self.assertEqual((status, body), (200, SSE))                         # codex gets the model's answer as is
        method, path, sent = self.received[-1]
        self.assertEqual((method, path), ("POST", "/v1/responses"))
        self.assertEqual(sent["input"], [MANAGED] + items)                    # the model gets the server's context
        self.assertEqual((sent["model"], sent["stream"]), ("m", True))       # the rest of the body kept
        client, = FakeClient.made
        (op, request), = client.requests
        process = request.pop("process", None)                                  # who called: this test, on Linux
        self.assertEqual((op, request), ("rewrite", {"gatherer": "t1", "properties": {"channel": "t1", "cwd": "/w"}, "cwd": "/w",
                                                     "events": codex_format.to_events(items)}))   # the cwd from the environment context
        if os.path.isdir("/proc/net"):
            self.assertEqual(process["pid"], os.getpid())
        self.assertEqual(self.lines, [("t1", "[t1] 3 items in")])
        with open(os.path.join(self.dir, "0001.json")) as fh:
            record = json.load(fh)                                        # the hook server's log of the change
        self.assertEqual((record["body_in"]["input"], record["body_out"]["input"][1:]), (items, items))

    async def test_a_named_gatherer_takes_a_channel_per_thread(self):
        for thread, n in (("th1", 1), ("th2", 2)):
            resp = await self.client.post("/h/demo/v1/responses", json={"model": "m", "input": [user("q", n)]},
                                          headers={"thread-id": thread})
            self.assertEqual(resp.status, 200)
            await resp.read()
        self.assertEqual(self.received[-1][1], "/v1/responses")              # the prefix is not forwarded
        client, = FakeClient.made                                            # one gatherer: one server
        self.assertEqual([(b["gatherer"], b["properties"]["channel"]) for _, b in client.requests], [("demo", "th1"),
                                                                                     ("demo", "th2")])
        resp = await self.client.get("/h/demo/v1/models")                   # other paths: stripped, passed through
        self.assertEqual((resp.status, self.received[-1][:2]), (200, ("GET", "/v1/models")))

    async def test_a_server_per_session_started_once(self):
        await self.call([user("q", 1)], thread="t1")
        await self.call([user("q", 1), agent("a", 1), user("q2", 2)], thread="t1")
        await self.call([user("other", 9)], thread="t2")
        self.assertEqual([c.gatherer for c in FakeClient.made], ["t1", "t2"])
        self.assertEqual([len(c.requests) for c in FakeClient.made], [2, 1])
        await self.client.close()
        self.assertTrue(all(c.stopped for c in FakeClient.made))            # stopped with the hook server

    async def test_what_is_passed_through_untouched(self):
        items = [DEV, user("q", 1)]
        await self.call(items, thread=None)                                  # no thread id
        self.assertEqual(self.received[-1][2]["input"], items)
        await self.call([DEV])                                               # no user message
        self.assertEqual(self.received[-1][2]["input"], [DEV])
        resp = await self.client.get("/v1/models")                           # another path
        self.assertEqual((resp.status, await resp.json()), (200, {"data": []}))
        self.assertEqual(self.received[-1][:2], ("GET", "/v1/models"))
        self.assertEqual(FakeClient.made, [])                               # no server involved

    async def test_a_failing_server_leaves_the_request_alone(self):
        items = [DEV, user("q", 1)]
        for answer in ({"error": "server exited (1)"}, {"context": None, "note": "insert failed"}, "garbage"):
            FakeClient.made = []
            await self.call([user("warm", 0)], thread="f")                  # start the gatherer's client
            FakeClient.made[0].answer = lambda body, a=answer: a
            status, body = await self.call(items, thread="f")
            self.assertEqual((status, body), (200, SSE))
            self.assertEqual(self.received[-1][2]["input"], items)
            self.hook.ag_clients.by_gatherer.clear()


@unittest.skipIf(web is None, "the hook server needs aiohttp")
class RealServerTest(ProxyBase):
    """The real server behind the codex hook (`python -m
    ag.ag_harness.server`, one per gatherer, in a home of the test's own): a
    file the conversation mentions changes between two calls, and the second
    call's input ends with the notice."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        await self.start(codex_ag.CodexContextManager(log=self.log))

    def database(self, gatherer):
        return os.path.join(self.home, "gatherers", gatherer, "context.db")

    def channels(self, gatherer):
        conn = sqlite3.connect(self.database(gatherer))
        try:
            return {c for (c,) in conn.execute("SELECT DISTINCT p_channel FROM events")}
        finally:
            conn.close()

    async def named(self, items, thread, gatherer="demo"):
        resp = await self.client.post(f"/h/{gatherer}/v1/responses", json={"model": "m", "input": items},
                                      headers={"thread-id": thread})
        await resp.read()
        return self.received[-1][2]["input"]

    async def test_threads_of_a_named_gatherer_are_channels_and_both_hear_of_a_change(self):
        work = os.path.join(self.tmp.name, "work")
        os.makedirs(work)
        target = os.path.join(work, "a.py")
        with open(target, "w") as fh:
            fh.write("x = 1\n")
        one = [DEV, env(work), user("please read a.py", 1), *cat("a.py", 1)]
        two = [DEV, env(work), user("what is in a.py?", 7), *cat("a.py", 7)]
        await self.named(one, "th1")
        await self.named(two, "th2")
        with open(target, "a") as fh:
            fh.write("y = 2\n")
        sent1 = await self.named(one + [agent("ok", 1), user("and now?", 2)], "th1")   # th1's read finds it
        sent2 = await self.named(two + [agent("ok", 7), user("again?", 8)], "th2")     # th2 hears of it too
        parallel = lambda item: "another session working in parallel with you" in json.dumps(item)  # noqa: E731
        sent1, sent2 = ([i for i in sent if not parallel(i)] for sent in (sent1, sent2))  # the other's requests aside
        notice = lambda item: str(item.get("content", [{}])[0].get("text", "")).startswith(  # noqa: E731
            "File a.py was changed on disk")
        self.assertTrue(notice(sent1[-1]))                                    # found by th1's read: its newest
        at = [i for i, item in enumerate(sent2) if notice(item)]
        self.assertEqual(len(at), 1)                                          # th2 hears of it too, once,
        self.assertEqual(sent2[at[0] + 1:], [agent("ok", 7), user("again?", 8)])   # where it was stored
        self.assertNotIn("what is in a.py?", json.dumps(sent1[:-1]))           # each thread its own history
        self.assertEqual(self.channels("demo"), {"th1", "th2", None})         # one database; the change pooled
        self.assertFalse(os.path.exists(self.database("th1")))

    async def test_threads_in_other_directories_hear_only_of_their_own_files(self):
        dirs = [os.path.join(self.tmp.name, d) for d in ("repo_a", "repo_b")]
        for d in dirs:
            os.makedirs(d)
            with open(os.path.join(d, "notes.txt"), "w") as fh:
                fh.write("x\n")
        one = [DEV, env(dirs[0]), user("please read notes.txt", 1), *cat("notes.txt", 1)]
        two = [DEV, env(dirs[1]), user("what is in notes.txt?", 7), *cat("notes.txt", 7)]
        await self.named(one, "th1")
        await self.named(two, "th2")
        with open(os.path.join(dirs[0], "notes.txt"), "a") as fh:            # only repo_a's changes
            fh.write("y\n")
        await self.named(two + [agent("ok", 7), user("again?", 8)], "th2")    # th2 polls repo_b: nothing
        sent1 = await self.named(one + [agent("ok", 1), user("and now?", 2)], "th1")   # th1 finds repo_a's
        sent2 = await self.named(two + [agent("ok", 7), user("again?", 8), agent("ok", 8), user("still?", 9)], "th2")
        said = lambda sent: [i for i in sent if "was changed on disk" in json.dumps(i)]   # noqa: E731
        self.assertEqual(len(said(sent1)), 1)
        self.assertEqual(said(sent2), [])                                     # repo_b's notes.txt did not change

    async def test_a_file_change_reaches_the_model(self):
        work = os.path.join(self.tmp.name, "work")
        os.makedirs(work)
        target = os.path.join(work, "a.py")
        with open(target, "w") as fh:
            fh.write("x = 1\n")
        first = [DEV, env(work), user("please read a.py", 1), *cat("a.py", 1)]
        await self.call(first, thread="real")
        sent = self.received[-1][2]["input"]
        guide = [i for i in sent if json.dumps(i).find("About this context, from the gatherer.") >= 0]
        self.assertEqual(len(guide), 1)                                      # the gatherer guide, after the set-up
        self.assertEqual(sent.index(guide[0]), 2)
        self.assertEqual([i for i in sent if i not in guide], first)         # nothing else to add yet
        with open(target, "a") as fh:
            fh.write("y = 2\n")
        second = first + [agent("ok", 1), user("and now?", 2)]
        await self.call(second, thread="real")
        sent = [i for i in self.received[-1][2]["input"] if i not in guide]
        self.assertEqual(sent[:len(second)], second)
        self.assertEqual(sent[-1]["role"], "developer")
        self.assertTrue(sent[-1]["content"][0]["text"].startswith("File a.py was changed on disk"))
        self.assertEqual(self.channels("real"), {"real", None})              # the channel is the thread id too
        with open(os.path.join(self.home, "logs", "gatherers", "real", "server.log")) as fh:
            self.assertIn("events in", fh.read())                           # the server's log


if __name__ == "__main__":
    unittest.main()
