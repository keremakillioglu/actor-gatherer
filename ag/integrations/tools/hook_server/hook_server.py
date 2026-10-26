"""A hook for a harness that has none: an HTTP server between the harness and
its model's endpoint that calls a given hook on every request and relays.

    harness --(HTTP)--> hook server --(HTTP)--> the model's endpoint
                          |    ^
                  Request |    | a new JSON body, or None
                          v    |
                          hook

A harness with no hook of its own is pointed at this server instead, which
gives it one. The server knows HTTP and nothing else: no messages, no gatherers, no context manager. For each
request, whatever its method or path, it reads the body, calls the hook with
it, forwards the hook's body -- or, when the hook returns None or fails, the
original bytes, untouched -- and streams the answer back as it arrives. A
WebSocket upgrade is answered 426 and not relayed: the hook sees HTTP bodies
only, so a harness that tries WebSockets first falls back to HTTP.

    python -m ag.integrations.tools.hook_server.hook_server --hook module:attr [--option KEY=VALUE ...]
                                            [--port 4013] [--upstream http://127.0.0.1:4011]
                                            [--log-dir DIR] [--trace-root DIR [--thread-header NAME ...]]
                                            [--path DIR ...]

`--hook` names the hook: an async callable taking a `Request` and returning a
new JSON body or None, or a class, built with the `--option`s, whose
instances are that. A hook with a `close()` has it called when the server
stops. A URL's `/h/<label>/` may be followed by `/r/<run>/`: the hook's `request.run` is then
`run` -- the one run of the harness (its process) the call came from, as its launcher named it,
whichever thread or session the call is in -- and then by `/l/<n>/`: the hook's
`request.limit` is then `n` (the prefixes are stripped before forwarding), the
harness's own limit for its calls. A hook with a `measured(request, tokens)` has it called (awaited) when
a POST's answer has come back whole, before the harness sees its end: `tokens`
is the call's input tokens as the answer reports them, cached ones included
(trace.py's reading of a Responses or Anthropic Messages answer), or None; the
`request` is the one it was given, with whatever it kept in `request.state`
(only a request it kept something on is measured). A hook with a `before_end(request, status, answer)`
has it called (awaited) then too, for the same requests, after `measured`: the answer as trace.py
reads it -- for a hook that acts before the harness acts on the answer (runs the tools it calls).
A hook with an `answered(request, status, answer)`
has it called (awaited) once a POST's answer has come back whole and the harness has seen its end,
for the same requests as `measured`: the HTTP status, and the answer as trace.py reads it
(`response_of`: {response_id, status, token_usage, output_items, error}) -- even if the harness
hung up before the stream's end was written, as a harness may once its answer is complete. A hook with a
`streamed(request, answer)` has it called, for the same requests, while the answer streams: each
time a part of it is complete (an Anthropic content block has ended, a Responses output item is
done), with the parts complete so far (trace.py's `streamed_of`: {response_id, output_items}) --
in the background, one call after another, so the answer is never held up for it, and all of them
done before `answered`. A hook with a
`failed(request, status, error)` has it called (awaited), for the same requests, when the call failed:
its endpoint answered an error -- a status other than 200, or an error in the answer (`status` that
status, `error` the endpoint's message) -- once the harness has it; or no answer came at all -- the
endpoint could not be reached, or did not answer -- (`status` None, `error` why). The harness is then
answered 502 with an error body readable as both Anthropic's and OpenAI's ({"type": "error", "error":
{"type", "message"}}), saying why, where it would otherwise get a bare 500. An answer that breaks off
once it has begun is not reported: the harness itself may have closed it (an interrupted turn). A URL starting
`/h/<label>/` gives the hook that label (the prefix is stripped before
forwarding): what the label means is the hook's to decide. `request.upstream` is
where the request goes (its path after it), for a hook that asks the same
endpoint something first, with the request's own headers.
A hook may answer the request itself, not relaying it, by returning an `Answer`
(its HTTP status and JSON body): a refusal, say.
With `--log-dir`, each request the hook changed is written there as
NNNN.json: its body before and after, then the status and duration. With
`--trace-root`, every model call -- as the model got it, and its answer -- is
traced there (trace.py), each call
under the thread the first `--thread-header` it carries names.

Needs aiohttp.
"""

import argparse
import asyncio
import importlib
import inspect
import itertools
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from aiohttp import ClientSession, ClientTimeout, web

from . import peer
from .trace import ModelTrace, response_of, streamed_of

HOP = {"host", "content-length", "transfer-encoding", "connection", "content-encoding", "accept-encoding"}
LABEL_PREFIX = re.compile(r"^/h/([A-Za-z0-9._-]+)(?=/|$)")
RUN_PREFIX = re.compile(r"^/r/([A-Za-z0-9._-]+)(?=/|$)")
LIMIT_PREFIX = re.compile(r"^/l/([0-9]+)(?=/|$)")
PART_DONE = (b'"content_block_stop"', b'"response.output_item.done"')   # a part of an answer is complete
ANSWER_DONE = (b'"message_stop"', b'"response.completed"')               # all of it: `answered` keeps it


@dataclass
class Request:
    """What a hook is given: one HTTP request, as the harness sent it."""
    method: str
    path: str                                   # with any /h/<label>/ prefix stripped
    label: Optional[str]                        # the <label> of /h/<label>/..., if the URL had one
    headers: dict = field(default_factory=dict)
    body: Any = None                            # the JSON body, or None if it is not JSON
    limit: Optional[int] = None                 # the <n> of /l/<n>/..., if the URL had one
    run: Optional[str] = None                   # the <run> of /r/<run>/..., if the URL had one: the harness's
                                                # run (its process) the call came from, as its launcher named it
    upstream: Optional[str] = None              # where the request is forwarded (path_qs after it)
    state: dict = field(default_factory=dict)   # the hook's own, kept until its `measured` for this request
    process: Optional[dict] = None              # who sent it: {"pid", "started"} of the harness's process
                                                # (peer.py); None: not told (not Linux, not this machine)
    answer_started: Optional[float] = None      # when the answer's first bytes came back (time.time()):
                                                # nothing it asks for can have run before


@dataclass
class Answer:
    """What a hook returns to answer the request itself: nothing is relayed."""
    status: int
    body: Any


#: What a call is reported as (`failed`) when the harness hung up before its answer was through -- the user stopped
#: it (Esc) -- not an error of its endpoint's: the status for it that nginx has, "client closed request".
HUNG_UP = 499
HUNG_UP_WHY = "the harness hung up before the answer was through: stopped by the user"


def hung_up(request) -> bool:
    """Whether the harness has hung up on `request`: its connection closing, or gone."""
    transport = request.transport
    return transport is None or transport.is_closing()


WATCH_SECONDS = 0.25     # while the answer's next bytes are awaited, how often the harness is looked at (`next_bytes`)


async def next_bytes(up, request) -> bytes:
    """The answer's next bytes from upstream (`up`), b"" at its end -- the harness looked at meanwhile: one that hung
    up raises ConnectionResetError then, not when the next bytes come, which while the model thinks can be seconds."""
    got = asyncio.ensure_future(up.content.readany())
    while True:
        done, _ = await asyncio.wait({got}, timeout=WATCH_SECONDS)
        if done:
            return got.result()
        if hung_up(request):
            got.cancel()
            raise ConnectionResetError("the harness hung up")


def route_of(path: str):
    """(the label the URL names, or None; the path to forward):
    `/h/<label>/v1/chat` is label `label` and `/v1/chat`. A label
    is letters, digits, `.`, `_` and `-`."""
    match = LABEL_PREFIX.match(path)
    if not match:
        return None, path
    return match.group(1), path[match.end():] or "/"


def run_of(path: str):
    """(the run the URL names, or None; the path to forward): `/r/<run>/v1/chat`, after any label,
    is run `run` and `/v1/chat` -- the harness's run (its process) the call came from, as its launcher
    named it. A run is letters, digits, `.`, `_` and `-`."""
    match = RUN_PREFIX.match(path)
    if not match:
        return None, path
    return match.group(1), path[match.end():] or "/"


def limit_of(path: str):
    """(the limit the URL states, or None; the path to forward): `/l/<n>/v1/chat`, after
    any label, is limit `n` and `/v1/chat` -- the harness's own limit for its calls, in
    its provider's tokens, as its launcher found it."""
    match = LIMIT_PREFIX.match(path)
    if not match or not int(match.group(1)):
        return None, path
    return int(match.group(1)), path[match.end():] or "/"


async def _call(hook: Callable, request: Request):
    result = hook(request)
    return await result if inspect.isawaitable(result) else result


async def _report(n: int, name: str, method: Callable, *args) -> None:
    """Call a hook's report (`failed`, ...), awaited if it must be; a failing one is logged, never raised."""
    try:
        result = method(*args)
        if inspect.isawaitable(result):
            await result
    except Exception as exc:  # noqa: BLE001 - a lost report never breaks the answer
        print(f"#{n:04d} {name} failed: {exc!r}", file=sys.stderr, flush=True)


class Parts:
    """A hook's `streamed` for one answer: called each time a chunk relayed completes a part of it
    (PART_DONE) -- not the chunk that ends it (ANSWER_DONE), `answered`'s -- with the parts complete so
    far: in the background, each call after the one before."""

    def __init__(self, n: int, method: Callable, request: Request):
        self.n, self.method, self.request = n, method, request
        self.tail, self.parts, self.task = b"", 0, None

    def chunk(self, chunk: bytes, answer: list) -> None:
        """`chunk` was relayed; `answer`, every chunk so far."""
        seen, self.tail = self.tail + chunk, chunk[-64:]           # a marker split across two chunks
        if not any(marker in seen for marker in PART_DONE) or any(marker in seen for marker in ANSWER_DONE):
            return
        read = streamed_of(b"".join(answer))
        if len(read["output_items"]) <= self.parts:
            return
        self.parts = len(read["output_items"])
        self.task = asyncio.ensure_future(self.report(self.task, read))

    async def report(self, before, read: dict) -> None:
        if before is not None:
            await before
        await _report(self.n, "streamed", self.method, self.request, read)

    async def done(self) -> None:
        """Once every call made so far has returned."""
        if self.task is not None:
            await self.task


def error_of(status: Optional[int], read: Optional[dict], raw: bytes) -> str:
    """Why a call failed, from its answer: its error's type and message as the endpoint gave them
    (Anthropic's and OpenAI's errors both have them), else the start of what came back, else its status."""
    err = (read or {}).get("error")
    if isinstance(err, dict):
        kind, message = err.get("type") or err.get("code"), err.get("message")
        if message:
            return f"{kind}: {message}" if kind else str(message)
        if kind:
            return str(kind)
    elif isinstance(err, str) and err:
        return err
    text = raw.decode("utf-8", errors="replace").strip()
    return text[:500] if text else f"HTTP {status}"


def input_tokens_of(raw: bytes) -> Optional[int]:
    """The call's input tokens, cached ones included, from the answer's bytes; None if it reports none."""
    usage = response_of(raw).get("token_usage") or {}
    tokens = usage.get("input_tokens")
    return tokens if isinstance(tokens, int) and tokens > 0 else None


def make_app(upstream: str, hook: Callable, log_dir: Optional[str] = None,
             trace_root: Optional[str] = None, thread_headers=()) -> web.Application:
    """The hook server as an aiohttp application forwarding to `upstream`
    (e.g. http://127.0.0.1:4011)."""
    counter = itertools.count(1)
    trace = ModelTrace(trace_root) if trace_root else None
    senders = {}                                # connection -> its process: found once, on its first request

    def sender(request: web.Request) -> Optional[dict]:
        transport = request.transport
        if transport is None:
            return None
        at, me = transport.get_extra_info("peername"), transport.get_extra_info("sockname")
        key = (id(transport), tuple(at) if isinstance(at, (tuple, list)) else at)
        if key not in senders or senders[key] is not None and not peer.alive(senders[key]):
            if len(senders) > 1000:             # connections long closed
                senders.clear()
            senders[key] = peer.process_of(at, me)
        return senders[key]
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    def save(n: int, record: dict) -> None:
        with open(os.path.join(log_dir, f"{n:04d}.json"), "w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=1, ensure_ascii=False)

    async def handle(request: web.Request):
        if request.headers.get("Upgrade", "").lower() == "websocket":
            return web.Response(status=426, text="WebSockets are not relayed: use HTTP")
        n = next(counter)
        label, path_qs = route_of(request.path_qs)
        run, path_qs = run_of(path_qs)
        limit, path_qs = limit_of(path_qs)
        raw = await request.read()
        headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP}
        try:
            body = json.loads(raw) if raw else None
        except ValueError:
            body = None                                    # not JSON (e.g. compressed): as it is
        given = Request(request.method, path_qs.split("?", 1)[0], label, dict(request.headers), body, limit,
                        upstream=upstream, process=sender(request), run=run)
        try:
            new = await _call(hook, given)
        except Exception as exc:  # noqa: BLE001 - a failing hook never blocks the call
            print(f"#{n:04d} hook failed: {exc!r}; request unchanged", file=sys.stderr, flush=True)
            new = None
        if isinstance(new, Answer):
            print(f"#{n:04d} {request.method} {request.path_qs} answered by the hook: {new.status}", flush=True)
            return web.json_response(new.body, status=new.status)
        record = {"n": n, "method": request.method, "path": request.path_qs, "label": label, "t_start": time.time()}
        if new is not None:
            raw = json.dumps(new).encode()
            record.update(body_in=body, body_out=new)
        print(f"#{n:04d} {request.method} {request.path_qs} {'hooked' if new is not None else 'passed through'}",
              flush=True)
        if log_dir and new is not None:
            save(n, record)                               # what was sent, before the answer streams
        sent = new if new is not None else body
        call = None
        if trace is not None and request.method == "POST" and isinstance(sent, dict):
            thread = next((request.headers[h] for h in thread_headers if request.headers.get(h)), None)
            call = (trace.started(n, path_qs, label, thread, sent, new is not None), thread)

        measured = getattr(hook, "measured", None) if request.method == "POST" and given.state else None
        answered = getattr(hook, "answered", None) if request.method == "POST" and given.state else None
        before_end = getattr(hook, "before_end", None) if request.method == "POST" and given.state else None
        failed = getattr(hook, "failed", None) if request.method == "POST" and given.state else None
        streamed = getattr(hook, "streamed", None) if request.method == "POST" and given.state else None
        parts = Parts(n, streamed, given) if streamed else None
        answer = [] if call or measured or answered or before_end or failed or streamed else None
        if hung_up(request):                              # stopped while the hook ran (Esc, as ag read): no model call
            print(f"#{n:04d} the harness hung up before the call went on: not sent", flush=True)
            if call:
                trace.completed(call[0], call[1], None, b"", time.time() - record["t_start"], HUNG_UP_WHY)
            if failed:
                await _report(n, "failed", failed, given, HUNG_UP, HUNG_UP_WHY)
            return web.Response(status=HUNG_UP)           # to no one: the server drops it
        timeout = ClientTimeout(total=None, sock_read=1800)
        status, error, resp = None, None, None
        try:
            async with ClientSession(timeout=timeout, auto_decompress=True) as client:
                async with client.request(request.method, upstream + path_qs, data=raw, headers=headers) as up:
                    status = up.status
                    resp = web.StreamResponse(status=up.status, headers={
                        k: v for k, v in up.headers.items() if k.lower() not in HOP})
                    await resp.prepare(request)
                    while True:
                        chunk = await next_bytes(up, request)
                        if not chunk:
                            break
                        if given.answer_started is None:
                            given.answer_started = time.time()
                        if answer is not None:
                            answer.append(chunk)
                        await resp.write(chunk)
                        if parts is not None:
                            parts.chunk(chunk, answer)
                    whole = b"".join(answer) if answer is not None else b""
                    if call:                                  # traced before the harness sees the end
                        trace.completed(call[0], call[1], status, whole, time.time() - record["t_start"])
                        call = None
                    if measured:                              # counted before the harness sees the end
                        try:
                            result = measured(given, input_tokens_of(whole) if status == 200 else None)
                            if inspect.isawaitable(result):
                                await result
                        except Exception as exc:  # noqa: BLE001 - a lost count never breaks the answer
                            print(f"#{n:04d} measured failed: {exc!r}", file=sys.stderr, flush=True)
                    read = response_of(whole) if before_end or answered or failed else None
                    if before_end:                            # before the harness sees the end
                        try:
                            result = before_end(given, status, read)
                            if inspect.isawaitable(result):
                                await result
                        except Exception as exc:  # noqa: BLE001 - never breaks the answer
                            print(f"#{n:04d} before_end failed: {exc!r}", file=sys.stderr, flush=True)
                    try:
                        await resp.write_eof()
                    except ConnectionResetError:              # the harness hung up once it had the whole answer
                        pass                                  # (as some do, at its end): the answer is still its
                    record["status"] = up.status
                    if failed and (status != 200 or (read or {}).get("error")):   # after the harness has it
                        await _report(n, "failed", failed, given, status, error_of(status, read, whole))
                    if parts is not None:                     # the parts kept before the whole answer is
                        await parts.done()
                    if answered:                              # after the harness has the answer: it waits on nothing
                        try:
                            result = answered(given, status, read)
                            if inspect.isawaitable(result):
                                await result
                        except Exception as exc:  # noqa: BLE001 - the answer is already the harness's
                            print(f"#{n:04d} answered failed: {exc!r}", file=sys.stderr, flush=True)
        except Exception as exc:
            error = repr(exc)
            if hung_up(request):                              # stopped as the answer came (Esc): the model's call
                print(f"#{n:04d} the harness hung up as the answer came: broken off", flush=True)   # given up with it
                if failed:
                    await _report(n, "failed", failed, given, HUNG_UP, HUNG_UP_WHY)
                if parts is not None:
                    await parts.done()
                return resp if resp is not None else web.Response(status=HUNG_UP)
            if resp is not None:                              # the answer had begun: it breaks off
                raise
            why = str(exc) or type(exc).__name__
        finally:
            if call:                                          # the call broke off: what came back
                trace.completed(call[0], call[1], status, b"".join(answer or []), time.time() - record["t_start"],
                                error)
        record["seconds"] = time.time() - record["t_start"]
        if resp is None:                                      # no answer came: the harness is told why
            print(f"#{n:04d} {request.method} {request.path_qs}: no answer from {upstream}: {why}",
                  file=sys.stderr, flush=True)
            record.update(status=502, error=why)
            if log_dir and new is not None:
                save(n, record)
            if failed:
                await _report(n, "failed", failed, given, None, why)
            return web.json_response({"type": "error", "error": {
                "type": "api_error", "message": f"ag's hook server got no answer from {upstream}: {why}"}}, status=502)
        if log_dir and new is not None:
            save(n, record)                               # and how it went
        return resp

    app = web.Application(client_max_size=1 << 30)
    app.router.add_route("*", "/{tail:.*}", handle)

    async def closing(app):
        if trace is not None:
            trace.close()
        close = getattr(hook, "close", None)
        if close is not None:
            result = close()
            if inspect.isawaitable(result):
                await result
    app.on_cleanup.append(closing)
    return app


def serve(hook: Callable, port: int = 4013, upstream: str = "http://127.0.0.1:4011",
          log_dir: Optional[str] = None, trace_root: Optional[str] = None, thread_headers=()) -> None:
    """Run the hook server on 127.0.0.1:`port` until interrupted."""
    web.run_app(make_app(upstream, hook, log_dir, trace_root, thread_headers), host="127.0.0.1", port=port,
                print=None)


def load_hook(spec: str, options: dict, paths=()) -> Callable:
    """The hook `module:attr` names: the attribute itself, or -- a class --
    an instance of it built with `options`."""
    for path in paths:
        if path not in sys.path:
            sys.path.insert(0, path)
    module, _, attr = spec.partition(":")
    obj = getattr(importlib.import_module(module), attr)
    if inspect.isclass(obj):
        return obj(**options)
    if options:
        raise ValueError(f"{spec} is not a class: it takes no --option")
    return obj


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ag.integrations.tools.hook_server.hook_server")
    ap.add_argument("--hook", required=True, help="module:attr, the hook (or a class of hooks)")
    ap.add_argument("--option", action="append", default=[], metavar="KEY=VALUE",
                    help="given to the hook's class, if it is one")
    ap.add_argument("--path", action="append", default=[], help="put on sys.path first, for --hook")
    ap.add_argument("--port", type=int, default=4013)
    ap.add_argument("--upstream", default="http://127.0.0.1:4011")
    ap.add_argument("--log-dir", help="write each request the hook changed, before and after, as NNNN.json")
    ap.add_argument("--trace-root", help="trace every model call, as the model got it and its answer (trace.py)")
    ap.add_argument("--thread-header", action="append", default=[], metavar="NAME",
                    help="a request header naming the harness's thread, for the trace; the first present wins")
    a = ap.parse_args(argv)
    options = dict(o.split("=", 1) for o in a.option)
    hook = load_hook(a.hook, options, a.path)
    print(f"hook server :{a.port} -> {a.upstream}, calling {a.hook}", flush=True)
    serve(hook, a.port, a.upstream, a.log_dir, a.trace_root, a.thread_header)
    return 0


if __name__ == "__main__":
    sys.exit(main())
