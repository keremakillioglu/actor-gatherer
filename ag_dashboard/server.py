"""The dashboard's local server: the page (page.html) and the JSON it reads, from the
context manager's home (data.py), read-only. Standard library only.

    GET /                                 the page
    GET /api/home                         data.home()
    GET /api/agent?gatherer=G&channel=C   data.agent(G, C)
    GET /api/read?gatherer=G&read_id=N    data.read(G, N)
    GET /api/context?gatherer=G&read_id=N data.context(G, N)
    GET /api/history?gatherer=G&channel=C&from=A[&to=B]   data.history(G, C, A, B)
    GET /api/transcript?gatherer=G&channel=C[&after=A|&before=B]   data.transcript(G, C, A, B)
    GET /api/stream[?gatherer=G&channel=C]                 server-sent events, until the page goes:
        `home` (data.home()) and, with a channel, `agent` (data.agent(G, C)) at once, then again
        each time they change -- woken by ag's notifications or the fallback check (live.py) --
        and every KEEPALIVE seconds a comment, or `home` if the time alone changed it (Running/Idle)
    GET /api/sessions                     the sessions started from the page (sessions.py)
    GET /api/views                        the reader's own chat views: <home>/dashboard/views/*.js, by name
    GET /views/<name>.js                  one of them, which the page loads (page.html: chat views)
    POST /api/gatherers {name}            a new gatherer (`ag new`), no session yet -> {name}
    POST /api/sessions {gatherer, cwd?, permission_mode?}  a new one -> the session
    POST /api/send {session_id, text}     a message to its agent -> the session

The POSTs are the only writes, and only to the dashboard's own table, the agents it runs, and the
gatherers `ag new` makes:
the gatherers' databases are only read. They are taken from the dashboard's own page only
(`own_page`), and the server listens on localhost unless told otherwise.

`page(snapshot)` is the page itself, the libraries it renders markdown with (VENDOR: marked,
and DOMPurify to make what it makes safe) inside it, never fetched; with a snapshot
(data.snapshot()) it stands alone, its data inside it (`ag dashboard --out`)."""

import json
import os
import select
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlsplit

from . import data, home, live, sessions

PAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "page.html")
VENDOR = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor", n) for n in ("marked.min.js", "purify.min.js")]
LLM_SECONDS = 10.0          # how long the Gatherer's call log is reused before it is read again
KEEPALIVE = 15.0            # the most a stream stays silent
COALESCE = 0.03             # after a wake, how long to wait for the rest of a burst (a call stores many events)


def page(snapshot: Optional[dict] = None) -> str:
    """The page; with `snapshot`, its data inside it."""
    with open(PAGE, encoding="utf-8") as fh:
        text = fh.read()
    scripts = []
    for path in VENDOR:
        with open(path, encoding="utf-8") as fh:
            scripts.append("<script>" + fh.read().replace("</script", "<\\/script") + "</script>")
    text = text.replace("<!--VENDOR-->", "\n".join(scripts), 1)
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

    def changed(self) -> None:
        """A call was logged: read the log again next time."""
        with self.lock:
            self.at = 0.0


def _signature(value) -> str:
    """What a stream compares to send only a change: the value, less the time it was read at."""
    if isinstance(value, dict):
        value = {k: v for k, v in value.items() if k != "now"}
    return json.dumps(value, sort_keys=True, default=str)


def handler(calls: _Calls, hub: live.Hub, started: sessions.Sessions):
    def home_view() -> dict:
        """The home as the page gets it: with the sessions' state, and what the new-session form starts from."""
        return {**data.home(started.list()), "cwd": os.getcwd(), "permission_modes": list(sessions.PERMISSION_MODES)}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):      # quiet: one line per request is noise
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
                if url.path == "/api/stream":
                    return self.stream(q.get("gatherer"), q.get("channel"))
                if url.path == "/api/home":
                    return self.answer(home_view())
                if url.path == "/api/sessions":
                    return self.answer(started.list())
                if url.path == "/api/views":
                    return self.answer(home.view_names())
                if url.path.startswith("/views/"):
                    path = home.view_file(url.path[len("/views/"):])
                    if path is None:
                        return self.send(404, b"not found", "text/plain")
                    with open(path, "rb") as fh:
                        return self.send(200, fh.read(), "text/javascript; charset=utf-8")
                if url.path == "/api/agent" and q.get("gatherer") and "channel" in q:
                    return self.answer(data.agent(q["gatherer"], q["channel"], calls.get()))
                if url.path == "/api/read" and q.get("gatherer") and q.get("read_id", "").isdigit():
                    return self.answer(data.read(q["gatherer"], int(q["read_id"])))
                if url.path == "/api/context" and q.get("gatherer") and q.get("read_id", "").isdigit():
                    return self.answer(data.context(q["gatherer"], int(q["read_id"])))
                if url.path == "/api/history" and q.get("gatherer") and "channel" in q and q.get("from", "").isdigit() \
                        and q.get("to", "0").isdigit():
                    return self.answer(data.history(q["gatherer"], q["channel"], int(q["from"]),
                                                    int(q["to"]) if "to" in q else None))
                if url.path == "/api/transcript" and q.get("gatherer") and "channel" in q \
                        and q.get("after", "0").isdigit() and q.get("before", "0").isdigit():
                    return self.answer(data.transcript(q["gatherer"], q["channel"],
                                                       int(q["after"]) if "after" in q else None,
                                                       int(q["before"]) if "before" in q else None))
                return self.send(404, b"not found", "text/plain")
            except Exception as exc:  # noqa: BLE001 - the page shows the error and keeps its last view
                return self.send(500, json.dumps({"error": f"{type(exc).__name__}: {exc}"}).encode(), "application/json")

        def event(self, name: str, value) -> None:
            self.wfile.write(f"event: {name}\ndata: {json.dumps(value)}\n\n".encode("utf-8"))

        def gone(self) -> bool:
            """Whether the page closed the connection: it sends nothing more, so readable means closed."""
            try:
                if not select.select([self.connection], [], [], 0)[0]:
                    return False
                return self.connection.recv(1, socket.MSG_PEEK) == b""
            except (OSError, ValueError):
                return True

        def stream(self, gatherer: Optional[str], channel: Optional[str]) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            watch = hub.watch(gatherer, channel)
            sent = {}
            try:
                while True:
                    woken = watch.wake.wait(KEEPALIVE)
                    if self.gone():
                        return
                    if woken:
                        time.sleep(COALESCE)
                    home, agent = watch.take()
                    out = []
                    if home or not woken:                # unwoken: the time alone may have changed it
                        out.append(("home", home_view()))
                    if agent and gatherer and channel is not None:
                        out.append(("agent", data.agent(gatherer, channel, calls.get())))
                    wrote = False
                    for name, value in out:
                        sig = _signature(value)
                        if sent.get(name) != sig:
                            self.event(name, value)
                            sent[name], wrote = sig, True
                    if not wrote and not woken:
                        self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
            except OSError:                              # the page went away
                pass
            finally:
                hub.drop(watch)

        def own_page(self) -> bool:
            """Whether a POST comes from the dashboard's own page: JSON (which a page elsewhere can
            send only after a preflight this server never answers), from no other origin, to this
            host as named (not a name rebound to it)."""
            host = self.headers.get("Host") or ""
            origin = self.headers.get("Origin")
            return (self.headers.get("Content-Type") or "").split(";")[0].strip() == "application/json" \
                and (origin is None or urlsplit(origin).netloc == host) \
                and urlsplit("//" + host).hostname in ("127.0.0.1", "localhost", "::1", self.server.server_address[0])

        def do_POST(self):  # noqa: N802 - http.server's name
            url = urlsplit(self.path)
            if not self.own_page():
                return self.send(403, json.dumps({"error": "only the dashboard's own page may do that"}).encode(),
                                 "application/json")
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}") if 0 < length <= MAX_BODY else None
                if not isinstance(body, dict):
                    return self.send(400, json.dumps({"error": "a JSON object, please"}).encode(), "application/json")
                if url.path == "/api/gatherers":
                    return self.answer(sessions.new_gatherer(str(body.get("name") or "")))
                if url.path == "/api/sessions":
                    return self.answer(started.create(str(body.get("gatherer") or ""), str(body.get("cwd") or ""),
                                                      str(body.get("permission_mode") or "auto")))
                if url.path == "/api/send":
                    return self.answer(started.send(str(body.get("session_id") or ""), str(body.get("text") or "")))
                return self.send(404, b"not found", "text/plain")
            except (sessions.SessionError, ValueError) as exc:
                return self.send(400, json.dumps({"error": str(exc)}).encode(), "application/json")
            except Exception as exc:  # noqa: BLE001
                return self.send(500, json.dumps({"error": f"{type(exc).__name__}: {exc}"}).encode(), "application/json")

    return Handler


MAX_BODY = 1_000_000        # the largest request body taken: a message, not a file


class Server(ThreadingHTTPServer):
    """The HTTP server, with what wakes its streams (live.py) and the sessions started from the page
    (sessions.py), whose agents it runs: stopped with it."""

    daemon_threads = True               # an open stream never holds up the exit

    def __init__(self, address, live_updates: bool = True):
        self.calls, self.hub = _Calls(), live.Hub()
        self.hub.on_llm = self.calls.changed
        self.sessions = sessions.Sessions(on_change=self.hub.ring)     # a session's state: its gatherer's streams
        super().__init__(address, handler(self.calls, self.hub, self.sessions))
        self.listener = live.Listener(self.hub) if live_updates else None
        self.fallback = live.Fallback(self.hub) if live_updates else None

    def server_close(self) -> None:
        for part in (self.listener, self.fallback):
            if part is not None:
                part.close()
        super().server_close()
        self.sessions.close()


def serve(host: str = "127.0.0.1", port: int = 4200, live_updates: bool = True) -> Server:
    """The server, bound and ready (`serve_forever()` runs it); `server_close()` stops it, its
    listener and its sessions' agents. Without `live_updates`, streams are woken by nothing but
    their keep-alive (and the sessions' own changes)."""
    return Server((host, port), live_updates)
