"""The server's lanes (`ag.ag_harness.server.serve`): a session's requests answered one at a time, in
the order they came; different sessions' side by side, so a read that waits holds up only its own."""

import io
import json
import os
import random
import sqlite3
import sys
import tempfile
import threading
import time
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from ag.ag_harness import home as ag_home  # noqa: E402
from ag.ag_harness.server import Server, serve  # noqa: E402
from ag.ag_harness.server.__main__ import server_for  # noqa: E402
from ag.ag_harness.store import paths, schema  # noqa: E402
from ag.integrations.harnesses.codex.adaptor import to_events as codex  # noqa: E402

WAIT = 10        # seconds: how long a test waits for what should come at once


class Stub:
    """A manager whose reads the test controls: `read_logged` runs `hold(properties, row)` first."""

    name = "stub"

    def __init__(self, hold, handled):
        self.hold, self.handled = hold, handled

    def init(self, gatherer):
        pass

    def set_pollers(self, pollers):
        pass

    def read_logged(self, gatherer, row, *, properties=None, **_):
        self.hold(properties, row)
        self.handled.append(((properties or {}).get("channel"), row))
        return [{"type": "x", "id": str(row), "payload": {"row": row, "pad": "y" * 20000}}], row, {}


class StubServer(Server):
    """A gatherer whose sessions are told apart by `channel` (as one whose types declare it identifying)."""

    def __init__(self, hold=lambda properties, row: None):
        self.handled = []
        super().__init__(lambda gatherer: Stub(hold, self.handled))

    def identifying(self, gatherer):
        return ("channel",)


def read(channel, row, **more):
    request = {"op": "read", "gatherer": "g", "row": row, **more}
    if channel is not None:
        request["properties"] = {"channel": channel}
    return request


class Out(io.StringIO):
    """stdout as the harness reads it: each write in pieces, the thread switching between them -- a line
    two lanes wrote at once would come out mixed -- and each whole line seen, as it is."""

    def __init__(self):
        super().__init__()
        self.seen, self.changed = [], threading.Condition()

    def write(self, text):
        for i in range(0, len(text), 4096):
            super().write(text[i:i + 4096])
            time.sleep(0)
        return len(text)

    def flush(self):
        with self.changed:
            self.seen = [json.loads(line) for line in self.getvalue().splitlines()]
            self.changed.notify_all()

    def wait_for(self, ids):
        """Once every one of `ids` is answered (failing the test after WAIT seconds)."""
        with self.changed:
            if not self.changed.wait_for(lambda: set(ids) <= {a["id"] for a in self.seen}, WAIT):
                raise AssertionError(f"not answered: {sorted(set(ids) - {a['id'] for a in self.seen})}")


def in_background(server, requests, out, **kwargs):
    lines = [json.dumps(dict(r, id=i)) for i, r in enumerate(requests, 1)] if isinstance(requests, list) else requests
    done = threading.Thread(target=serve, args=(server, lines, out), kwargs=kwargs, daemon=True)
    done.start()
    return done


class LanesTest(unittest.TestCase):
    def test_a_session_that_waits_holds_up_no_other(self):
        release = threading.Event()
        server = StubServer(lambda properties, row: release.wait(WAIT) if properties == {"channel": "a"} else None)
        out = Out()
        done = in_background(server, [read("a", 1), read("b", 2), read("b", 3), read(None, 4), {"op": "ping"}], out)
        try:
            out.wait_for([2, 3, 4, 5])                 # b's, the gatherer's with no session, and the ping
            self.assertNotIn(1, [a["id"] for a in out.seen])
        finally:
            release.set()
        done.join(WAIT)
        self.assertFalse(done.is_alive())
        self.assertEqual([a["id"] for a in out.seen][-1], 1)

    def test_a_session_s_requests_are_answered_in_the_order_they_came(self):
        def hold(properties, row):
            time.sleep(random.uniform(0, 0.01) if row % 2 else 0.03 / row)    # the later, the quicker
        server = StubServer(hold)
        requests = [read(channel, row) for row in range(1, 41) for channel in ("a", "b", "c")
                    if (row + ord(channel)) % 3]
        out = Out()
        serve(server, [json.dumps(dict(r, id=i)) for i, r in enumerate(requests, 1)], out)
        for channel in ("a", "b", "c"):
            sent = [i for i, r in enumerate(requests, 1) if r["properties"]["channel"] == channel]
            self.assertEqual([a["id"] for a in out.seen if a["id"] in sent], sent)          # answered in turn
            self.assertEqual([row for c, row in server.handled if c == channel],
                             [r["row"] for r in requests if r["properties"]["channel"] == channel])   # and run in turn

    def test_every_request_is_answered_once_whole_with_its_id(self):
        server = StubServer(lambda properties, row: time.sleep(random.uniform(0, 0.005)))
        requests = [read(f"s{n % 12}", n) for n in range(1, 121)] + [{"op": "dance", "gatherer": "g"}]
        out = Out()
        serve(server, [json.dumps(dict(r, id=i)) for i, r in enumerate(requests, 1)] + ["not json", "[1]"], out)
        lines = out.getvalue().splitlines()
        answers = [json.loads(line) for line in lines]                  # each line one JSON answer, unmixed
        self.assertEqual(len(lines), len(requests) + 2)
        self.assertEqual(sorted(a["id"] for a in answers if a["id"] is not None), list(range(1, len(requests) + 1)))
        for a in answers:
            if a["id"] is not None and a["id"] <= 120:
                self.assertEqual(a["context"][0]["payload"], {"row": a["id"], "pad": "y" * 20000})
        self.assertEqual(sum(1 for a in answers if a["id"] is None and "error" in a), 2)   # the two that are no request

    def test_serve_returns_once_every_request_is_answered(self):
        server = StubServer(lambda properties, row: time.sleep(0.2))
        out = Out()
        began = time.monotonic()
        serve(server, [json.dumps(dict(read(c, n), id=n)) for n, c in enumerate("aabbc", 1)], out)   # linger: 60 s
        self.assertEqual(sorted(a["id"] for a in out.seen), [1, 2, 3, 4, 5])
        self.assertLess(time.monotonic() - began, WAIT)                    # lanes left idle do not linger on
        self.assertEqual([t.name for t in threading.enumerate() if t.name.startswith("ag lane")], [])

    def test_requests_wait_while_the_gatherer_s_sessions_are_not_told_apart(self):
        """A new gatherer's requests run in one lane until its database says what tells its sessions
        apart; one after that waits for those before it, instead of running beside them."""
        started, release, known = threading.Event(), threading.Event(), threading.Event()

        def hold(properties, row):
            if row == 1:
                known.set()                            # its database is made, with its types
                started.set()
                release.wait(WAIT)

        class New(StubServer):
            def identifying(self, gatherer):
                return ("channel",) if known.is_set() else None

        def lines():
            yield json.dumps(dict(read("a", 1), id=1))
            started.wait(WAIT)
            yield json.dumps(dict(read("a", 2), id=2))     # a's next, and b's: by session now, after 1
            yield json.dumps(dict(read("b", 3), id=3))

        server, out = New(hold), Out()
        done = in_background(server, lines(), out)
        started.wait(WAIT)
        time.sleep(0.3)
        self.assertEqual(out.seen, [])
        self.assertEqual(server.handled, [])
        release.set()
        done.join(WAIT)
        self.assertEqual(sorted(a["id"] for a in out.seen), [1, 2, 3])
        self.assertEqual(server.handled[0], ("a", 1))

    def test_a_broken_stdout_ends_serving(self):
        class Closed(io.StringIO):
            def write(self, text):
                raise BrokenPipeError("the harness is gone")
        with self.assertRaises(BrokenPipeError):
            serve(StubServer(), [json.dumps(dict(read("a", 1), id=1)), json.dumps(dict(read("b", 2), id=2))], Closed())


class GathererTest(unittest.TestCase):
    """Sessions side by side on a real gatherer: one sqlite file, written from a thread per session."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = paths.TRACE_DIR, paths.AG_HOME, os.environ.get("AG_HOME")
        paths.AG_HOME = os.environ["AG_HOME"] = os.path.join(self.tmp.name, "ag")    # a worker started finds it too
        paths.TRACE_DIR = os.path.join(paths.AG_HOME, "gatherers")
        ag_home._HOMES.clear()

    def tearDown(self):
        schema.release()
        paths.TRACE_DIR, paths.AG_HOME, home = self.saved
        if home is None:
            os.environ.pop("AG_HOME", None)
        else:
            os.environ["AG_HOME"] = home
        ag_home._HOMES.clear()
        self.tmp.cleanup()

    @staticmethod
    def user(text, n):
        return {"type": "message", "role": "user", "id": f"u{n}", "content": [{"type": "input_text", "text": text}]}

    @staticmethod
    def agent(text, n):
        return {"type": "message", "role": "assistant", "id": f"a{n}",
                "content": [{"type": "output_text", "text": text}]}

    def ask(self, requests):
        out = io.StringIO()
        serve(server_for(), [json.dumps(dict(r, id=i)) for i, r in enumerate(requests, 1)], out)
        return sorted((json.loads(line) for line in out.getvalue().splitlines()), key=lambda a: a["id"])

    def test_sessions_write_and_read_one_gatherer_at_once(self):
        self.ask([{"op": "rewrite", "gatherer": "g", "properties": {"channel": "c0"},
                   "events": codex.to_events([self.user("start", 0)])}])            # the gatherer, made
        lanes, answer = set(), Server.answer

        def seen(server, request):
            lanes.add(threading.current_thread().name)
            return answer(server, request)
        requests = []
        for turn in range(1, 6):
            for c in ("c1", "c2", "c3"):
                history = [m for k in range(1, turn + 1) for m in (self.user(f"{c} {k}", k), self.agent(f"ok {k}", k))]
                session = {"gatherer": "g", "properties": {"channel": c}}
                requests += [
                    {"op": "rewrite", **session, "events": codex.to_events(history[:-1])},
                    {"op": "pending", **session, "events": codex.to_events(history[-1:]), "answer": f"{c}-{turn}",
                     "stop": "end_turn"},
                    {"op": "insert", **session, "events": [{"type": f"note_{c}", "id": f"n{turn}", "payload": turn}]},
                    {"op": "latest", **session, "n": 2}]
        Server.answer = seen
        try:
            answers = self.ask(requests)
        finally:
            Server.answer = answer
        self.assertEqual([a["id"] for a in answers], list(range(1, len(requests) + 1)))
        failed = [a for a in answers if a.get("error") or ("context" in a and a["context"] is None)]
        self.assertEqual(failed, [])                                             # no "database is locked"
        self.assertGreater(len(lanes), 2)                                        # a lane per session
        conn = sqlite3.connect(paths.db_path("g"))
        try:
            for c in ("c1", "c2", "c3"):
                ids = [e for (e,) in conn.execute("SELECT event_id FROM events WHERE p_channel = ?", (c,))]
                self.assertEqual(len(ids), len(set(ids)))                        # each event once
                self.assertEqual(len(ids), 9 + 5)               # 5 turns' messages but the last answer; 5 notes
        finally:
            conn.close()

    def test_threads_insert_and_read_at_once(self):
        """Each thread its own connection (`schema.connection`), each waiting for the others' writes."""
        from ag.ag_interface import Event
        ag_home.manager("g").init("g")
        errors = []

        def work(c):
            try:
                manager = ag_home.manager("g")
                manager.policy.jobs = None                  # no check or build started: reads alone
                manager.init("g")
                types = {t.name: t.id for t in manager.event_types("g")}
                for n in range(60):
                    row = manager.insert("g", Event(types["user_message"], {"n": n}, id=f"{c}-{n}",
                                                    properties={"channel": c}, text=f"message {n} of {c}"))
                    self.assertIsNotNone(row)
                    if n % 10 == 9:
                        manager.read_logged("g", row, properties={"channel": c})
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))
            finally:
                schema.release()
        threads = [threading.Thread(target=work, args=(f"t{i}",)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        self.assertEqual(errors, [])
        conn = sqlite3.connect(paths.db_path("g"))
        try:
            self.assertEqual(conn.execute("SELECT count(*) FROM events").fetchone()[0], 240)
            self.assertEqual(conn.execute("SELECT count(*) FROM _reads").fetchone()[0], 24)
        finally:
            conn.close()

    def test_a_connection_is_a_thread_s_own(self):
        here = schema.connection("g")
        self.assertIs(schema.connection("g"), here)
        there = []
        t = threading.Thread(target=lambda: (there.append(schema.connection("g")), schema.release()))
        t.start()
        t.join()
        self.assertIsNot(there[0], here)
        with self.assertRaises(sqlite3.ProgrammingError):
            there[0].execute("SELECT 1")                                # closed as its thread ended
        schema.release()
        self.assertIsNone(schema.opened("g"))


if __name__ == "__main__":
    unittest.main()
