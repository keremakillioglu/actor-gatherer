"""The dashboard's local server: the page (page.html) and the JSON it reads, from the
context manager's home (data.py), read-only. Standard library only.

    GET /                                 the page
    GET /api/home                         data.home()
    GET /api/agent?gatherer=G&channel=C   data.agent(G, C)
    GET /api/read?gatherer=G&read_id=N    data.read(G, N)

`page(snapshot)` is the page itself; with a snapshot (data.snapshot()) it stands alone,
its data inside it (`ag dashboard --out`)."""

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlsplit

from . import data

PAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "page.html")
LLM_SECONDS = 10.0          # how long the Gatherer's call log is reused before it is read again


def page(snapshot: Optional[dict] = None) -> str:
    """The page; with `snapshot`, its data inside it."""
    with open(PAGE, encoding="utf-8") as fh:
        text = fh.read()
    if snapshot is None:
        return text
    embedded = json.dumps(snapshot).replace("</", "<\\/")      # never closes the script it sits in
    return text.replace("/*SNAPSHOT*/null", embedded, 1)


class _Calls:
    """The Gatherer's call log, read at most every LLM_SECONDS: polling reads it often."""

    def __init__(self):
        self.lock, self.at, self.calls = threading.Lock(), 0.0, []

    def get(self):
        with self.lock:
            if time.time() - self.at > LLM_SECONDS:
                self.calls, self.at = data.llm_calls(), time.time()
            return self.calls


def handler(calls: _Calls):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):      # quiet: the page polls every few seconds
            pass

        def send(self, status: int, body: bytes, kind: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def answer(self, value) -> None:
            self.send(200, json.dumps(value).encode("utf-8"), "application/json")

        def do_GET(self):  # noqa: N802 - http.server's name
            url = urlsplit(self.path)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            try:
                if url.path in ("/", "/index.html"):
                    return self.send(200, page().encode("utf-8"), "text/html; charset=utf-8")
                if url.path == "/api/home":
                    return self.answer(data.home())
                if url.path == "/api/agent" and q.get("gatherer") and "channel" in q:
                    return self.answer(data.agent(q["gatherer"], q["channel"], calls.get()))
                if url.path == "/api/read" and q.get("gatherer") and q.get("read_id", "").isdigit():
                    return self.answer(data.read(q["gatherer"], int(q["read_id"])))
                return self.send(404, b"not found", "text/plain")
            except Exception as exc:  # noqa: BLE001 - the page shows the error and keeps its last view
                return self.send(500, json.dumps({"error": f"{type(exc).__name__}: {exc}"}).encode(), "application/json")

    return Handler


def serve(host: str = "127.0.0.1", port: int = 4200) -> ThreadingHTTPServer:
    """The server, bound and ready (`serve_forever()` runs it)."""
    return ThreadingHTTPServer((host, port), handler(_Calls()))
