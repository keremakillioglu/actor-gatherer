"""Actors on branches of their own (ag_dashboard/branches.py): a gatherer's projects, an actor's worktree made from one,
and what it changes there merged into the project's checkout -- every change asked about with approval on; without,
all but the conflict zone's and what the project changed too -- shown in the file open in the Editor, its lines marked."""
import base64
import os
import random
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ag_dashboard import branches, editor, home as dashboard_home, sessions  # noqa: E402

try:
    from pycrdt import Doc, Text
except ImportError:
    Doc = Text = None

BASE = "one\ntwo\nthree\nfour\nfive\n"


class CombineTest(unittest.TestCase):
    """`combine`: the branch's file merged into the project's, from where the project has it."""

    def test_the_branch_s_change_is_taken_in_and_the_base_moves_on(self):
        merged, base, found, held = branches.combine(BASE, BASE.replace("one", "ONE"), BASE.replace("four", "FOUR"))
        self.assertEqual(merged, "ONE\ntwo\nthree\nFOUR\nfive\n")
        self.assertEqual(base, BASE.replace("four", "FOUR"))
        self.assertEqual((found, held), ([], {}))

    def test_with_approval_every_change_is_held_and_nothing_taken(self):
        theirs = BASE.replace("two", "TWO").replace("five\n", "five\nsix\n")
        merged, base, found, held = branches.combine(BASE, BASE, theirs, approve=True)
        self.assertEqual((merged, base), (BASE, BASE))
        self.assertEqual([(BASE[s:e], was, said, why) for s, e, was, said, why, _ in found],
                         [("two\n", "two\n", "TWO\n", "approve"), ("", "", "six\n", "approve")])
        self.assertEqual(sorted(held.values()), ["approve", "approve"])

    def test_the_conflict_zone_s_lines_are_held_the_rest_taken(self):
        theirs = BASE.replace("two", "TWO").replace("four", "FOUR")
        merged, base, found, held = branches.combine(BASE, BASE, theirs, guard=[(1, 2)])   # "two" in the zone
        self.assertEqual(merged, BASE.replace("four", "FOUR"))
        self.assertEqual(base, BASE.replace("four", "FOUR"))
        self.assertEqual([(said, why) for _, _, _, said, why, _ in found], [("TWO\n", "zone")])

    def test_lines_the_project_changed_too_differently_are_held(self):
        merged, base, found, held = branches.combine(BASE, BASE.replace("two", "2"), BASE.replace("two", "TWO"))
        self.assertEqual((merged, base), (BASE.replace("two", "2"), BASE))
        self.assertEqual([(merged[s:e], said, why) for s, e, _, said, why, _ in found], [("2\n", "TWO\n", "both")])

    def test_the_same_change_on_both_sides_moves_the_base_on(self):
        merged, base, found, _ = branches.combine(BASE, BASE.replace("two", "TWO"), BASE.replace("two", "TWO"), approve=True)
        self.assertEqual((merged, base, found), (BASE.replace("two", "TWO"), BASE.replace("two", "TWO"), []))

    def test_a_place_held_before_stays_held_until_settled(self):
        theirs = BASE.replace("two", "TWO")
        *_, held = branches.combine(BASE, BASE, theirs, guard=[(1, 2)])
        merged, base, found, again = branches.combine(BASE, BASE, theirs, held=held)    # the zone cleared since
        self.assertEqual((merged, len(found), again), (BASE, 1, held))
        key = found[0][5]
        merged, base, found, again = branches.combine(BASE, BASE, theirs, held=held, decided={key: "TWO\n"})
        self.assertEqual((merged, base, found, again), (BASE, theirs, [], {}))         # left out, asked no more

    def test_a_settlement_of_lines_the_branch_changed_since_does_not_count(self):
        theirs = BASE.replace("two", "TWO")
        *_, held = branches.combine(BASE, BASE, theirs, approve=True)
        key = next(iter(held))
        _, base, found, _ = branches.combine(BASE, BASE, BASE.replace("two", "Two!"), approve=True, held=held,
                                             decided={key: "TWO\n"})
        self.assertEqual((base, [f[3] for f in found]), (BASE, ["Two!\n"]))

    def test_every_place_held_settled_at_once(self):
        theirs = BASE.replace("two", "TWO").replace("four", "FOUR")
        merged, base, found, held = branches.combine(BASE, BASE, theirs, approve=True, every="theirs")
        self.assertEqual((merged, base, found, held), (theirs, theirs, [], {}))
        merged, base, found, held = branches.combine(BASE, BASE, theirs, approve=True, every="mine")
        self.assertEqual((merged, base, found, held), (BASE, theirs, [], {}))


class MarkedTest(unittest.TestCase):
    """`marked`: the branch's lines in the project's file, as long as the project has them as the branch does."""

    def test_its_changed_lines_where_the_project_has_them(self):
        start = "a\nb\nc\n"
        theirs = "a\nB\nc\nd\n"
        mine = "zero\na\nB\nc\nd\n"
        self.assertEqual(branches.marked(start, theirs, mine), [(2, 3), (4, 5)])
        self.assertEqual(branches.marked(start, theirs, "zero\na\nB edited\nc\nd\n"), [(4, 5)])
        self.assertEqual(branches.marked(start, theirs, start), [])


def git(cwd, *args):
    return subprocess.run(["git", "-C", cwd, *args], check=True, capture_output=True, text=True).stdout.strip()


@unittest.skipIf(Doc is None, "pycrdt is not installed")
class BranchesTest(unittest.TestCase):
    """A project with a commit, an actor's branch made from it, and its changes merged into the project's checkout."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        top = os.path.realpath(self.tmp.name)
        self.saved = dashboard_home.HOME
        dashboard_home.HOME = os.path.join(top, "ag")
        self.addCleanup(setattr, dashboard_home, "HOME", self.saved)
        self.project = os.path.join(top, "work", "proj")
        os.makedirs(self.project)
        git(self.project, "init", "-q", "-b", "main")
        for k, v in (("user.name", "T"), ("user.email", "t@example.com"), ("commit.gpgsign", "false")):
            git(self.project, "config", k, v)
        self.put(self.project, "notes.py", "def f():\n    return 1\n\nx = f()\n")
        self.put(self.project, "README.md", "# proj\n")
        git(self.project, "add", "-A")
        git(self.project, "commit", "-qm", "start")
        git(self.project, "remote", "add", "origin", "git@github.com:someone/proj.git")
        self.started = sessions.Sessions()
        self.addCleanup(self.started.close)
        self.editors = editor.Editors(poll=3600)     # looked at by hand here
        self.addCleanup(self.editors.close)
        self.branches = branches.Branches(self.editors, self.started, poll=3600)
        self.addCleanup(self.branches.close)

    def put(self, where, rel, text):
        path = os.path.join(where, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        st = os.stat(path)                           # a later mtime: the same second may not tell writes apart
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + random.randint(1, 10**6)))

    def get(self, where, rel):
        with open(os.path.join(where, rel), encoding="utf-8") as fh:
            return fh.read()

    def branch(self, approve=False):
        branches.add_project("g", self.project)
        s = self.branches.create("g", self.project, approve=approve)
        b = next(x for x in self.branches.listed() if x["session_id"] == s["session_id"])
        return s, b["worktree"]

    def test_projects_set_suggested_and_removed(self):
        side = os.path.join(os.path.dirname(self.project), "side")
        git(self.project, "worktree", "add", "-q", side)
        self.assertEqual([p["path"] for p in branches.suggestions("g", [side, os.path.join(self.project, "sub"), self.project])],
                         [self.project])                     # a worktree's: its repository's
        got = branches.add_project("g", side)
        self.assertEqual([(p["path"], p["github"]) for p in got], [(self.project, "someone/proj")])
        self.assertEqual(branches.suggestions("g", [self.project]), [])
        self.assertEqual(branches.remove_project("g", self.project), [])
        with self.assertRaises(branches.BranchError):
            branches.add_project("g", os.path.dirname(self.project))      # not in a repository

    def test_an_actor_on_a_branch_runs_in_a_worktree_of_its_own(self):
        s, wt = self.branch()
        self.assertEqual(s["cwd"], s["branch"]["worktree"])
        self.assertEqual(os.path.realpath(s["cwd"]), wt)
        self.assertEqual(git(wt, "rev-parse", "--abbrev-ref", "HEAD"), s["branch"]["branch"])
        self.assertTrue(s["branch"]["branch"].startswith("ag/"))
        self.assertEqual(os.path.basename(os.path.dirname(wt)), "proj-worktrees")
        [b] = self.branches.listed()                 # where it came from, and where its changes go
        self.assertEqual((b["start"], b["started_on"], b["onto"]["branch"]),
                         (git(self.project, "rev-parse", "HEAD"), "main", "main"))
        self.assertEqual(branches.projects("g")[0]["branch"], "main")
        with self.assertRaises(branches.BranchError):
            self.branches.create("other", self.project)     # not one of its projects

    def test_without_approval_its_changes_merge_into_the_project(self):
        s, wt = self.branch()
        self.put(wt, "notes.py", "def f():\n    return 2\n\nx = f()\n")
        self.put(wt, "new/added.txt", "made on the branch\n")
        os.remove(os.path.join(wt, "README.md"))
        self.branches.look(everything=True)
        self.assertEqual(self.get(self.project, "notes.py"), "def f():\n    return 2\n\nx = f()\n")
        self.assertEqual(self.get(self.project, "new/added.txt"), "made on the branch\n")
        self.assertFalse(os.path.exists(os.path.join(self.project, "README.md")))
        self.assertEqual(self.branches.listed()[0]["held"], {})

    def test_the_project_s_own_change_is_kept_and_the_same_lines_asked_about(self):
        s, wt = self.branch()
        self.put(self.project, "notes.py", "def f():\n    return 10\n\nx = f()\n")     # not committed
        self.put(wt, "notes.py", "# top\ndef f():\n    return 2\n\nx = f()\n")
        self.branches.look(everything=True)
        self.assertEqual(self.get(self.project, "notes.py"), "# top\ndef f():\n    return 10\n\nx = f()\n")
        self.assertEqual(self.branches.listed()[0]["held"], {"notes.py": {"n": 1, "kind": "lines"}})
        self.assertEqual(self.branches.pending(os.path.join(self.project, "notes.py")), 1)
        self.assertEqual(self.branches.pending(self.project, folder=True), 1)

    def open(self, rel, cid="p1"):
        room, conn = self.editors.join(os.path.join(self.project, rel), self.project, cid, 1)
        self.branches.look()                          # what was opened: shown at once
        return room

    def edit(self, room, cid, old, new):
        """A page's edit of the open file, as the page sends it: `old`'s first appearance made `new`."""
        doc = Doc()
        doc.apply_update(room.doc.get_update())
        text, before = doc.get("text", type=Text), doc.get_state()
        at = len(str(text)[:str(text).index(old)].encode())
        del text[at:at + len(old.encode())]
        text.insert(at, new)
        room.edit(cid, doc.get_update(before))

    def region(self, room, c):
        units = str(room.text).encode("utf-16-le")
        return units[2 * c["from"]:2 * c["to"]].decode("utf-16-le")

    def test_with_approval_each_change_waits_in_the_open_file(self):
        s, wt = self.branch(approve=True)
        self.put(wt, "notes.py", "def f():\n    return 2\n\nx = f() + 1\n")
        self.branches.look(everything=True)
        self.assertEqual(self.get(self.project, "notes.py"), "def f():\n    return 1\n\nx = f()\n")   # not taken in
        room = self.open("notes.py")
        found = room.state()["conflicts"]
        self.assertEqual([(self.region(room, c), c["theirs"], c["agent"]["why"]) for c in found],
                         [("    return 1\n", "    return 2\n", "approve"), ("x = f()\n", "x = f() + 1\n", "approve")])
        self.editors.settle(room.path, self.project, found[0]["id"], "theirs")     # Accept
        self.editors.settle(room.path, self.project, found[1]["id"], "mine")       # Reject
        self.assertEqual(str(room.text), "def f():\n    return 2\n\nx = f()\n")
        self.assertEqual(room.state()["conflicts"], [])
        room.save()
        self.branches.look(everything=True)                # asked once: the rejected change is not asked about again
        self.assertEqual(room.state()["conflicts"], [])
        self.assertEqual(self.get(self.project, "notes.py"), "def f():\n    return 2\n\nx = f()\n")
        self.assertEqual(self.branches.listed()[0]["held"], {})

    def test_its_change_to_the_conflict_zone_is_asked_about_the_rest_saved(self):
        s, wt = self.branch()
        room = self.open("notes.py")
        self.edit(room, "p1", "return 1", "return 5")       # typed here: the zone
        room.save()
        self.put(wt, "notes.py", "def f():\n    return 6\n\nx = f() * 2\n")
        self.branches.look(everything=True)
        self.assertEqual(str(room.text), "def f():\n    return 5\n\nx = f() * 2\n")
        self.assertEqual(self.get(self.project, "notes.py"), "def f():\n    return 5\n\nx = f() * 2\n")   # saved
        [c] = room.state()["conflicts"]
        self.assertEqual((self.region(room, c), c["theirs"], c["zone"], c["agent"]["why"]),
                         ("    return 5\n", "    return 6\n", True, "zone"))
        room.clear_zone()
        self.branches.look(everything=True)                 # held, until settled
        self.assertEqual(len(room.state()["conflicts"]), 1)

    def test_its_lines_are_marked_in_the_open_file(self):
        s, wt = self.branch()
        self.put(wt, "notes.py", "def f():\n    return 2\n\nx = f()\ny = 3\n")
        self.branches.look(everything=True)
        room = self.open("notes.py")
        marks = room.state()["marks"]
        self.assertEqual([(self.region(room, m), m["channel"]) for m in marks],
                         [("    return 2\n", s["session_id"]), ("y = 3\n", s["session_id"])])
        self.edit(room, "p1", "y = 3", "y = 4")             # rewritten here: no longer its
        self.branches.look(everything=True)
        self.assertEqual([self.region(room, m) for m in room.state()["marks"]], ["    return 2\n"])

    def test_a_file_it_made_or_deleted_is_asked_about_whole_with_approval(self):
        s, wt = self.branch(approve=True)
        self.put(wt, "added.txt", "new\n")
        os.remove(os.path.join(wt, "README.md"))
        self.branches.look(everything=True)
        self.assertEqual(self.branches.listed()[0]["held"], {"added.txt": {"n": 1, "kind": "created"},
                                                            "README.md": {"n": 1, "kind": "deleted"}})
        self.assertFalse(os.path.exists(os.path.join(self.project, "added.txt")))
        self.branches.decide(s["session_id"], os.path.join(self.project, "added.txt"), "theirs")
        self.branches.decide(s["session_id"], "README.md", "mine")
        self.assertEqual(self.get(self.project, "added.txt"), "new\n")
        self.assertEqual(self.get(self.project, "README.md"), "# proj\n")
        self.branches.look(everything=True)
        self.assertEqual(self.branches.listed()[0]["held"], {})

    def test_approval_turned_on_holds_its_next_change(self):
        s, wt = self.branch()
        self.branches.set_approve(s["session_id"], True)
        self.put(wt, "notes.py", "def f():\n    return 2\n\nx = f()\n")
        self.branches.look(everything=True)
        self.assertEqual(self.get(self.project, "notes.py"), "def f():\n    return 1\n\nx = f()\n")
        self.branches.decide(s["session_id"], "notes.py", "theirs")
        self.assertEqual(self.get(self.project, "notes.py"), "def f():\n    return 2\n\nx = f()\n")

    def test_a_codex_session_renamed_to_its_thread_keeps_its_branch(self):
        s, wt = self.branch()
        thread = "019a0000-0000-7000-8000-000000000001"
        self.started._rename(s["session_id"], thread)
        [b] = self.branches.listed()
        self.assertEqual((b["session_id"], b["channel"]), (s["session_id"], thread))
        self.assertEqual(self.branches.set_approve(thread, True)["approve"], True)

    def told(self):
        """What the actors were told (`tell`): (channel, its stream message's payload)."""
        return [(c[0][1], e["payload"]) for c in self.record.call_args_list for e in c[0][2]]

    def test_the_actor_is_told_when_its_change_is_left_out_and_not_when_taken(self):
        self.record = self.enterContext(mock.patch.object(branches.actions, "record"))
        s, wt = self.branch(approve=True)
        self.put(wt, "notes.py", "def f():\n    return 2\n\nx = f() + 1\n")
        self.put(wt, "added.txt", "new\n")
        self.branches.look(everything=True)
        room = self.open("notes.py")
        first, second = room.state()["conflicts"]
        self.editors.settle(room.path, self.project, first["id"], "theirs")       # Accept: nothing to tell
        self.assertEqual(self.told(), [])
        self.editors.settle(room.path, self.project, second["id"], "mine")        # Reject
        [(channel, said)] = self.told()
        self.assertEqual((channel, said["stream"], said["author"]), (s["session_id"], "the Editor", "the gatherer"))
        self.assertTrue(said["text"].startswith(f"The user rejected your change to notes.py: the project ({self.project}) "
                                                "keeps its own lines there. Your branch still has your version"))
        self.assertIn("Yours:\n```\nx = f() + 1\n```\n\nThe project's:\n```\nx = f()\n```", said["text"])
        self.assertIn("Before you change this file again, read its latest version in the project: "
                      f"{os.path.join(self.project, 'notes.py')}.", said["text"])
        self.assertEqual(self.record.call_args_list[0][0][2][0]["type"], "context_stream")
        self.branches.decide(s["session_id"], "added.txt", "mine")                  # a file it made, not added
        self.assertEqual(self.told()[-1][1]["text"],
                         f"The user did not add added.txt, which you created, to the project ({self.project}): it is only "
                         "on your branch.")

    def test_its_changes_rejected_all_at_once_are_told_together(self):
        self.record = self.enterContext(mock.patch.object(branches.actions, "record"))
        s, wt = self.branch(approve=True)
        self.put(wt, "notes.py", "def f():\n    return 2\n\nx = f() + 1\n")
        self.branches.look(everything=True)
        self.branches.decide(s["session_id"], "notes.py", "mine")
        [(_, said)] = self.told()
        self.assertTrue(said["text"].startswith("The user rejected 2 of your changes to notes.py"))
        self.assertEqual(said["text"].count("Yours:"), 2)
        self.assertEqual(self.get(self.project, "notes.py"), "def f():\n    return 1\n\nx = f()\n")

    def test_a_branch_never_used_goes_with_its_session(self):
        s, wt = self.branch()
        self.started.discard(s["session_id"])
        self.branches.discarded(s["session_id"])
        self.assertFalse(os.path.exists(wt))
        self.assertEqual(self.branches.listed(), [])
        self.assertNotIn(s["branch"]["branch"], git(self.project, "branch", "--list"))


if __name__ == "__main__":
    unittest.main()
