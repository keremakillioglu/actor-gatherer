"""The Editor panel's shared files (ag_dashboard/editor.py): each file open there one Yjs document (pycrdt), which
every page editing it shares, with the file on disk one more of its editors -- what is written to the file merged in,
around what the pages typed and did not save -- and the server's /api/edit/*, through which the pages share it."""
import base64
import json
import os
import queue
import random
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ag_dashboard import editor  # noqa: E402

try:
    from pycrdt import Doc, Text
except ImportError:                                 # the view is not offered without it
    Doc = Text = None


def page_of(init: dict):
    """A page's copy of the document, from its stream's `init`."""
    doc = Doc()
    doc.apply_update(base64.b64decode(init["update"]))
    return doc, doc.get("text", type=Text)


def drain(conn) -> list:
    out = []
    while True:
        try:
            out.append(conn.queue.get_nowait())
        except queue.Empty:
            return out


@unittest.skipIf(Doc is None, "pycrdt is not installed")
class ChangeTest(unittest.TestCase):
    """`change`: a text made to hold another, by what differs."""

    def check(self, old, new):
        doc = Doc()
        doc["t"] = text = Text(old)
        editor.change(text, new)
        self.assertEqual(str(text), new)

    def test_it_makes_the_text_exactly_the_new_one(self):
        for old, new in [("a😀b\nline two\nline three\n", "a😀b\nline 2 😀\n"), ("x\r\ny\r\n", "x\r\nz\r\ny\r\n"),
                         ("", "new\n"), ("gone\n", ""), ("é\nü\n", "é\nüü\nnew\n"), ("same\n", "same\n")]:
            self.check(old, new)

    def test_random_texts_of_wide_characters(self):
        rng = random.Random(7)
        alphabet = "ab\n😀é "
        for _ in range(500):
            self.check("".join(rng.choice(alphabet) for _ in range(rng.randint(0, 30))),
                       "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 30))))

    def test_lines_left_alone_keep_what_was_typed_in_them(self):
        """A change elsewhere does not touch a line: an edit made in it meanwhile, by another, stays."""
        base = Doc()
        base["text"] = Text("one\ntwo\nthree\n")
        page, disk = Doc(), Doc()
        page.apply_update(base.get_update())
        disk.apply_update(base.get_update())
        page.get("text", type=Text).insert(len("one\ntw"), "(o)")
        editor.change(disk.get("text", type=Text), "one\ntwo\nTHREE\n")
        page.apply_update(disk.get_update())
        self.assertEqual(str(page.get("text", type=Text)), "one\ntw(o)o\nTHREE\n")


class MergeTest(unittest.TestCase):
    """`merge`: three ways, by line, as version control merges."""

    BASE = "a\nb\nc\nd\ne\n"

    def check(self, mine, theirs, merged, conflicts=()):
        text, found, _ = editor.merge(self.BASE, mine, theirs)
        self.assertEqual(text, merged)
        self.assertEqual([(text[s:e], t) for s, e, _, t, _ in found], list(conflicts))

    def test_changes_to_different_lines_both_kept(self):
        self.check("A\nb\nc\nd\ne\n", "a\nb\nc\nD\ne\n", "A\nb\nc\nD\ne\n")
        self.check("a\nB\nc\nd\ne\n", "a\nb\nC\nd\ne\n", "a\nB\nC\nd\ne\n")     # side by side too

    def test_the_same_change_is_no_conflict(self):
        self.check("a\nX\nc\nd\ne\n", "a\nX\nc\nd\ne\n", "a\nX\nc\nd\ne\n")

    def test_a_line_changed_on_both_sides_differently_is_a_conflict_mine_kept(self):
        self.check("a\nb\nMINE\nd\ne\n", "a\nb\nTHEIRS\nd\ne\n", "a\nb\nMINE\nd\ne\n", [("MINE\n", "THEIRS\n")])
        self.check("a\nb\nMINE\nd\ne\n", "a\nb\nd\ne\n", "a\nb\nMINE\nd\ne\n", [("MINE\n", "")])   # deleted there
        self.check(self.BASE + "mine\n", self.BASE + "theirs\n", self.BASE + "mine\n", [("mine\n", "theirs\n")])

    def test_lines_guarded_are_a_conflict_when_theirs_changes_them(self):
        text, found, _ = editor.merge(self.BASE, self.BASE, "a\nB\nc\nd\nE\n", guard=[(1, 2)])
        self.assertEqual(text, "a\nb\nc\nd\nE\n")                       # unguarded: merged
        self.assertEqual([(text[s:e], t, zone) for s, e, _, t, zone in found], [("b\n", "B\n", True)])

    def test_lines_put_in_inside_a_guarded_range_are_a_conflict_at_its_edges_not(self):
        inside = editor.merge(self.BASE, self.BASE, "a\nb\nNEW\nc\nd\ne\n", guard=[(1, 3)])
        self.assertEqual(inside[0], self.BASE)
        self.assertEqual([(t, zone) for _, _, _, t, zone in inside[1]], [("NEW\n", True)])
        for theirs in ("a\nNEW\nb\nc\nd\ne\n", "a\nb\nc\nNEW\nd\ne\n"):   # just before it, just after it
            self.assertEqual(editor.merge(self.BASE, self.BASE, theirs, guard=[(1, 3)])[:2], (theirs, []))

    def test_a_change_beside_a_guarded_line_mine_changed_merges(self):
        mine = "a\nb\nMINE\nd\ne\n"                                        # mine's line 2, guarded
        text, found, _ = editor.merge(self.BASE, mine, "a\nb\nc\nNEW\nd\ne\n", guard=[(2, 3)])
        self.assertEqual((text, found), ("a\nb\nMINE\nNEW\nd\ne\n", []))
        text, found, _ = editor.merge(self.BASE, mine, "a\nb\nc\nd\nE\n", guard=[(2, 3)])
        self.assertEqual((text, found), ("a\nb\nMINE\nd\nE\n", []))

    def test_a_guarded_line_is_found_after_lines_mine_put_in_before_it(self):
        mine = "a\nNEW1\nNEW2\nb\nc\nd\ne\n"                              # base's c is mine's line 4, guarded
        text, found, _ = editor.merge(self.BASE, mine, "a\nb\nC\nd\ne\n", guard=[(1, 3), (4, 5)])
        self.assertEqual([(text[s:e], t, zone) for s, e, _, t, zone in found], [("c\n", "C\n", True)])

    def test_guarded_lines_are_mine_s_not_base_s(self):
        mine = "TOP\n" + self.BASE                                          # a line put in here: base's line 1 is mine's 2
        text, found, _ = editor.merge(self.BASE, mine, "a\nB\nc\nd\ne\n", guard=[(2, 3)])
        self.assertEqual([(text[s:e], t) for s, e, _, t, _ in found], [("b\n", "B\n")])

    def test_it_counts_what_only_mine_has(self):
        self.assertEqual(editor.merge(self.BASE, "a\nB\nc\nd\ne\n", self.BASE)[2], 1)
        self.assertEqual(editor.merge(self.BASE, self.BASE, "a\nB\nc\nd\ne\n")[2], 0)


@unittest.skipIf(Doc is None, "pycrdt is not installed")
class RoomTest(unittest.TestCase):
    """A file open for editing: what pages send, what the disk does, and what is saved."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.realpath(self.tmp.name)
        self.path = os.path.join(self.root, "notes.py")
        self.write("def f():\n    return 1\n\nx = f()\n")
        self.editors = editor.Editors(poll=3600)      # looked at by hand here (`check`)
        self.addCleanup(self.editors.close)

    def write(self, text: str) -> None:
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(text)
        st = os.stat(self.path)                      # a later mtime: the same second may not tell writes apart
        os.utime(self.path, ns=(st.st_atime_ns, st.st_mtime_ns + random.randint(1, 10**6)))

    def disk(self) -> str:
        with open(self.path, encoding="utf-8") as fh:
            return fh.read()

    def open(self, cid: str, client: int = 1):
        room, conn = self.editors.join(self.path, self.root, cid, client)
        events = drain(conn)
        self.assertEqual(events[0][0], "init")
        doc, text = page_of(events[0][1])
        return room, conn, doc, text

    def type(self, room, cid, doc, at: int, what: str) -> None:
        before = doc.get_state()
        doc.get("text", type=Text).insert(at, what)
        room.edit(cid, doc.get_update(before))

    def test_a_page_opens_the_file_as_it_is(self):
        room, conn, doc, text = self.open("p1")
        self.assertEqual(str(text), self.disk())
        self.assertFalse(room.dirty)

    def test_a_page_s_edit_reaches_the_others_and_not_itself(self):
        room, c1, d1, t1 = self.open("p1", 1)
        _, c2, d2, t2 = self.open("p2", 2)
        drain(c1)
        self.type(room, "p1", d1, 0, "# hi\n")
        updates = [v for name, v in drain(c2) if name == "update"]
        self.assertEqual(len(updates), 1)
        d2.apply_update(base64.b64decode(updates[0]["update"]))
        self.assertEqual(str(t2), "# hi\n" + self.disk())
        self.assertFalse([v for name, v in drain(c1) if name == "update"])
        self.assertTrue(room.dirty)

    def test_the_disk_s_change_merges_around_what_was_not_saved(self):
        room, conn, doc, text = self.open("p1")
        self.type(room, "p1", doc, 0, "# typed, not saved\n")
        drain(conn)
        self.write("def f():\n    return 2\n\nx = f()\n")          # an actor's edit, on another line
        room.check()
        updates = [v for name, v in drain(conn) if name == "update"]
        self.assertTrue(updates and updates[0]["disk"])
        for u in updates:
            doc.apply_update(base64.b64decode(u["update"]))
        merged = "# typed, not saved\ndef f():\n    return 2\n\nx = f()\n"
        self.assertEqual(str(text), merged)
        self.assertEqual(str(room.text), merged)
        self.assertTrue(room.dirty)                  # the file has the actor's change, not the typed line
        self.assertIsNotNone(room.changed)
        room.save()
        self.assertEqual(self.disk(), merged)
        self.assertFalse(room.dirty)

    def edit(self, room, cid, doc, old: str, new: str) -> None:
        """A page's edit: `old`'s first appearance made `new`."""
        text, before = doc.get("text", type=Text), doc.get_state()
        at = len(str(text)[:str(text).index(old)].encode())
        del text[at:at + len(old.encode())]
        text.insert(at, new)
        room.edit(cid, doc.get_update(before))

    def region(self, room, conflict: dict) -> str:
        """A conflict's lines, as the page finds them: its UTF-16 positions in the document."""
        units = str(room.text).encode("utf-16-le")
        return units[2 * conflict["from"]:2 * conflict["to"]].decode("utf-16-le")

    def test_the_same_lines_changed_on_both_sides_are_a_conflict_not_a_merge(self):
        room, conn, doc, text = self.open("p1")
        self.edit(room, "p1", doc, "return 1", "return 10")             # typed here, not saved
        drain(conn)
        self.write("def f():\n    return 2\n\nx = f()\n")                # the actor's, the same line
        room.check()
        self.assertFalse([v for name, v in drain(conn) if name == "update"])   # nothing merged into the page's line
        self.assertIn("return 10", str(room.text))
        [c] = room.state()["conflicts"]
        self.assertEqual((self.region(room, c), c["theirs"], c["base"]), ("    return 10\n", "    return 2\n", "    return 1\n"))
        self.assertIn("return 2", self.disk())                          # the file is the actor's until a page says
        room.settle(c["id"], "theirs")
        self.assertEqual(str(room.text), self.disk())
        self.assertEqual(room.state()["conflicts"], [])
        self.assertFalse(room.dirty)

    def test_lines_changed_on_one_side_merge_around_a_conflict(self):
        room, conn, doc, text = self.open("p1")
        self.edit(room, "p1", doc, "return 1", "return 10")
        self.write("# top\ndef f():\n    return 2\n\nx = f()\ny = 2\n")  # a line above, the same line, a line below
        room.check()
        self.assertEqual(str(room.text), "# top\ndef f():\n    return 10\n\nx = f()\ny = 2\n")
        self.assertEqual(len(room.conflicts), 1)

    def test_keep_both_and_keep_mine(self):
        room, conn, doc, text = self.open("p1")
        self.type(room, "p1", doc, len(str(text)), "y = 3\n")
        self.write("def f():\n    return 1\n\nx = f()\nz = 9\n")          # both put a line at the end
        room.check()
        [c] = room.state()["conflicts"]
        self.assertEqual((self.region(room, c), c["theirs"]), ("y = 3\n", "z = 9\n"))
        room.settle(c["id"], "both")
        self.assertTrue(str(room.text).endswith("x = f()\ny = 3\nz = 9\n"))
        self.edit(room, "p1", doc, "return 1", "return 3")
        self.write("def f():\n    return 4\n\nx = f()\nz = 9\n")
        room.check()
        [c] = room.state()["conflicts"]
        room.settle(c["id"], "mine")
        self.assertIn("return 3", str(room.text))
        self.assertTrue(room.dirty)                                      # the file has the actor's: a save writes mine
        with self.assertRaisesRegex(editor.EditorError, "settled already"):
            room.settle(c["id"], "theirs")

    def test_a_conflict_s_lines_move_with_edits_before_them(self):
        room, conn, doc, text = self.open("p1")
        self.edit(room, "p1", doc, "x = f()", "x = f() * 2")
        self.write("def f():\n    return 1\n\nx = g()\n")
        room.check()
        self.type(room, "p1", doc, 0, "# 😀 a wide note above\n")        # wider in UTF-8 than in UTF-16
        self.edit(room, "p1", doc, "* 2", "* 3")                         # and in it
        [c] = room.state()["conflicts"]
        self.assertEqual(self.region(room, c), "x = f() * 3\n")

    def test_a_save_does_not_overwrite_a_conflict_it_just_found(self):
        room, conn, doc, text = self.open("p1")
        self.type(room, "p1", doc, len(str(text)), "y = 3\n")
        self.write("def f():\n    return 1\n\nx = f()\nz = 9\n")    # not looked at before the save
        with self.assertRaisesRegex(editor.EditorError, "see the conflicts"):
            room.save()
        self.assertTrue(self.disk().endswith("z = 9\n"))               # the actor's line still there
        [c] = room.state()["conflicts"]
        room.settle(c["id"], "both")
        room.save()
        self.assertEqual(self.disk(), "def f():\n    return 1\n\nx = f()\ny = 3\nz = 9\n")

    def test_a_save_keeps_the_lines_of_a_conflict_already_shown(self):
        room, conn, doc, text = self.open("p1")
        self.edit(room, "p1", doc, "return 1", "return 10")
        self.write("def f():\n    return 2\n\nx = f()\n")
        room.check()
        room.save()
        self.assertIn("return 10", self.disk())
        self.assertEqual(room.conflicts, {})

    def test_a_write_from_before_a_save_does_not_undo_it_unasked(self):
        room, conn, doc, text = self.open("p1")
        self.edit(room, "p1", doc, "return 1", "return 5")
        room.save()
        self.write("def f():\n    return 1\n\nx = f() + 1\n")          # a script's: the file before the save, changed
        room.check()
        self.assertEqual(str(room.text), "def f():\n    return 5\n\nx = f() + 1\n")   # its other change merged
        [c] = room.state()["conflicts"]                                  # the saved line: asked about
        self.assertEqual((self.region(room, c), c["theirs"], c["zone"]), ("    return 5\n", "    return 1\n", True))

    def test_undoing_a_save_on_purpose_is_asked_then_taken(self):
        room, conn, doc, text = self.open("p1")
        original = str(text)
        self.edit(room, "p1", doc, "return 1", "return 5")
        room.save()
        self.write(original)                                             # `git checkout` of the file, say
        room.check()
        [c] = room.state()["conflicts"]
        room.settle(c["id"], "theirs")
        self.assertEqual(str(room.text), original)
        self.assertFalse(room.dirty)

    def test_a_change_after_a_save_to_other_lines_merges(self):
        room, conn, doc, text = self.open("p1")
        self.edit(room, "p1", doc, "return 1", "return 5")
        room.save()
        self.write("def f():\n    return 5\n\nx = f() + 1\n")          # read after the save, changed elsewhere
        room.check()
        self.assertEqual(str(room.text), self.disk())
        self.assertEqual(room.conflicts, {})

    def test_an_actor_rewriting_lines_edited_here_is_asked_about(self):
        """Auto-saved as typed, then rewritten by an actor that read them: the lines kept, its rewrite shown."""
        room, conn, doc, text = self.open("p1")
        self.edit(room, "p1", doc, "return 1", "return 5")
        room.save()
        self.edit(room, "p1", doc, "x = f()", "x = f() * 2")              # a second save, of another line
        room.save()
        self.write("def f():\n    return 6\n\nx = f() * 3\n")          # read after both, rewrote both
        room.check()
        found = sorted((self.region(room, c), c["theirs"], c["zone"]) for c in room.state()["conflicts"])
        self.assertEqual(found, [("    return 5\n", "    return 6\n", True), ("x = f() * 2\n", "x = f() * 3\n", True)])

    def zone(self, room) -> list:
        """The conflict zone's text, as the page finds it: its UTF-16 ranges of the document."""
        return [self.region(room, {"from": a, "to": b}) for a, b in room.state()["zone"]]

    def test_the_zone_is_what_the_pages_changed_moved_with_every_edit(self):
        room, conn, doc, text = self.open("p1")
        self.assertEqual(self.zone(room), [])
        self.edit(room, "p1", doc, "return 1", "return 1  # 😀 one")
        self.assertEqual(self.zone(room), ["return 1  # 😀 one"])
        self.write("# a line the actor put on top\ndef f():\n    return 1  # 😀 one\n\nx = f()\n")
        room.check()                                                     # the disk's: not in it, and it moves
        self.assertEqual(self.zone(room), ["return 1  # 😀 one"])
        self.edit(room, "p1", doc, "x = f()\n", "")                        # a line taken out: where it was
        self.assertEqual(len(room.zone), 2)
        self.assertEqual(room.zone[1][0], room.zone[1][1])

    def test_a_line_in_the_zone_changed_by_the_actor_after_a_save_is_asked_about(self):
        room, conn, doc, text = self.open("p1")
        self.edit(room, "p1", doc, "return 1", "return 5")
        room.save()
        room.check()
        self.write("def f():\n    return 6\n\nx = f() + 1\n")          # its line, and another
        room.check()
        self.assertEqual(str(room.text), "def f():\n    return 5\n\nx = f() + 1\n")
        [c] = room.state()["conflicts"]
        self.assertTrue(c["zone"])

    def test_cleared_the_zone_s_lines_are_the_file_s_again(self):
        room, conn, doc, text = self.open("p1")
        self.edit(room, "p1", doc, "return 1", "return 5")
        room.save()
        self.assertEqual(room.clear_zone()["zone"], [])
        self.write("def f():\n    return 6\n\nx = f()\n")
        room.check()
        self.assertEqual(room.conflicts, {})
        self.assertIn("return 6", str(room.text))

    def test_the_actor_s_rewrite_taken_is_not_the_zone_s(self):
        room, conn, doc, text = self.open("p1")
        self.edit(room, "p1", doc, "return 1", "return 5")
        room.save()
        self.write("def f():\n    return 6\n\nx = f()\n")
        room.check()
        [c] = room.state()["conflicts"]
        room.settle(c["id"], "theirs")
        self.write("def f():\n    return 7\n\nx = f()\n")              # the actor again: merged, not asked
        room.check()
        self.assertEqual((room.conflicts, self.disk()), ({}, str(room.text)))

    def test_a_second_actor_s_change_to_a_conflict_s_lines_is_that_conflict_s(self):
        """Two actors: the first rewrote a line edited here (a conflict); the second, reading the file, added to the
        first's rewrite. Not merged around the line kept here: the conflict shows the file's lines as they are now."""
        room, conn, doc, text = self.open("p1")
        self.edit(room, "p1", doc, "return 1", "return 1  # many shapes, I suppose")
        room.save()
        self.write("def f():\n    return 1  # circle\n    # square\n\nx = f()\n")     # the first actor's, in its place
        room.check()
        [first] = room.state()["conflicts"]
        self.write("def f():\n    return 1  # circle\n    # square\n    # kite\n\nx = f()\n")   # the second's, after it
        room.check()
        self.assertEqual(str(room.text), "def f():\n    return 1  # many shapes, I suppose\n\nx = f()\n")
        [c] = room.state()["conflicts"]
        self.assertEqual(c["theirs"], "    return 1  # circle\n    # square\n    # kite\n")
        self.assertEqual((c["since"], c["zone"]), (first["since"], True))
        self.assertGreater(c["at"], first["at"])
        room.settle(c["id"], "theirs")
        self.assertEqual(str(room.text), self.disk())

    def test_the_zone_goes_once_the_file_s_last_page_closed_it(self):
        room, conn, doc, text = self.open("p1")
        self.edit(room, "p1", doc, "return 1", "return 5")
        room.save()
        room.leave(conn)
        self.editors.look()
        self.assertTrue(room.zone)                                       # its stream may come back: kept a moment
        room.idle_since -= editor.ZONE_GRACE + 1
        self.editors.look()
        self.assertEqual(room.zone, [])

    def test_a_save_writes_its_own_file_only_and_keeps_its_mode(self):
        os.chmod(self.path, 0o755)
        room, conn, doc, text = self.open("p1")
        self.type(room, "p1", doc, 0, "#!/bin/sh\n")
        room.save()
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o755)
        self.assertEqual(sorted(os.listdir(self.root)), ["notes.py"])   # nothing left beside it
        room.check()                                 # its own write: no change from the disk
        self.assertFalse([v for name, v in drain(conn) if name == "update" and v.get("disk")])

    def test_a_file_deleted_on_disk_is_written_again_by_a_save(self):
        room, conn, doc, text = self.open("p1")
        os.unlink(self.path)
        room.check()
        self.assertTrue(room.missing)
        room.save()
        self.assertEqual(self.disk(), str(text))
        self.assertFalse(room.missing)

    def test_a_page_that_goes_takes_its_cursor_with_it(self):
        room, c1, _, _ = self.open("p1", 11)
        room2, c2, _, _ = self.open("p2", 22)
        room.aware("p1", b"\x01\x02")
        self.assertIn(("aware", {"update": base64.b64encode(b"\x01\x02").decode()}), drain(c2))
        _, c3, _, _ = self.open("p3", 33)                   # a page that comes later is sent the others' cursors
        room.leave(c1)
        self.assertIn(("left", {"client": 11}), drain(c2))

    def test_a_page_s_stream_again_ends_the_old_one(self):
        room, c1, _, _ = self.open("p1")
        _, again, _, _ = self.open("p1")
        self.assertIsNone(c1.queue.get_nowait())
        self.assertIs(room.conns["p1"], again)

    def test_a_file_with_unsaved_changes_stays_open_after_its_pages_go(self):
        room, conn, doc, text = self.open("p1")
        self.type(room, "p1", doc, 0, "# kept\n")
        room.leave(conn)
        clean = os.path.join(self.root, "clean.txt")
        with open(clean, "w") as fh:
            fh.write("x\n")
        other, oc = self.editors.join(clean, self.root, "p2", 2)
        other.leave(oc)
        with mock.patch.object(editor, "LINGER", 0.0):
            self.editors.poll = 0.01
            self.editors.stop.set()
            self.editors.thread.join()
            self.editors.stop.clear()
            self.editors.thread = threading.Thread(target=self.editors._watch, daemon=True)
            self.editors.thread.start()
            for _ in range(200):
                if os.path.realpath(clean) not in self.editors.rooms:
                    break
                time.sleep(0.01)
        self.assertNotIn(os.path.realpath(clean), self.editors.rooms)
        self.assertIn(self.path, self.editors.rooms)
        _, again, d2, t2 = self.open("p3")
        self.assertTrue(str(t2).startswith("# kept\n"))

    def test_what_cannot_be_opened(self):
        with open(os.path.join(self.root, "b.bin"), "wb") as fh:
            fh.write(b"\x00\x01\x02")
        with open(os.path.join(self.root, "latin.txt"), "wb") as fh:
            fh.write("café".encode("latin-1"))
        for path, said in [("/etc/hosts", "not under"), (os.path.join(self.root, "b.bin"), "not a text file"),
                           (os.path.join(self.root, "latin.txt"), "not UTF-8"),
                           (os.path.join(self.root, "none.txt"), "does not exist"), (self.root, "not a file"),
                           ("notes.py", "absolute")]:
            with self.assertRaisesRegex(editor.EditorError, said):
                self.editors.join(path, self.root, "p", 1)
        with mock.patch.object(editor, "MAX_BYTES", 10):
            with self.assertRaisesRegex(editor.EditorError, "too large"):
                self.editors.join(self.path, self.root, "p", 1)

    def test_a_link_out_of_the_root_is_refused(self):
        os.symlink("/etc/hosts", os.path.join(self.root, "hosts"))
        with self.assertRaisesRegex(editor.EditorError, "not under"):
            self.editors.join(os.path.join(self.root, "hosts"), self.root, "p", 1)

    def test_the_listing(self):
        os.makedirs(os.path.join(self.root, "src"))
        os.makedirs(os.path.join(self.root, ".git"))
        os.makedirs(os.path.join(self.root, "node_modules"))
        with open(os.path.join(self.root, "a.txt"), "w") as fh:
            fh.write("a")
        with open(os.path.join(self.root, ".x.py.123" + editor.TEMP), "w") as fh:
            fh.write("half written")
        room, conn, doc, text = self.open("p1")
        self.type(room, "p1", doc, 0, "#")
        got = self.editors.listing(self.root, self.root)
        self.assertEqual([e["name"] for e in got["entries"]], ["src", "a.txt", "notes.py"])
        notes = got["entries"][2]
        self.assertEqual((notes["editors"], notes["dirty"]), (1, True))
        self.assertEqual(got["entries"][1]["editors"], 0)
        with self.assertRaisesRegex(editor.EditorError, "not under"):
            self.editors.listing("/etc", self.root)


@unittest.skipIf(Doc is None, "pycrdt is not installed")
class WritersTest(unittest.TestCase):
    """Who changed each listed file, of the actors: what ag's hook found their tool calls did on disk (`file_touched`)."""

    def setUp(self):
        from datetime import datetime, timezone
        import sqlite3
        from ag_dashboard import home as dashboard_home
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.saved, dashboard_home.HOME = dashboard_home.HOME, os.path.join(self.tmp.name, "home")
        self.addCleanup(setattr, dashboard_home, "HOME", self.saved)
        self.work = os.path.join(os.path.realpath(self.tmp.name), "work")
        os.makedirs(os.path.join(self.work, "src"))
        for name in ("a.py", "b.py", "c.py"):
            with open(os.path.join(self.work, "src", name), "w") as fh:
                fh.write("x = 1\n")
        os.makedirs(os.path.join(dashboard_home.HOME, "gatherers", "g"))
        conn = sqlite3.connect(os.path.join(dashboard_home.HOME, "gatherers", "g", "context.db"))
        conn.executescript("""CREATE TABLE event_types (event_type_id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, created_at TEXT);
            CREATE TABLE events (row_id INTEGER PRIMARY KEY, inserted_at TEXT NOT NULL, event_id TEXT, event_type_id INTEGER NOT NULL,
              payload_json TEXT NOT NULL, tokens INTEGER NOT NULL, text TEXT, counted INTEGER, p_channel);
            INSERT INTO event_types (name) VALUES ('user_message'), ('file_touched');""")
        stamp = lambda ago: datetime.fromtimestamp(time.time() - ago, timezone.utc).isoformat()   # noqa: E731
        src = os.path.join(self.work, "src")
        conn.executemany("INSERT INTO events (inserted_at, event_type_id, payload_json, tokens, p_channel) VALUES (?, ?, ?, 0, ?)", [
            (stamp(editor.RECENT + 600), 2, json.dumps({"call": "t5", "path": f"{src}/c.py", "how": "modified"}), "c3"),   # too long ago
            (stamp(300), 2, json.dumps({"call": "t1", "path": f"{src}/a.py", "how": "modified"}), "c1"),
            (stamp(60), 2, json.dumps({"call": "t2", "path": f"{src}/a.py", "how": "modified"}), "c1"),       # c1's latest
            (stamp(30), 2, json.dumps({"call": "t3", "path": f"{src}/a.py", "how": "modified"}), "c2"),       # a second actor on it
            (stamp(25), 1, json.dumps({"role": "user", "content": "hi"}), "c1"),                               # not a touch
            (stamp(20), 2, json.dumps({"call": "t4", "path": f"{src}/b.py", "how": "read"}), "c1"),           # a read changes nothing
            (stamp(10), 2, json.dumps({"call": "t6", "path": None, "how": None}), "c1")])                     # a call that touched no file
        conn.commit()
        conn.close()
        self.editors = editor.Editors(poll=3600)
        self.addCleanup(self.editors.close)

    def test_a_file_changed_by_two_actors_lists_both_the_latest_first(self):
        got = {e["name"]: e["writers"] for e in self.editors.listing(os.path.join(self.work, "src"), "/")["entries"]}
        self.assertEqual([w["channel"] for w in got["a.py"]], ["c2", "c1"])
        self.assertTrue(all(w["gatherer"] == "g" and w["how"] == "modified" for w in got["a.py"]))
        self.assertGreater(got["a.py"][0]["at"], got["a.py"][1]["at"])
        self.assertEqual(got["b.py"], [])
        self.assertEqual(got["c.py"], [])

    def test_a_folder_lists_who_changed_what_is_in_it(self):
        got = {e["name"]: e["writers"] for e in self.editors.listing(self.work, "/")["entries"]}
        self.assertEqual([w["channel"] for w in got["src"]], ["c2", "c1"])


def asked(text):
    return ("user_message", {"role": "user", "content": [{"type": "text", "text": text}]})


def bash(cid, command):
    return ("tool_call", {"role": "assistant", "content": [{"type": "tool_use", "id": cid, "name": "Bash", "input": {"command": command}}]})


class PlaceTest(unittest.TestCase):
    """Where an actor's work is, the Editor opened from its pane shows: the folder holding all the files it changed
    lately -- in its latest turn that changed any, and the last few minutes -- but not by git."""

    def setUp(self):
        import sqlite3
        from ag_dashboard import files, home as dashboard_home
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        top = os.path.realpath(self.tmp.name)
        self.saved, dashboard_home.HOME = dashboard_home.HOME, os.path.join(top, "home")
        self.addCleanup(setattr, dashboard_home, "HOME", self.saved)
        self.work, self.scratch, self.claude = (os.path.join(top, n) for n in ("work", "scratch", "claude"))
        for d in ("src/app", "src/lib", "docs"):
            os.makedirs(os.path.join(self.work, d))
        # the test's own folder is in the system's temporary one: only `scratch` is, here
        for patcher in (mock.patch.object(files, "TEMPORARY", (self.scratch,)), mock.patch.object(files, "HARNESS_FOLDERS", (self.claude,))):
            patcher.start()
            self.addCleanup(patcher.stop)
        os.makedirs(os.path.join(dashboard_home.HOME, "gatherers", "g"))
        self.conn = sqlite3.connect(os.path.join(dashboard_home.HOME, "gatherers", "g", "context.db"))
        self.addCleanup(self.conn.close)
        self.conn.executescript("""CREATE TABLE event_types (event_type_id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, created_at TEXT);
            CREATE TABLE events (row_id INTEGER PRIMARY KEY, inserted_at TEXT NOT NULL, event_id TEXT, event_type_id INTEGER NOT NULL,
              payload_json TEXT NOT NULL, tokens INTEGER NOT NULL, text TEXT, counted INTEGER, p_channel);""")

    def add(self, channel: str, *events, ago: float = 3600.0) -> None:
        """Events of `channel`, after those there, stored `ago` seconds back: (type, payload), each."""
        from datetime import datetime, timezone
        at = datetime.fromtimestamp(time.time() - ago, timezone.utc).isoformat()
        for typ, payload in events:
            got = self.conn.execute("SELECT event_type_id FROM event_types WHERE name = ?", (typ,)).fetchone()
            tid = got[0] if got else self.conn.execute("INSERT INTO event_types (name) VALUES (?)", (typ,)).lastrowid
            self.conn.execute("INSERT INTO events (inserted_at, event_type_id, payload_json, tokens, p_channel) VALUES (?, ?, ?, 0, ?)",
                              (at, tid, json.dumps(payload), channel))
        self.conn.commit()

    def touched(self, channel: str, *changes, call: str = "t", ago: float = 3600.0) -> None:
        """A call's changes, as ag's hook records them: (path, how), each."""
        self.add(channel, *[("file_touched", {"call": call, "path": p, "how": how}) for p, how in changes], ago=ago)

    def test_the_folder_holding_all_its_changes(self):
        w = self.work
        self.touched("c1", (f"{w}/src/app/a.py", "modified"), (f"{w}/src/lib/b.py", "created"), (f"{w}/src/lib/c.py", "deleted"),
                     (f"{w}/docs/d.md", "read"), (f"{w}/docs/e.md", "hit"), (None, None))    # a read is no change
        self.touched("c2", (f"{w}/docs/x.md", "modified"))                                   # another actor's
        self.assertEqual(editor.place("g", "c1", w), os.path.join(w, "src"))
        self.assertEqual(editor.place("g", "c2", w), os.path.join(w, "docs"))

    def test_a_temporary_folder_ag_s_home_or_a_harness_s_own_is_not_the_work(self):
        from ag_dashboard import home as dashboard_home
        w = self.work
        self.touched("c1", (f"{w}/src/app/a.py", "modified"), (f"{self.scratch}/notes.md", "created"),
                     (f"{dashboard_home.HOME}/gatherers/g/context.db", "modified"),
                     (f"{self.claude}/projects/-work/c1.jsonl", "modified"), (f"{self.claude}/projects/-work/memory/m.md", "created"))
        self.assertEqual(editor.place("g", "c1", w), os.path.join(w, "src", "app"))

    def test_under_its_working_directory_a_temporary_folder_is_its_work(self):
        project = os.path.join(self.scratch, "project")
        os.makedirs(os.path.join(project, "src"))
        self.touched("c1", (f"{project}/src/a.py", "modified"), (f"{project}/README.md", "modified"),
                     (f"{self.scratch}/other/notes.md", "created"))
        self.assertEqual(editor.place("g", "c1", project), project)

    def test_a_folder_since_removed_gives_the_nearest_still_there(self):
        self.touched("c1", (f"{self.work}/src/gone/deeper/a.py", "deleted"))
        self.assertEqual(editor.place("g", "c1", self.work), os.path.join(self.work, "src"))

    def test_none_without_a_change_counted(self):
        self.touched("c1", (f"{self.work}/src/app/a.py", "read"), (f"{self.scratch}/notes.md", "created"))
        self.assertIsNone(editor.place("g", "c1", self.work))
        self.assertIsNone(editor.place("g", "nobody", self.work))
        self.assertIsNone(editor.place("no such gatherer", "c1", self.work))

    def test_what_git_changed_is_not_its_work_but_what_the_command_names(self):
        from ag_dashboard import files
        w = self.work
        self.add("c1", ("model_call", {"kind": "turn", "harness": "claude"}), asked("pull, then fix the docs"),
                 bash("g1", f"cd {w} && git status --short; git pull -q origin main > docs/pull.log 2>&1"))
        self.touched("c1", (f"{w}/src/app/a.py", "modified"), (f"{w}/src/lib/b.py", "created"), (f"{w}/docs/pull.log", "created"), call="g1")
        self.add("c1", bash("b1", f"cd {w} && git status --short && sed -i '' 's/a/b/' docs/x.md"))   # git changing nothing
        self.touched("c1", (f"{w}/docs/x.md", "modified"), call="b1")
        self.assertEqual(files.lately_changed("g", "c1", w), [f"{w}/docs/pull.log", f"{w}/docs/x.md"])
        self.assertEqual(editor.place("g", "c1", w), os.path.join(w, "docs"))

    def test_a_change_no_call_names_is_not_its_work(self):
        w = self.work
        self.add("c1", ("file_touched", {"call": "e1", "path": f"{w}/docs/x.md", "how": "modified", "named": True}),
                 ("file_touched", {"call": "b1", "path": f"{w}/src/app/a.py", "how": "modified", "named": False}))  # changed meanwhile
        self.assertEqual(editor.place("g", "c1", w), os.path.join(w, "docs"))

    def test_its_latest_turn_that_changed_files(self):
        w = self.work
        self.add("c1", asked("fix a"))
        self.touched("c1", (f"{w}/src/app/a.py", "modified"), call="t1")
        self.add("c1", asked("now b"))
        self.touched("c1", (f"{w}/src/lib/b.py", "modified"), (f"{w}/src/lib/c.py", "created"), call="t2")
        self.add("c1", asked("thanks"))                                                       # a turn that changed none
        self.assertEqual(editor.place("g", "c1", w), os.path.join(w, "src", "lib"))

    def test_and_what_it_changed_in_the_last_minutes(self):
        w = self.work
        self.add("c1", asked("write the docs"))
        self.touched("c1", (f"{w}/docs/d.md", "created"), call="t1")                          # an hour ago
        self.add("c1", asked("fix a"), ago=300)
        self.touched("c1", (f"{w}/src/app/a.py", "modified"), call="t2", ago=290)
        self.add("c1", asked("now b"), ago=60)
        self.touched("c1", (f"{w}/src/lib/b.py", "modified"), call="t3", ago=50)
        self.assertEqual(editor.place("g", "c1", w), os.path.join(w, "src"))

    def test_the_page_asks_the_server(self):
        from ag_dashboard import server
        self.touched("c1", (f"{self.work}/src/app/a.py", "modified"), (f"{self.work}/src/lib/b.py", "modified"))
        httpd = server.serve("127.0.0.1", 0, live_updates=False)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        q = urllib.parse.urlencode({"gatherer": "g", "channel": "c1", "cwd": self.work})
        got = json.load(urllib.request.urlopen(f"http://127.0.0.1:{httpd.server_port}/api/edit/place?{q}", timeout=10))
        self.assertEqual(got, {"dir": os.path.join(self.work, "src")})


@unittest.skipIf(Doc is None, "pycrdt is not installed")
class ServerTest(unittest.TestCase):
    """The pages' side: a file opened by a stream, edited and saved by POSTs, through the dashboard's server."""

    def setUp(self):
        from ag_dashboard import home as dashboard_home, server
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.saved, dashboard_home.HOME = dashboard_home.HOME, os.path.join(self.tmp.name, "home")
        self.addCleanup(setattr, dashboard_home, "HOME", self.saved)
        self.root = os.path.join(os.path.realpath(self.tmp.name), "work")
        os.makedirs(self.root)
        self.path = os.path.join(self.root, "a.md")
        with open(self.path, "w") as fh:
            fh.write("# Title\n\nBody.\n")
        with mock.patch.object(editor, "POLL", 0.05):
            self.httpd = server.serve("127.0.0.1", 0, live_updates=False)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"

    def stream(self, conn: str, client: int) -> queue.Queue:
        q = urllib.parse.urlencode({"path": self.path, "root": self.root, "conn": conn, "client": client})
        resp = urllib.request.urlopen(f"{self.url}/api/edit/stream?{q}", timeout=10)
        self.addCleanup(resp.close)
        got = queue.Queue()

        def read():
            name = None
            try:
                for raw in resp:
                    line = raw.decode().rstrip("\n")
                    if line.startswith("event: "):
                        name = line[7:]
                    elif line.startswith("data: "):
                        got.put((name, json.loads(line[6:])))
            except Exception:                        # noqa: BLE001 - closed
                pass
        threading.Thread(target=read, daemon=True).start()
        return got

    def next(self, events: queue.Queue, name: str) -> dict:
        deadline = time.time() + 10
        while time.time() < deadline:
            got, value = events.get(timeout=deadline - time.time())
            if got == name:
                return value
        self.fail(f"no {name}")

    def post(self, path: str, body: dict, kind: str = "application/json"):
        req = urllib.request.Request(self.url + path, data=json.dumps(body).encode(), headers={"Content-Type": kind})
        return json.load(urllib.request.urlopen(req, timeout=10))

    def test_two_pages_share_the_file_and_the_disk_s_changes(self):
        e1, e2 = self.stream("p1", 1), self.stream("p2", 2)
        d1, t1 = page_of(self.next(e1, "init"))
        d2, t2 = page_of(self.next(e2, "init"))
        before = d1.get_state()
        t1.insert(len("# Title\n\n"), "Typed. ")
        state = self.post("/api/edit/update", {"path": self.path, "root": self.root, "conn": "p1",
                                               "update": base64.b64encode(d1.get_update(before)).decode()})
        self.assertTrue(state["dirty"])
        d2.apply_update(base64.b64decode(self.next(e2, "update")["update"]))
        self.assertEqual(str(t2), "# Title\n\nTyped. Body.\n")
        with open(self.path, "a") as fh:                    # an actor's change on disk, merged in as it lands
            fh.write("\nMore.\n")
        for d, e in ((d1, e1), (d2, e2)):
            got = self.next(e, "update")
            self.assertTrue(got["disk"])
            d.apply_update(base64.b64decode(got["update"]))
        self.assertEqual(str(t1), str(t2))
        self.assertEqual(str(t1), "# Title\n\nTyped. Body.\n\nMore.\n")
        saved = self.post("/api/edit/save", {"path": self.path, "root": self.root})
        self.assertFalse(saved["dirty"])
        with open(self.path) as fh:
            self.assertEqual(fh.read(), "# Title\n\nTyped. Body.\n\nMore.\n")
        self.assertTrue(saved["zone"])                                   # what p1 typed: kept after the save
        self.assertEqual(self.post("/api/edit/zone/clear", {"path": self.path, "root": self.root})["zone"], [])

    def test_the_listing_and_what_is_refused(self):
        got = json.load(urllib.request.urlopen(
            f"{self.url}/api/edit/list?{urllib.parse.urlencode({'dir': self.root, 'root': self.root})}", timeout=10))
        self.assertEqual([e["name"] for e in got["entries"]], ["a.md"])
        with self.assertRaises(urllib.error.HTTPError) as no:
            urllib.request.urlopen(f"{self.url}/api/edit/list?{urllib.parse.urlencode({'dir': '/etc', 'root': self.root})}", timeout=10)
        self.assertEqual(no.exception.code, 400)
        with self.assertRaises(urllib.error.HTTPError) as no:           # not the page's own: no JSON
            self.post("/api/edit/save", {"path": self.path, "root": self.root}, kind="text/plain")
        self.assertEqual(no.exception.code, 403)
        q = urllib.parse.urlencode({"path": "/etc/hosts", "root": self.root, "conn": "p", "client": 1})
        with urllib.request.urlopen(f"{self.url}/api/edit/stream?{q}", timeout=10) as resp:
            self.assertIn(b"event: failed", resp.read())

    def test_the_editor_is_served_and_said_to_be_there(self):
        with urllib.request.urlopen(f"{self.url}/vendor/editor.js", timeout=10) as resp:
            self.assertIn(b"agEditor", resp.read())
        self.assertTrue(json.load(urllib.request.urlopen(f"{self.url}/api/home", timeout=10))["editor"])


if __name__ == "__main__":
    unittest.main()
