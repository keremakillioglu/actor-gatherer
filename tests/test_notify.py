"""Listeners: whoever watches a gatherer (the dashboard) binds a socket in the home's listeners/
folder and is told, by one datagram per write, after it commits, what of which gatherer and
channel changed -- so it can show the change at once instead of polling the database."""
import json
import os
import socket
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ag.ag_harness.store import operations as store  # noqa: E402
from ag.ag_harness.store import paths  # noqa: E402
from ag.ag_harness.store.notify import listeners_dir  # noqa: E402
from ag.ag_policies.proactive_context_manager import tables  # noqa: E402
from ag.ag_tools import notify as doorbell  # noqa: E402
from ag.ag_tools.llm.calllog import JOB_ENV, CallLog  # noqa: E402
from test_core import PREAMBLE, Base, conversation, user  # noqa: E402
from channels import ch  # noqa: E402


class Listener:
    """A socket bound in `folder`, as a dashboard's would be."""

    def __init__(self, folder, name="t.sock"):
        os.makedirs(folder, exist_ok=True)
        self.path = os.path.join(folder, name)
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.sock.bind(self.path)
        self.sock.setblocking(False)

    def received(self):
        out = []
        while True:
            try:
                out.append(json.loads(self.sock.recv(65536)))
            except BlockingIOError:
                return out

    def close(self):
        self.sock.close()
        if os.path.exists(self.path):
            os.unlink(self.path)


class DoorbellTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = os.path.join(self.tmp.name, "listeners")

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_folder_no_listener_nothing_sent_nothing_raised(self):
        self.assertEqual(doorbell.notify(self.folder, "g", "events"), 0)
        os.makedirs(self.folder)
        self.assertEqual(doorbell.notify(self.folder, "g", "events"), 0)
        self.assertEqual(doorbell.notify("", "g", "events"), 0)

    def test_every_listener_gets_the_message(self):
        a, b = Listener(self.folder, "a.sock"), Listener(self.folder, "b.sock")
        try:
            self.assertEqual(doorbell.notify(self.folder, "g", "events", {"channel": "c1", "cwd": None}, 7), 2)
            for listener in (a, b):
                [msg] = listener.received()
                self.assertEqual({k: msg[k] for k in ("v", "gatherer", "what", "properties", "row")},
                                 {"v": 1, "gatherer": "g", "what": "events", "properties": {"channel": "c1"},
                                  "row": 7})
                self.assertIsInstance(msg["at"], float)
        finally:
            a.close(), b.close()

    def test_a_dead_listener_s_socket_is_removed_and_other_files_left_alone(self):
        dead = Listener(self.folder, "dead.sock")
        dead.sock.close()                                    # died without removing its socket
        with open(os.path.join(self.folder, "notes.txt"), "w") as fh:
            fh.write("not a listener")
        live = Listener(self.folder, "live.sock")
        try:
            self.assertEqual(doorbell.notify(self.folder, "g", "pending"), 1)
            self.assertEqual(sorted(os.listdir(self.folder)), ["live.sock", "notes.txt"])
            self.assertEqual(len(live.received()), 1)
        finally:
            live.close()

    def test_a_full_listener_is_skipped_not_waited_for(self):
        live = Listener(self.folder)
        try:
            sent = [doorbell.notify(self.folder, "g", "events", row=n) for n in range(5000)]
            self.assertIn(0, sent)                           # its buffer filled: dropped, not blocked
            self.assertTrue(os.path.exists(live.path))       # and it is not taken for dead
        finally:
            live.close()

    def test_a_call_log_is_told_with_its_job_s_gatherer_and_properties(self):
        live = Listener(self.folder)
        job = {"gatherer": "g", "job": "build", "id": 3, "properties": {"channel": "c1"}}
        try:
            with mock.patch.dict(os.environ, {JOB_ENV: json.dumps(job)}):
                CallLog(os.path.join(self.tmp.name, "llm"), listeners=self.folder).write(
                    "segment", "m", "low", {}, 0.1, None, "out", None, "prompt")
            [msg] = live.received()
            self.assertEqual((msg["gatherer"], msg["what"], msg["properties"]), ("g", "llm", {"channel": "c1"}))
            CallLog(os.path.join(self.tmp.name, "llm")).write(          # no listeners given: none told
                "segment", "m", "low", {}, 0.1, None, "out", None, "prompt")
            self.assertEqual(live.received(), [])
        finally:
            live.close()


class WritesTest(Base):
    """What the harness and the policy tell, write by write."""

    def setUp(self):
        super().setUp()
        self.assertEqual(listeners_dir(), os.path.join(self.tmp.name, "listeners"))
        self.live = Listener(listeners_dir())

    def tearDown(self):
        self.live.close()
        super().tearDown()

    def told(self):
        return [(m["what"], m["properties"].get("channel"), m.get("row")) for m in self.live.received()]

    def test_each_event_stored_once_with_its_channel_and_row(self):
        self.put([user("hello", 1)])
        top = store.high_water(self.m._conn("s"))
        self.assertEqual(self.told(), [("events", "c1", top)])
        self.put([user("hello", 1)])                         # a duplicate: nothing stored, nothing told
        self.assertEqual(self.told(), [])

    def test_the_row_is_committed_when_the_message_arrives(self):
        seen = []

        def listen():
            self.live.sock.setblocking(True)
            self.live.sock.settimeout(5)
            msg = json.loads(self.live.sock.recv(65536))
            conn = sqlite3.connect(paths.db_path("s"))       # another connection, as the dashboard's
            seen.append(conn.execute("SELECT count(*) FROM events WHERE row_id = ?", (msg["row"],)).fetchone()[0])
            conn.close()

        thread = threading.Thread(target=listen)
        thread.start()
        self.put([user("hello", 1)])
        thread.join(5)
        self.assertEqual(seen, [1])

    def test_pending_kept_and_cleared(self):
        self.m.record_pending("s", ch("c1"), [{"type": "agent_message", "payload": {"x": 1}, "text": "done"}], "a1")
        self.assertEqual(self.told(), [("pending", "c1", None)])
        self.m.clear_pending("s", ch("c2"))                  # nothing of c2's: nothing told
        self.assertEqual(self.told(), [])
        self.m.clear_pending("s", ch("c1"))
        self.assertEqual(self.told(), [("pending", "c1", None)])

    def test_a_logged_read_and_the_counts_after_it(self):
        self.put([user("hello", 1)])
        self.told()
        self.read()
        reads = [t for t in self.told() if t[0] == "read"]
        read_id = self.m._conn("s").execute("SELECT max(read_id) FROM _reads").fetchone()[0]
        self.assertEqual(reads, [("read", "c1", read_id)])
        self.m.record_real_tokens("s", read_id, 1234)
        self.assertEqual(self.told(), [("counts", None, read_id)])
        self.m.record_real_tokens("s", read_id + 99, 1)      # no such read: nothing told
        self.assertEqual(self.told(), [])

    def test_a_build_claimed_and_settled_and_its_tasks(self):
        self.put(PREAMBLE + conversation(6))
        self.told()
        build_id = tables.claim_build(self.m.store("s"), "c1", 60)    # as a read starts one
        self.policy.build("s", ch("c1"), build_id)                     # as the worker runs it
        told = self.told()
        self.assertEqual(told[0], ("build", "c1", build_id))           # claimed
        self.assertIn(("tasks", "c1", None), told)
        self.assertEqual(told[-1], ("build", "c1", build_id))          # settled: its channel looked up

    def test_a_boundary_check_claimed_and_decided(self):
        store_ = self.m.store("s")
        self.assertTrue(tables.claim_boundary(store_, 5, "c1"))
        self.assertFalse(tables.claim_boundary(store_, 5, "c1"))      # already claimed: nothing written
        tables.record_boundary(store_, 5, True, "new topic", "c1")
        self.assertEqual(self.told(), [("boundary", "c1", 5), ("boundary", "c1", 5)])

    def test_a_bare_connection_tells_no_one(self):
        tables.new_build(self.m._conn("s"), "c1")
        self.assertEqual(self.told(), [])

    def test_a_read_only_side_call_tells_no_one(self):
        self.put(PREAMBLE + conversation(6))
        self.told()
        self.m.context_only("s", store.high_water(self.m._conn("s")), properties=ch("c1"))
        self.assertEqual(self.told(), [])


if __name__ == "__main__":
    unittest.main()
