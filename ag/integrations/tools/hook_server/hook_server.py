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
stops. A URL's `/h/<label>/` may be followed by `/l/<n>/`: the hook's
`request.limit` is then `n` (the prefix is stripped before forwarding), the
harness's own limit for its calls. A hook with a `measured(request, tokens)` has it called (awaited) when
a POST's answer has come back whole, before the harness sees its end: `tokens`
is the call's input tokens as the answer reports them, cached ones included
(trace.py's reading of a Responses or Anthropic Messages answer), or None; the
`request` is the one it was given, with whatever it kept in `request.state`
(only a request it kept something on is measured). A URL starting
`/h/<label>/` gives the hook that label (the prefix is stripped before
forwarding): what the label means is the hook's to decide.
With `--log-dir`, each request the hook changed is written there as
NNNN.json: its body before and after, then the status and duration. With
`--trace-root`, every model call -- as the model got it, and its answer -- is
traced there (trace.py), each call
under the thread the first `--thread-header` it carries names.

Needs aiohttp.
"""

import argparse
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

from .trace import ModelTrace, response_of

HOP = {"host", "content-length", "transfer-encoding", "connection", "content-encoding", "accept-encoding"}
LABEL_PREFIX = re.compile(r"^/h/([A-Za-z0-9._-]+)(?=/|$)")
LIMIT_PREFIX = re.compile(r"^/l/([0-9]+)(?=/|$)")


@dataclass
class Request:
    """What a hook is given: one HTTP request, as the harness sent it."""
    method: str
    path: str                                   # with any /h/<label>/ prefix stripped
    label: Optional[str]                        # the <label> of /h/<label>/..., if the URL had one
    headers: dict = field(default_factory=dict)
    body: Any = None                            # the JSON body, or None if it is not JSON
    limit: Optional[int] = None                 # the <n> of /l/<n>/..., if the URL had one
    state: dict = field(default_factory=dict)   # the hook's own, kept until its `measured` for this request


def route_of(path: str):
    """(the label the URL names, or None; the path to forward):
    `/h/<label>/v1/chat` is label `label` and `/v1/chat`. A label
    is letters, digits, `.`, `_` and `-`."""
    match = LABEL_PREFIX.match(path)
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
        limit, path_qs = limit_of(path_qs)
        raw = await request.read()
        headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP}
        try:
            body = json.loads(raw) if raw else None
        except ValueError:
            body = None                                    # not JSON (e.g. compressed): as it is
        given = Request(request.method, path_qs.split("?", 1)[0], label, dict(request.headers), body, limit)
        try:
            new = await _call(hook, given)
        except Exception as exc:  # noqa: BLE001 - a failing hook never blocks the call
            print(f"#{n:04d} hook failed: {exc!r}; request unchanged", file=sys.stderr, flush=True)
            new = None
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
        answer = [] if call or measured else None
        timeout = ClientTimeout(total=None, sock_read=1800)
        status, error = None, None
        try:
            async with ClientSession(timeout=timeout, auto_decompress=True) as client:
                async with client.request(request.method, upstream + path_qs, data=raw, headers=headers) as up:
                    status = up.status
                    resp = web.StreamResponse(status=up.status, headers={
                        k: v for k, v in up.headers.items() if k.lower() not in HOP})
                    await resp.prepare(request)
                    async for chunk in up.content.iter_any():
                        if answer is not None:
                            answer.append(chunk)
                        await resp.write(chunk)
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
                    await resp.write_eof()
                    record["status"] = up.status
        except Exception as exc:
            error = repr(exc)
            raise
        finally:
            if call:                                          # the call broke off: what came back
                trace.completed(call[0], call[1], status, b"".join(answer or []), time.time() - record["t_start"],
                                error)
        record["seconds"] = time.time() - record["t_start"]
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
