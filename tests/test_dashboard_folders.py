"""folders.py: the folders a gatherer's actors are kept in -- made, named, moved, deleted, closed and reopened, found
by path -- and the folders of saved actors from before it, copied in once."""

import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ag_dashboard import folders, saved, sessions  # noqa: E402
from ag_dashboard import home as dashboard_home  # noqa: E402


class FoldersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.was = dashboard_home.HOME
        dashboard_home.HOME = os.path.join(self.tmp.name, "ag")

    def tearDown(self):
        dashboard_home.HOME = self.was
        self.tmp.cleanup()

    def names(self, gatherer="g"):
        """{path: [the channels in it]} of the gatherer, every folder's."""
        tree = folders.of(gatherer)
        out = {folders.path(tree, f["id"]): [] for f in tree["folders"]}
        for c, fid in sorted(tree["filed"].items()):
            out[folders.path(tree, fid)].append(c)
        return out

    def test_nothing_kept_is_nothing(self):
        self.assertEqual((folders.stored(), folders.of("g")), ({}, {"folders": [], "filed": {}}))

    def test_folders_in_folders_found_by_path_whatever_its_case(self):
        harnesses = folders.make("g", " Harnesses ")
        codex = folders.make("g", "Codex", harnesses)
        self.assertEqual(folders.find("g", "harnesses/CODEX"), codex)
        self.assertEqual(folders.find("g", "/Harnesses/Codex/"), codex)
        for top in ("", "/", "top", "TOP"):
            self.assertIsNone(folders.find("g", top))
        with self.assertRaisesRegex(folders.FolderError, 'no folder "Harnesses/Gemini" in g'):
            folders.find("g", "Harnesses/Gemini")
        gemini = folders.find_or_make("g", "harnesses/Gemini/Live")          # the folders not there made
        self.assertEqual(folders.path(folders.of("g"), gemini), "Harnesses/Gemini/Live")
        self.assertEqual(folders.find_or_make("g", "Harnesses/Codex"), codex)   # there already: itself
        self.assertEqual(folders.of("h"), {"folders": [], "filed": {}})        # another gatherer's: none of them
        self.assertEqual(folders.make("h", "Codex"), folders.find("h", "Codex"))

    def test_names_are_one_of_their_kind_beside_one_another(self):
        a = folders.make("g", "Paper")
        folders.make("g", "Notes", a)
        with self.assertRaisesRegex(folders.FolderError, 'a folder named "Paper" is already there'):
            folders.make("g", "PAPER")
        folders.make("g", "Notes")                                            # the same name elsewhere: fine
        with self.assertRaisesRegex(folders.FolderError, "needs a name"):
            folders.make("g", "  ")
        with self.assertRaisesRegex(folders.FolderError, "can't contain"):
            folders.make("g", "a/b")
        with self.assertRaisesRegex(folders.FolderError, "which gatherer"):
            folders.make("", "x")
        folders.rename("g", a, "paper")                                       # its own case: fine
        with self.assertRaisesRegex(folders.FolderError, 'a folder named "Notes" is already there'):
            folders.rename("g", a, "notes")
        self.assertEqual(sorted(self.names()), ["Notes", "paper", "paper/Notes"])

    def test_actors_filed_moved_and_out_again(self):
        a, b = folders.make("g", "A"), folders.make("g", "B")
        folders.file("g", ["c1", "c2", "c1", " "], a)
        self.assertEqual(self.names(), {"A": ["c1", "c2"], "B": []})
        folders.file("g", ["c2"], b)
        folders.file("g", ["c1"], None)                                       # at the top: no folder
        self.assertEqual(self.names(), {"A": [], "B": ["c2"]})
        with self.assertRaisesRegex(folders.FolderError, "which actors"):
            folders.file("g", [""], a)
        with self.assertRaisesRegex(folders.FolderError, f"no folder {a} in h"):
            folders.file("h", ["x"], a)                                       # another gatherer's folder

    def test_a_folder_moves_with_all_in_it_but_never_into_itself(self):
        a = folders.make("g", "A")
        b = folders.make("g", "B", a)
        c = folders.make("g", "C")
        folders.file("g", ["x"], b)
        folders.move("g", a, c)
        self.assertEqual(self.names(), {"C": [], "C/A": [], "C/A/B": ["x"]})
        for into in (a, b):
            with self.assertRaisesRegex(folders.FolderError, "can't go in itself"):
                folders.move("g", a, into)
        folders.make("g", "A")
        with self.assertRaisesRegex(folders.FolderError, 'a folder named "A" is already there'):
            folders.move("g", a, None)

    def test_a_deleted_folders_actors_and_folders_move_up_a_level(self):
        a = folders.make("g", "A")
        b = folders.make("g", "B", a)
        folders.make("g", "B")                                                # B at the top too: the moved one renamed
        folders.file("g", ["in-a"], a)
        folders.file("g", ["in-b"], b)
        folders.delete("g", a)
        self.assertEqual(self.names(), {"B": [], "B 2": ["in-b"]})
        self.assertNotIn("in-a", folders.of("g")["filed"])                     # at the top now
        top = folders.make("g", "T")
        inner = folders.make("g", "I", top)
        folders.file("g", ["deep"], inner)
        folders.delete("g", inner)
        self.assertEqual(self.names()["T"], ["deep"])                          # in the folder it was in
        with self.assertRaisesRegex(folders.FolderError, "no folder"):
            folders.delete("g", 9999)

    def test_the_folders_of_saved_actors_from_before_are_copied_in_once(self):
        os.makedirs(dashboard_home.HOME)
        conn = sqlite3.connect(sessions.db_path())
        conn.executescript("""
            CREATE TABLE saved (gatherer TEXT NOT NULL, channel TEXT NOT NULL, at TEXT NOT NULL, folder TEXT,
                                PRIMARY KEY (gatherer, channel));
            CREATE TABLE saved_folders (gatherer TEXT NOT NULL, name TEXT NOT NULL COLLATE NOCASE, at TEXT NOT NULL,
                                        PRIMARY KEY (gatherer, name));
            INSERT INTO saved_folders VALUES ('g', 'Paper', '2026-11-01T00:00:00+00:00'),
                                             ('g', 'Empty', '2026-11-02T00:00:00+00:00'),
                                             ('g', 'A/B', '2026-11-03T00:00:00+00:00'),
                                             ('h', 'Paper', '2026-11-04T00:00:00+00:00');
            INSERT INTO saved VALUES ('g', 'c1', '2026-11-05T00:00:00+00:00', 'paper'),
                                     ('g', 'c2', '2026-11-05T00:00:00+00:00', NULL),
                                     ('g', 'c3', '2026-11-05T00:00:00+00:00', 'A/B'),
                                     ('h', 'c4', '2026-11-05T00:00:00+00:00', 'Paper');
        """)
        conn.close()
        self.assertEqual(self.names(), {"A-B": ["c3"], "Empty": [], "Paper": ["c1"]})    # its case as made
        self.assertEqual(self.names("h"), {"Paper": ["c4"]})
        self.assertEqual(sorted(saved.stored()["g"]), ["c1", "c2", "c3"])               # all still saved
        folders.delete("g", folders.find("g", "Paper"))
        folders.ensure()                                                               # once: not again
        self.assertEqual(sorted(self.names()), ["A-B", "Empty"])
        saved.choose("g", "c5", True)                                                  # its table from before still takes one
        saved.choose("g", "c1", False)
        self.assertEqual(sorted(saved.stored()["g"]), ["c2", "c3", "c5"])

    def test_a_folder_closed_with_the_folders_in_it_and_reopened(self):
        a = folders.make("g", "A")
        b = folders.make("g", "B", a)
        c = folders.make("g", "C")
        self.assertEqual(sorted(folders.mark("g", a, True)), sorted([a, b]))
        closed = {f["name"]: f["closed"] for f in folders.of("g")["folders"]}
        self.assertTrue(closed["A"] and closed["A"] == closed["B"])               # at once, with what is in it
        self.assertIsNone(closed["C"])
        folders.reopen("g", a)
        self.assertEqual({f["closed"] for f in folders.of("g")["folders"]}, {None})
        with self.assertRaisesRegex(folders.FolderError, "no folder"):
            folders.reopen("g", 9999)
        self.assertIsNotNone(c)

    def test_putting_something_in_a_closed_folder_reopens_it_and_the_closed_folders_it_is_in(self):
        a = folders.make("g", "A")
        b = folders.make("g", "B", a)
        other = folders.make("g", "Other")
        shut = lambda: {f["name"] for f in folders.of("g")["folders"] if f["closed"]}   # noqa: E731
        for put in (lambda: folders.file("g", ["c1"], b), lambda: folders.move("g", other, b),
                    lambda: folders.make("g", "New", b)):
            folders.mark("g", a, True)
            folders.mark("g", other, False)
            put()
            self.assertEqual(shut(), set())
        folders.mark("g", a, True)
        folders.file("g", ["c1"], None)                                           # taken out to the top: nothing opens
        folders.move("g", other, None)                                            # nor does it, closed with A
        self.assertEqual(shut(), {"A", "B", "New", "Other"})
        folders.delete("g", a)                                                    # what was in it, up: closed still
        self.assertEqual(shut(), {"B", "New", "Other"})

    def test_a_table_from_before_closed_is_given_it_every_folder_open(self):
        os.makedirs(dashboard_home.HOME)
        conn = sqlite3.connect(sessions.db_path())
        conn.executescript("""
            CREATE TABLE folders (id INTEGER PRIMARY KEY AUTOINCREMENT, gatherer TEXT NOT NULL, parent INTEGER,
                                  name TEXT NOT NULL, at TEXT NOT NULL);
            CREATE TABLE filed (gatherer TEXT NOT NULL, channel TEXT NOT NULL, folder INTEGER NOT NULL, at TEXT NOT NULL,
                                PRIMARY KEY (gatherer, channel));
            INSERT INTO folders (gatherer, parent, name, at) VALUES ('g', NULL, 'Old', '2026-11-01T00:00:00+00:00');
        """)
        conn.close()
        self.assertEqual(folders.of("g")["folders"], [{"id": 1, "parent": None, "name": "Old", "closed": None}])
        folders.mark("g", 1, True)                                                # a change gives it the column
        self.assertTrue(folders.of("g")["folders"][0]["closed"])

    def test_closing_a_folder_closes_every_actor_in_it_takes_their_bookmarks_off_and_ends_its_terminals(self):
        a = folders.make("g", "A")
        b = folders.make("g", "B", a)
        elsewhere = folders.make("g", "Elsewhere")
        folders.file("g", ["running", "kept", "never", "outside", "done", "gone", "ran"], a)
        folders.file("g", ["codex-sid", "term"], b)
        folders.file("g", ["away"], elsewhere)
        for c in ("done", "gone", "running", "away"):
            saved.choose("g", c, True)

        class Started:                                                            # sessions.Sessions, as close uses it
            def __init__(self):
                self.did = []

            def stop(self, sid):
                self.did.append(("stop", sid))
                if sid == "running":
                    return {}
                if sid == "kept":
                    raise sessions.SessionError("the dashboard has no process open for this session")
                return {}

            def discard(self, sid):
                self.did.append(("discard", sid))

            def shells(self):
                return [{"id": "sh1", "gatherer": "g", "folder": b}, {"id": "sh2", "gatherer": "g", "folder": elsewhere},
                        {"id": "sh3", "gatherer": "h", "folder": b}]

            def close_shell(self, sid):
                self.did.append(("shell", sid))

        def actor(channel, status, **session):
            return {"channel": channel, "status": status, "events": 3, "reads": 2,
                    "session": {"session_id": channel, **session} if session is not None else None}
        home = {"gatherers": [{"name": "g", "agents": [
            actor("running", "running", pid=11),
            actor("kept", "idle", kept=1.0),
            {"channel": "never", "status": "idle", "events": 0, "reads": 0, "session": {"session_id": "never"}},
            {"channel": "outside", "status": "idle", "session": None},
            actor("ran", "idle", turns=1, ended=1.0),                            # its process gone, listed Idle
            actor("done", "closed"),
            actor("thread-1", "running", terminal=True, started_as="codex-sid"),
            actor("away", "running", pid=12),
            {"channel": "crew", "status": "running", "role": "coordinator", "session": {"session_id": "crew", "pid": 13}},
        ]}]}
        started = Started()
        left = folders.close("g", a, started, home)
        self.assertEqual(started.did, [("stop", "running"), ("stop", "kept"), ("discard", "never"), ("stop", "ran"),
                                       ("stop", "thread-1"), ("shell", "sh1")])
        self.assertEqual(left, [{"channel": "kept", "why": "the dashboard has no process open for this session"},
                                {"channel": "outside", "why": "the dashboard isn't running it"}])
        self.assertEqual(sorted(saved.stored()["g"]), ["away"])                   # in it -- "gone" too, not in the home
        self.assertEqual({f["name"] for f in folders.of("g")["folders"] if f["closed"]}, {"A", "B"})
        with self.assertRaisesRegex(folders.FolderError, "no folder"):
            folders.close("g", 9999, started, home)
        with self.assertRaisesRegex(folders.FolderError, "no folder 'x'"):
            folders.close("g", "x", started, home)


if __name__ == "__main__":
    unittest.main()
