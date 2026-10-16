"""Pollers: what the manager does with them, and the file-change poller."""

import io
import json
import os
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ag.ag_harness import Event, EventType, Manager, Poller  # noqa: E402
from ag.ag_interface.policy import Context, Policy  # noqa: E402
from ag.ag_pollers import FileChangePoller  # noqa: E402
from ag.ag_pollers.file_changes import changed_files  # noqa: E402
from ag.ag_harness.store import operations as store  # noqa: E402
from ag.ag_harness.store import paths  # noqa: E402
from channels import CHANNEL, ch, on  # noqa: E402
from ag.ag_interface import Property  # noqa: E402

HIDDEN = "." + "hidden"   # a hidden directory the walk must skip


def payload_text(payload):
    return payload.get("text", "")


class Plain(Policy):
    """A policy with two types and a read that returns every row's payload."""

    name = "plain"
    event_types = [EventType("note", (Property(CHANNEL),)), EventType("tick")]

    def read(self, conn, read):
        rows = store.rows(conn, match=read.properties)
        return Context([r.payload for r in rows], [], None)


class Ticker(Poller):
    """Returns the events it is told to, and records what it was asked."""

    name = "ticker"
    outputs = ("tick",)

    def __init__(self, events=()):
        self.events, self.asked = list(events), []

    def poll(self, since, types):
        self.asked.append((since, [t.name for t in types]))
        return self.events


class Broken(Poller):
    name = "broken"
    outputs = ("tick",)

    def poll(self, since, types):
        raise RuntimeError("no")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved, paths.TRACE_DIR = paths.TRACE_DIR, os.path.join(self.tmp.name, "traces")
        self.m = Manager(Plain())
        self.m.init("p")
        self.tick = {t.name: t.id for t in self.m.event_types("p")}["tick"]

    def tearDown(self):
        paths.TRACE_DIR = self.saved
        self.tmp.cleanup()

    def note(self, n):
        return Event(1, {"text": f"n{n}"}, id=f"n{n}")


class ManagerPollingTest(Base):
    def test_no_pollers_no_polling(self):
        self.assertEqual(self.m.insert("p", on(self.note(1), None)), 1)
        self.assertEqual(self.m.poll("p"), 0)

    def test_first_poll_has_no_since_even_after_inserts(self):
        self.m.insert("p", on(self.note(1), None))
        ticker = Ticker()
        self.m.add_poller(ticker)
        self.m.poll("p")
        self.assertEqual(ticker.asked, [(None, ["note", "tick"])])   # the poller decides what "first" means

    def test_first_poll_of_an_empty_gatherer_has_no_since(self):
        ticker = Ticker()
        self.m.add_poller(ticker)
        self.m.poll("p")
        self.assertEqual(ticker.asked, [(None, ["note", "tick"])])

    def test_polled_events_are_stored_in_the_pool_and_the_mark_advances(self):
        ticker = Ticker([Event(self.tick, {"n": 1}, id="t1"), Event(self.tick, {"n": 2}, id="t2")])
        self.m.add_poller(ticker)
        self.assertEqual(self.m.poll("p"), 2)
        rows = store.rows(self.m._conn("p"), match=ch("c"))
        self.assertEqual([(r.type.id, r.properties.get("channel")) for r in rows], [(self.tick, None)] * 2)   # every channel's
        first_mark = store.polled_at(self.m._conn("p"), "ticker")
        self.assertEqual(self.m.poll("p"), 0)                   # the same events again: duplicates
        self.assertEqual([since for since, _ in ticker.asked], [None, first_mark])   # the second starts from the first
        self.assertGreaterEqual(store.polled_at(self.m._conn("p"), "ticker"), first_mark)

    def test_the_mark_is_taken_before_the_poller_runs(self):
        ticker = Ticker()
        self.m.add_poller(ticker)
        t0 = time.time()
        self.m.poll("p")
        mark = store.polled_at(self.m._conn("p"), "ticker")
        self.assertGreaterEqual(mark, t0)
        self.assertLessEqual(mark, time.time())

    def test_read_polls_and_insert_does_not(self):
        ticker = Ticker()
        self.m.add_poller(ticker)
        self.m.insert("p", on(self.note(1), None))
        self.m.insert("p", on(self.note(2), None))
        self.assertEqual(ticker.asked, [])                      # inserting only stores
        self.m.read("p", 2, properties=ch(None))
        self.m.read("p", 2, properties=ch(None))
        self.assertEqual(len(ticker.asked), 2)                  # once per read

    def test_polled_events_are_stored_after_the_inserts_and_read_with_them(self):
        self.m.add_poller(Ticker([Event(self.tick, {"n": 1}, id="t1")]))
        self.m.insert("p", on(self.note(1), "c"))
        self.assertEqual([r.type.id for r in store.rows(self.m._conn("p"), match=ch("c"))], [1])
        context = self.m.read("p", 1, properties=ch("c"))
        self.assertEqual(context, [{"text": "n1"}, {"n": 1}])   # the read's own context has them
        self.assertEqual([(r.type.id, r.properties.get("channel")) for r in store.rows(self.m._conn("p"), match=ch("c"))],
                         [(1, "c"), (self.tick, None)])

    def test_what_one_channel_s_read_finds_every_channel_sees(self):
        self.m.add_poller(Ticker([Event(self.tick, {"n": 1}, id="t1")]))
        self.m.insert("p", on(self.note(1), "a"))
        self.m.insert("p", on(self.note(2), "b"))
        self.m.read("p", 1, properties=ch("a"))                     # a's read polls
        self.assertEqual(self.m.read("p", 2, properties=ch("b")), [{"text": "n2"}, {"n": 1}])   # b sees it too

    def test_a_gatherer_without_a_database_is_not_polled(self):
        ticker = Ticker()
        self.m.add_poller(ticker)
        self.assertEqual(self.m.read("nothing-here", 1, properties=ch(None)), [])
        self.assertEqual(ticker.asked, [])

    def test_a_failing_poller_is_skipped_and_its_mark_untouched(self):
        ticker = Ticker([Event(self.tick, {"n": 1}, id="t1")])
        self.m.add_poller(Broken())
        self.m.add_poller(ticker)
        self.assertEqual(self.m.insert("p", on(self.note(1), None)), 1)
        self.assertEqual(self.m.read("p", 1, properties=ch(None)), [{"text": "n1"}, {"n": 1}])   # the read goes on
        self.assertEqual(self.m.poll("p"), 0)
        self.assertIsNone(store.polled_at(self.m._conn("p"), "broken"))
        self.assertIsNotNone(store.polled_at(self.m._conn("p"), "ticker"))

    def test_a_poller_must_declare_its_outputs(self):
        class Silent(Poller):
            name = "silent"

            def poll(self, since, types):
                return []
        with self.assertRaisesRegex(ValueError, "declares no outputs"):
            self.m.add_poller(Silent())

    def test_an_event_of_an_undeclared_type_is_dropped(self):
        self.m.add_poller(Ticker([self.note(1), Event(self.tick, {"n": 2}, id="t2")]))   # a note: not its output
        with redirect_stderr(io.StringIO()) as err:
            self.assertEqual(self.m.poll("p"), 1)                                  # the tick alone
        self.assertIn("which it does not declare", err.getvalue())

    def test_an_event_of_an_unknown_type_is_refused_not_fatal(self):
        self.m.add_poller(Ticker([Event(99, {"n": 1}, id="x"), Event(self.tick, {"n": 2}, id="t2")]))
        self.assertEqual(self.m.poll("p"), 1)

    def test_add_poller_replaces_by_name(self):
        a, b = Ticker(), Ticker()
        self.m.add_poller(a)
        self.m.add_poller(b)
        self.assertEqual(self.m.pollers, [b])
        self.m.poll("p")
        self.assertEqual((len(a.asked), len(b.asked)), (0, 1))

    def test_pollers_at_construction(self):
        ticker = Ticker()
        m = Manager(Plain(), pollers=[ticker])
        m.init("q")
        m.poll("q")
        self.assertEqual(len(ticker.asked), 1)

    def test_bulk_load_does_not_poll(self):
        ticker = Ticker()
        self.m.add_poller(ticker)
        self.m.bulk_load("p", [self.note(1)], properties=ch(None))
        self.assertEqual(ticker.asked, [])


class FileWalkTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def workdir(self, since):
        """A directory with a file older than `since`, a newer one, and newer
        ones the walk must skip."""
        root = os.path.join(self.tmp.name, "work")
        os.makedirs(os.path.join(root, "src"))
        os.makedirs(os.path.join(root, HIDDEN))
        os.makedirs(os.path.join(root, "__pycache__"))
        for rel, when in (("old.py", since - 100), (os.path.join("src", "new.py"), since + 5),
                          (os.path.join(HIDDEN, "index"), since + 5), (os.path.join("__pycache__", "x.pyc"), since + 5)):
            path = os.path.join(root, rel)
            with open(path, "w") as fh:
                fh.write("x")
            os.utime(path, (when, when))
        return root

    def test_changed_files_walk(self):
        since = time.time() - 1000
        root = self.workdir(since)
        self.assertEqual([p for p, _ in changed_files(root, since)], [os.path.join("src", "new.py")])   # relative
        self.assertEqual(changed_files(root, None), [])
        self.assertEqual(changed_files(os.path.join(root, "nope"), since), [])
        self.assertEqual(changed_files(root, time.time() + 10), [])
        many = os.path.join(root, "many")
        os.makedirs(many)
        for n in range(5):
            with open(os.path.join(many, f"{n}.txt"), "w") as fh:
                fh.write("y")
        self.assertEqual(len(changed_files(root, since, limit=3)), 3)

    def test_the_poller_types_events_from_the_gatherer_and_names_files_relatively(self):
        since = time.time() - 1000
        root = self.workdir(since)
        poller = FileChangePoller(root)
        self.assertEqual(poller.name, f"file_changes:{os.path.abspath(root)}")   # a mark per directory
        self.assertNotEqual(FileChangePoller(root + "/src").name, poller.name)
        types = [EventType("user_message", id=1),
                 EventType("environment_update", id=6)]
        events = poller.poll(since, types)
        path = os.path.join("src", "new.py")
        self.assertEqual([(e.type_id, e.payload["subject"], e.payload["what"], e.payload["source"]) for e in events],
                         [(6, path, f"File {path} was changed on disk", poller.name)])
        self.assertAlmostEqual(events[0].payload["timestamp"], since + 5, places=2)
        self.assertEqual(events[0].id, f"environment_update:{poller.name}:{path}@{round(since + 5, 3)}")
        where = os.path.abspath(root)                                             # the directory, as cwd
        self.assertEqual(events[0].properties, {"poller": poller.name, "cwd": where})   # no id given: its name
        poller.id = "file_changes"                                                # as the home gives it
        self.assertEqual(poller.poll(since, types)[0].properties, {"poller": "file_changes", "cwd": where})
        self.assertEqual(FileChangePoller.properties, ("poller", "cwd"))

    def test_a_change_just_before_the_mark_is_found_once(self):
        """An mtime from the coarse clock can fall just before the mark; the
        poller looks back, and the store keeps a change seen twice once."""
        root = self.workdir(time.time() - 1000)
        path = os.path.join(root, "old.py")
        mark = time.time()
        os.utime(path, (mark - 0.01, mark - 0.01))           # "changed" a hair before the mark
        types = [EventType("environment_update", id=6)]
        first = FileChangePoller(root).poll(mark, types)
        self.assertEqual([e.payload["subject"] for e in first], ["old.py"])
        self.assertEqual([e.id for e in FileChangePoller(root).poll(mark + 0.03, types)], [e.id for e in first])

    def test_a_file_written_well_before_the_first_mark_is_not_a_change(self):
        """What was there when the gatherer started is not reported later."""
        root = self.workdir(time.time() - 1000)
        path = os.path.join(root, "old.py")
        mark = time.time()
        os.utime(path, (mark - 0.3, mark - 0.3))              # written before the first poll's mark
        types = [EventType("environment_update", id=6)]
        self.assertEqual(FileChangePoller(root).poll(mark, types), [])

    def test_nothing_without_the_type_or_a_since(self):
        since = time.time() - 1000
        root = self.workdir(since)
        poller = FileChangePoller(root)
        self.assertEqual(poller.poll(since, [EventType("user_message", id=1)]), [])
        self.assertEqual(poller.poll(None, [EventType("environment_update", id=6)]), [])


if __name__ == "__main__":
    unittest.main()
