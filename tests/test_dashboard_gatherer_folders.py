"""gatherer_folders.py: the folders gatherers are kept in, above them in the list -- made, named, moved, deleted, and
gatherers put in them and taken out again."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ag_dashboard import folders, gatherer_folders  # noqa: E402
from ag_dashboard import home as dashboard_home  # noqa: E402
from ag_dashboard.folders import FolderError  # noqa: E402


class GathererFoldersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.was = dashboard_home.HOME
        dashboard_home.HOME = os.path.join(self.tmp.name, "ag")

    def tearDown(self):
        dashboard_home.HOME = self.was
        self.tmp.cleanup()

    def tree(self):
        """{path: [the gatherers in it]}, every folder's (path: its names joined by "/"), "" the top's."""
        got = gatherer_folders.stored()
        out = {folders.path(got, f["id"]): [] for f in got["folders"]}
        for g, fid in sorted(got["filed"].items()):
            out[folders.path(got, fid)].append(g)
        return out

    def test_nothing_kept_is_every_gatherer_at_the_top(self):
        self.assertEqual(gatherer_folders.stored(), {"folders": [], "filed": {}})

    def test_folders_in_folders_by_name_whatever_its_case(self):
        work = gatherer_folders.make("  Work   projects ")
        papers = gatherer_folders.make("papers", work)
        gatherer_folders.make("Archive")
        self.assertEqual([f["name"] for f in gatherer_folders.stored()["folders"]], ["Archive", "papers", "Work projects"])
        self.assertEqual(self.tree(), {"Archive": [], "Work projects": [], "Work projects/papers": []})
        with self.assertRaisesRegex(FolderError, 'a folder named "Archive" is already there'):
            gatherer_folders.make("ARCHIVE")
        gatherer_folders.make("Archive", work)                    # beside others: its own name
        with self.assertRaisesRegex(FolderError, "can't contain"):
            gatherer_folders.make("a/b")
        with self.assertRaisesRegex(FolderError, "needs a name"):
            gatherer_folders.make("   ")
        with self.assertRaisesRegex(FolderError, "no folder"):
            gatherer_folders.make("x", 9999)
        gatherer_folders.rename(papers, "Papers")                 # its own name, its case changed
        with self.assertRaisesRegex(FolderError, "already there"):
            gatherer_folders.rename(papers, "archive")
        self.assertIn("Work projects/Papers", self.tree())

    def test_gatherers_filed_moved_and_out_again(self):
        work = gatherer_folders.make("Work")
        gatherer_folders.file(["web_scraper", " paper_draft ", "web_scraper", ""], work)
        self.assertEqual(self.tree(), {"Work": ["paper_draft", "web_scraper"]})
        old = gatherer_folders.make("Old")
        gatherer_folders.file(["paper_draft"], old)
        self.assertEqual(self.tree(), {"Old": ["paper_draft"], "Work": ["web_scraper"]})
        gatherer_folders.file(["web_scraper"], None)                 # at the top again
        self.assertEqual(gatherer_folders.stored()["filed"], {"paper_draft": old})
        with self.assertRaisesRegex(FolderError, "which gatherers"):
            gatherer_folders.file(["", " "], work)
        with self.assertRaisesRegex(FolderError, "no folder"):
            gatherer_folders.file(["x"], 9999)

    def test_a_folder_moves_with_all_in_it_but_never_into_itself(self):
        a, b = gatherer_folders.make("A"), gatherer_folders.make("B")
        inner = gatherer_folders.make("Inner", a)
        gatherer_folders.file(["g"], inner)
        gatherer_folders.move(a, b)
        self.assertEqual(self.tree(), {"B": [], "B/A": [], "B/A/Inner": ["g"]})
        with self.assertRaisesRegex(FolderError, "can't go in itself"):
            gatherer_folders.move(b, inner)
        with self.assertRaisesRegex(FolderError, "can't go in itself"):
            gatherer_folders.move(a, a)
        gatherer_folders.make("A")
        with self.assertRaisesRegex(FolderError, 'a folder named "A" is already there'):
            gatherer_folders.move(a, None)
        gatherer_folders.move(inner, None)
        self.assertEqual(self.tree(), {"A": [], "B": [], "B/A": [], "Inner": ["g"]})

    def test_a_deleted_folders_gatherers_and_folders_move_up_a_level(self):
        outer = gatherer_folders.make("Outer")
        mid = gatherer_folders.make("Mid", outer)
        gatherer_folders.make("Deep", mid)
        gatherer_folders.make("Deep", outer)                      # beside the one moving up: it keeps its own name
        gatherer_folders.file(["in_mid"], mid)
        gatherer_folders.file(["in_outer"], outer)
        gatherer_folders.delete(mid)
        self.assertEqual(self.tree(), {"Outer": ["in_mid", "in_outer"], "Outer/Deep": [], "Outer/Deep 2": []})
        gatherer_folders.delete(outer)                            # at the top: its gatherers at the top too
        self.assertEqual(self.tree(), {"Deep": [], "Deep 2": []})
        self.assertEqual(gatherer_folders.stored()["filed"], {})
        with self.assertRaisesRegex(FolderError, "no folder"):
            gatherer_folders.delete(outer)

    def test_apart_from_a_gatherers_own_folders(self):
        gatherer_folders.make("Shared name")
        folders.make("g", "Shared name")                          # a gatherer's folder for its actors: another table
        self.assertEqual([f["name"] for f in gatherer_folders.stored()["folders"]], ["Shared name"])
        self.assertEqual([f["name"] for f in folders.of("g")["folders"]], ["Shared name"])


if __name__ == "__main__":
    unittest.main()
