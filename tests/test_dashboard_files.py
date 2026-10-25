"""The dashboard's Files view (ag_dashboard/files.py): a turn's files, each with the lines the
agent saw -- by Read, or by a shell command that only prints part of a file -- and its edits
in place among them, by an edit tool or by a shell command whose change can be read from it."""
import json
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ag_dashboard import files  # noqa: E402
from ag_dashboard import home as dashboard_home  # noqa: E402


class ShellReadsTest(unittest.TestCase):
    """What a shell command read, told from its output."""

    def test_reads_are_split_out_of_one_output(self):
        found, other = files.shell_reads("sed -n 3,4p a.py; grep -n x b.py | head -3; sed -n 10,11p c.py",
                                         "L3\nL4\n5:x\n9:xx\nL10\nL11", "/w")
        self.assertEqual(found, [("/w/a.py", "lines", 3, ["L3", "L4"]), ("/w/b.py", "hit", 5, "x"),
                                 ("/w/b.py", "hit", 9, "xx"), ("/w/c.py", "lines", 10, ["L10", "L11"])])
        self.assertTrue(other)                                   # a search is not only reading

    def test_cd_sets_the_directory_and_a_command_of_unknown_size_is_split_from_the_back(self):
        found, other = files.shell_reads("cd /r && git status --short; cat d.txt | head -2; sed -n 1,2p e.py",
                                         " M f\n?? g\nd1\nd2\ne1\ne2", "/w")
        self.assertEqual(found, [("/r/d.txt", "lines", 1, ["d1", "d2"]), ("/r/e.py", "lines", 1, ["e1", "e2"])])
        self.assertTrue(other)

    def test_a_read_between_two_of_unknown_size_is_not_guessed(self):
        found, _ = files.shell_reads("ls; cat a.py; git log", "x\ny\nz", "/w")
        self.assertEqual(found, [("/w/a.py", "unsplit", None, [])])

    def test_numbered_and_recursive_searches(self):
        self.assertEqual(files.shell_reads("cat -n a.py", "     7\tseven", "/w")[0], [("/w/a.py", "lines", 7, ["seven"])])
        self.assertEqual(files.shell_reads("grep -rn foo src", "src/a.py:3:foo", "/w")[0], [("/w/src/a.py", "hit", 3, "foo")])
        only_reads = files.shell_reads("sed -n 1p a.py", "one", "/w")
        self.assertEqual(only_reads, ([("/w/a.py", "lines", 1, ["one"])], False))

    def test_what_cannot_be_read_plainly_is_left_as_a_command(self):
        self.assertEqual(files.shell_reads("cat $(ls)", "x", "/w"), ([], True))
        self.assertEqual(files.shell_reads("python3 - <<'EOF'\nprint(1)\nEOF", "1", "/w"), ([], True))


class ShellChangesTest(unittest.TestCase):
    """What a shell command changed, read from the command."""

    def test_a_heredoc_or_echo_into_a_file_writes_it(self):
        self.assertEqual(files.shell_changes("cat > n.txt <<'EOF'\nhello\nworld\nEOF", "/w"),
                         ([("/w/n.txt", "write", "hello\nworld")], True))
        self.assertEqual(files.shell_changes("cd sub && cat >> log <<EOF\nmore\nEOF\necho done", "/w"),
                         ([("/w/sub/log", "append", "more")], True))
        self.assertEqual(files.shell_changes("S=/tmp/x; echo 1 > $S/id", "/w"), ([("/tmp/x/id", "write", "1")], True))
        self.assertEqual(files.shell_changes("ls 2>err.log >/dev/null", "/w"), ([], False))   # stderr, and nowhere

    def test_sed_in_place_changes_files_it_cannot_say_where(self):
        self.assertEqual(files.shell_changes("sed -i 's/a/b/' x.py y.py && git diff", "/w"),
                         ([("/w/x.py", "changed", "sed -i s/a/b/"), ("/w/y.py", "changed", "sed -i s/a/b/")], False))

    def test_a_python_script_s_replacements_go_to_the_file_it_writes(self):
        script = """cd /r && python3 - <<'EOF'
p = "a/b.py"; s = open(p).read()
def sub(old, new):
    global s
    s = s.replace(old, new)
sub("x = 1", "x = 2")
for o, n in [("foo", "bar"), (\"\"\"two
lines\"\"\", "one")]:
    s = s.replace(o, n)
open(p, "w").write(s)
from pathlib import Path
Path("c.txt").write_text("hi")
EOF"""
        self.assertEqual(files.shell_changes(script, "/w"), ([
            ("/r/a/b.py", "pairs", [("x = 1", "x = 2"), ("foo", "bar"), ("two\nlines", "one")]),
            ("/r/c.txt", "changed", "a Python script")], False))
        self.assertEqual(files.python_changes("s = open('a').read().replace(x, 'y')\nopen('a', 'w').write(s)", "/w"),
                         [("/w/a", [])])                    # a replacement not made of constants: changed, lines unknown


def call(cid, name, inp):
    return ("tool_call", {"role": "assistant", "content": [{"type": "tool_use", "id": cid, "name": name, "input": inp}]})


def result(cid, text, error=False):
    return ("tool_output", {"role": "user", "content": [{"type": "tool_result", "tool_use_id": cid, "is_error": error, "content": text}]})


def said(text):
    return ("agent_message", {"role": "assistant", "content": [{"type": "text", "text": text}]})


def thought(text):
    return ("agent_reasoning", {"role": "assistant", "content": [{"type": "thinking", "thinking": text, "signature": "s"}]})


def asked(text):
    return ("user_message", {"role": "user", "content": [{"type": "text", "text": text}]})


class FilesTest(unittest.TestCase):
    """A session of two turns, in a gatherer database of the test's own."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.saved, dashboard_home.HOME = dashboard_home.HOME, self.tmp.name
        self.addCleanup(setattr, dashboard_home, "HOME", self.saved)
        os.makedirs(os.path.join(self.tmp.name, "gatherers", "g"))
        self.db = os.path.join(self.tmp.name, "gatherers", "g", "context.db")
        conn = sqlite3.connect(self.db)
        conn.executescript("""CREATE TABLE event_types (event_type_id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL);
            CREATE TABLE events (row_id INTEGER PRIMARY KEY, inserted_at TEXT NOT NULL, event_id TEXT, event_type_id INTEGER NOT NULL,
              payload_json TEXT NOT NULL, tokens INTEGER NOT NULL, text TEXT, counted INTEGER, p_channel);""")
        conn.close()
        self.add(
            asked("look at a.py"),
            thought("Read it first."), thought(""),
            call("r1", "Read", {"file_path": "/w/a.py"}), result("r1", "1\tdef f():\n2\t    return 1\n3\t\n4\tdef g():\n5\t    return 2"),
            said("It returns 1."),
            asked("change g"),
            call("b1", "Bash", {"command": "sed -n 4,5p a.py", "description": "Show g"}), result("b1", "def g():\n    return 2"),
            call("e1", "Edit", {"file_path": "/w/a.py", "old_string": "    return 2", "new_string": "    return 3\n    # three"}),
            result("e1", "The file /w/a.py has been updated successfully."),
            call("e2", "Edit", {"file_path": "/w/b.py", "old_string": "x = 1", "new_string": "x = 2"}), result("e2", "ok"),
            call("w1", "Write", {"file_path": "/w/new.py", "content": "print(1)\n"}), result("w1", "created"),
            call("t1", "Bash", {"command": "python3 -m unittest", "description": "Run the tests"}), result("t1", "FAILED", True),
            call("p1", "Bash", {"command": "python3 - <<'EOF'\np = 'a.py'\ns = open(p).read().replace('    # three', '    # 3')\n"
                                           "open(p, 'w').write(s)\nEOF", "description": "Shorten the comment"}), result("p1", ""),
            call("c1", "Bash", {"command": "cat > notes.md <<'EOF'\n# notes\nEOF", "description": "Write notes"}), result("c1", ""),
            call("i1", "Read", {"file_path": "/w/shot.png"}),
            ("tool_output", {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "i1", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "iVBORw0KGgo="}}]}]}),
        )

    def add(self, *events):
        """Events of channel c1, after those there."""
        conn = sqlite3.connect(self.db)
        for typ, payload in events:
            got = conn.execute("SELECT event_type_id FROM event_types WHERE name = ?", (typ,)).fetchone()
            tid = got[0] if got else conn.execute("INSERT INTO event_types (name, created_at) VALUES (?, '')", (typ,)).lastrowid
            conn.execute("INSERT INTO events (inserted_at, event_type_id, payload_json, tokens, p_channel) VALUES "
                         "('2026-10-24 08:00:00', ?, ?, 1, 'c1')", (tid, json.dumps(payload)))
        conn.commit()
        conn.close()

    def test_the_turns_and_the_latest_by_default(self):
        got = files.files("g", "c1", cwd="/w")
        self.assertEqual([t["text"] for t in got["turns"]], ["look at a.py", "change g"])
        self.assertEqual(got["turn"], 1)
        self.assertEqual([t["replies"] for t in got["turns"]],              # what the agent thought and said back
                         [[{"kind": "thinking", "texts": ["Read it first."]}, {"kind": "text", "text": "It returns 1."}], []])
        self.assertEqual([t["now"] for t in got["turns"]], [None, None])    # done: nothing under way
        self.assertEqual([f["path"] for f in got["files"]], ["/w/a.py", "/w/b.py", "/w/new.py", "/w/notes.md", "/w/shot.png"])
        self.assertIn("error", files.files("nope", "c1"))

    def test_what_the_agent_is_doing_while_its_turn_runs(self):
        self.add(asked("and now?"), thought(""))
        self.assertEqual(files.files("g", "c1")["turns"][-1]["replies"], [{"kind": "thinking", "texts": []}])   # encrypted
        self.assertEqual(files.files("g", "c1")["turns"][-1]["now"], {"kind": "thinking"})
        self.add(call("b9", "Bash", {"command": "make", "description": "Build it"}))
        self.assertEqual(files.files("g", "c1")["turns"][-1]["now"], {"kind": "call", "id": "b9", "text": "Build it"})
        self.add(result("b9", "ok"))
        self.assertIsNone(files.files("g", "c1")["turns"][-1]["now"])        # its result in: the model's turn again

    def test_a_read_shows_its_lines_at_their_numbers(self):
        a = files.files("g", "c1", 0)["files"][0]
        self.assertEqual(a["kinds"], ["read"])
        self.assertEqual(a["sources"][0]["blocks"][0]["start"], 1)
        self.assertEqual(a["sources"][0]["blocks"][0]["lines"][:2], ["def f():", "    return 1"])

    def test_each_call_shows_what_it_did_to_the_file(self):
        got = files.files("g", "c1", 1, cwd="/w")
        a = got["files"][0]
        self.assertEqual(a["kinds"], ["edit", "read"])
        read, edit, script = a["sources"]
        self.assertEqual(read["via"], "Show g")                     # a command's own description names it
        self.assertEqual(read["blocks"], [{"t": "lines", "start": 4, "lines": ["def g():", "    return 2"], "cut": 0}])
        self.assertEqual(edit["blocks"], [{"t": "diff", "at": 5, "old": ["    return 2"], "new": ["    return 3", "    # three"],
                                           "above": [[3, ""], [4, "def g():"]], "below": []}])
        self.assertEqual([(b["at"], b["old"], b["new"]) for b in script["blocks"]],   # placed after the edit before it
                         [(6, ["    # three"], ["    # 3"])])
        b = got["files"][1]                                         # never seen: where in it is not known
        self.assertEqual([(x["at"], x["new"]) for x in b["sources"][0]["blocks"]], [(None, ["x = 2"])])
        new = got["files"][2]
        self.assertTrue(new["created"])
        self.assertEqual(new["sources"][0]["blocks"][0]["lines"], ["print(1)", ""])

    def test_a_shell_command_s_changes_show_on_its_files_not_as_commands(self):
        got = files.files("g", "c1", 1, cwd="/w")
        a = got["files"][0]
        self.assertEqual([s["via"] for s in a["sources"]], ["Show g", "Edit", "Shorten the comment"])
        notes = got["files"][3]
        self.assertEqual((notes["kinds"], notes["created"], notes["sources"][0]["blocks"][0]["lines"]), (["write"], True, ["# notes"]))

    def test_an_image_read_is_shown_from_where_it_is_stored(self):
        shot = files.files("g", "c1", 1, cwd="/w")["files"][4]
        self.assertEqual(shot["kinds"], ["read"])                       # an image is read like any file
        b = shot["sources"][0]["blocks"][0]
        self.assertEqual((b["t"], b["id"]), ("image", "i1"))
        self.assertEqual(files.image("g", b["row_id"], "i1"), ("image/png", b"\x89PNG\r\n\x1a\n"))
        self.assertIsNone(files.image("g", b["row_id"], "other"))       # another call's: not this one

    def test_every_call_is_listed_in_order_with_its_files(self):
        cmds = files.files("g", "c1", 1, cwd="/w")["commands"]
        self.assertEqual([(c["text"], c["error"], c["files"]) for c in cmds], [
            ("Show g", False, ["/w/a.py"]), ("Edit a.py", False, ["/w/a.py"]), ("Edit b.py", False, ["/w/b.py"]),
            ("Write new.py", False, ["/w/new.py"]), ("Run the tests", True, []),
            ("Shorten the comment", False, ["/w/a.py"]), ("Write notes", False, ["/w/notes.md"]),
            ("Read shot.png", False, ["/w/shot.png"])])


if __name__ == "__main__":
    unittest.main()
