"""A tap between a harness and ag's hook server: every request the harness sends -- its method, path, headers and
body, as the hook server gets them -- and the answer it gets back, appended to a JSON-lines file, the request relayed
unchanged. Started by wrap.py, one per hook server, for the probe (probe.py).

    python tap.py --target http://127.0.0.1:4113 --out calls.jsonl --port-file tap.port [--fail MARK]

`--fail MARK`: a model call whose last message in the user's name ends with a block holding MARK is answered 400 by the tap itself, an API error as
Anthropic's and OpenAI's APIs both word one -- each try of it, so the harness gives up on it and records the error.
Needs aiohttp (ag's own dependency)."""

import argparse
import asyncio
import json
import os
import socket
import time

from aiohttp import ClientSession, ClientTimeout, web

HOP = {"host", "content-length", "transfer-encoding", "connection", "content-encoding", "accept-encoding"}
ANSWER_BYTES = 1 << 21          # the most of an answer kept


def last_said(body) -> str:
    """The last block of a model call's last message in the user's name (Anthropic's `messages`, a Responses `input`),
    as JSON: a retry may add the harness's own notes after that message, and Claude Code adds the next message the user
    sends to it, as a block of its own, while the refused one has no answer."""
    if not isinstance(body, dict):
        return ""
    items = body.get("messages") if isinstance(body.get("messages"), list) else body.get("input")
    said = [i for i in items if isinstance(i, dict) and i.get("role") == "user"] if isinstance(items, list) else []
    content = said[-1].get("content") if said else None
    return json.dumps(content[-1] if isinstance(content, list) and content else content, ensure_ascii=False)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--port-file", required=True)
    ap.add_argument("--fail", default="")
    a = ap.parse_args()
    lock = asyncio.Lock()
    counter = iter(range(1, 1 << 30))

    async def write(record: dict) -> None:
        async with lock:
            with open(a.out, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    async def handle(request: web.Request) -> web.StreamResponse:
        n, raw = next(counter), await request.read()
        try:
            body = json.loads(raw) if raw else None
        except ValueError:
            body = None
        record = {"n": n, "t": time.time(), "method": request.method, "path": request.path_qs,
                  "headers": dict(request.headers), "body": body, "raw_bytes": len(raw)}
        if a.fail and request.method == "POST" and a.fail in last_said(body):
            error = {"type": "error", "error": {"type": "invalid_request_error", "message": "probe: refused on purpose"}}
            await write({**record, "status": 400, "answer": json.dumps(error), "injected": True})
            return web.json_response(error, status=400)
        headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP}
        chunks, status = [], None
        try:
            async with ClientSession(timeout=ClientTimeout(total=None, sock_read=1800), auto_decompress=True) as client:
                async with client.request(request.method, a.target + request.path_qs, data=raw, headers=headers) as up:
                    status = up.status
                    resp = web.StreamResponse(status=up.status, headers={k: v for k, v in up.headers.items()
                                                                         if k.lower() not in HOP})
                    await resp.prepare(request)
                    async for chunk in up.content.iter_any():
                        if sum(map(len, chunks)) < ANSWER_BYTES:
                            chunks.append(chunk)
                        await resp.write(chunk)
                    await resp.write_eof()
                    return resp
        finally:
            await write({**record, "status": status, "answer": b"".join(chunks).decode("utf-8", "replace"),
                         "ended": time.time()})

    app = web.Application(client_max_size=1 << 28)
    app.router.add_route("*", "/{tail:.*}", handle)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    with open(a.port_file + ".tmp", "w") as fh:
        fh.write(str(sock.getsockname()[1]))
    os.replace(a.port_file + ".tmp", a.port_file)
    web.run_app(app, sock=sock, print=None)


if __name__ == "__main__":
    main()
