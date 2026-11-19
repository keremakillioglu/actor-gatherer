"""The Editor's ways to open what the tree does not show: the system's Open dialog (the Editor app's chooser.py), opened
by the dashboard on its own machine, and Go to file's list of a folder's files (livedocs.file_list) -- git's in a git
project, else a walk."""

import json
import os
import shutil
import subprocess
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

from app_kit.fileedit import chooser  # noqa: E402
from ag_dashboard import livedocs  # noqa: E402


def done(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


class ChooserTest(unittest.TestCase):
    """The dialog, its command faked: what it is asked, and what its answer becomes."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.start = os.path.realpath(self.tmp.name)

    def run_with(self, which, answer, what="file", start=None):
        with mock.patch.object(chooser, "tool", return_value=which), \
                mock.patch.object(chooser.subprocess, "run", return_value=answer) as run:
            got = chooser.choose(what, self.start if start is None else start)
        return got, run.call_args

    def test_macos_s_dialog_is_asked_through_applescript_at_the_folder(self):
        got, call = self.run_with("osascript", done("/Users/x/notes/plan.md\n"))
        self.assertEqual(got, "/Users/x/notes/plan.md")
        self.assertEqual(call.args[0], ["osascript", "-", "file", self.start])
        self.assertEqual(call.kwargs["input"], chooser.APPLESCRIPT)
        got, call = self.run_with("osascript", done("/Users/x/notes/\n"), what="folder")
        self.assertEqual(got, "/Users/x/notes")                       # a folder's path, its "/" left off
        self.assertEqual(call.args[0][2], "folder")

    def test_cancelled_is_none(self):
        self.assertIsNone(self.run_with("osascript", done(""))[0])
        self.assertIsNone(self.run_with("zenity", done("", 1))[0])
        self.assertIsNone(self.run_with("kdialog", done("", 1))[0])
        self.assertIsNone(self.run_with("osascript", done("", -15))[0])          # its dialog ended by a signal

    def test_linux_s_dialogs(self):
        got, call = self.run_with("zenity", done("/home/x/a.py\n"))
        self.assertEqual(got, "/home/x/a.py")
        self.assertEqual(call.args[0][:2], ["zenity", "--file-selection"])
        self.assertIn(f"--filename={self.start}/", call.args[0])
        self.assertNotIn("--directory", call.args[0])
        self.assertIn("--directory", self.run_with("zenity", done("/home/x\n"), what="folder")[1].args[0])
        _, call = self.run_with("kdialog", done("/home/x\n"), what="folder")
        self.assertEqual(call.args[0][-2:], ["--getexistingdirectory", self.start])

    def test_a_folder_not_there_opens_it_at_home(self):
        _, call = self.run_with("osascript", done(""), start=os.path.join(self.start, "gone"))
        self.assertEqual(call.args[0][3], os.path.expanduser("~"))
        _, call = self.run_with("osascript", done(""), start="relative/path")
        self.assertEqual(call.args[0][3], os.path.expanduser("~"))

    def test_what_it_refuses(self):
        with self.assertRaisesRegex(chooser.ChooseError, "file.*folder"):
            chooser.choose("anything", self.start)
        with mock.patch.object(chooser, "tool", return_value=None):
            with self.assertRaisesRegex(chooser.ChooseError, "no file dialog"):
                chooser.choose("file", self.start)
        with self.assertRaisesRegex(chooser.ChooseError, "did not open: no window"):
            self.run_with("osascript", done("", 1, "no window (-1713)\n"))

    def test_one_dialog_at_a_time(self):
        started, release = threading.Event(), threading.Event()

        def slow(*a, **k):
            started.set()
            release.wait(5)
            return done("/a\n")
        with mock.patch.object(chooser, "tool", return_value="osascript"), mock.patch.object(chooser.subprocess, "run", side_effect=slow):
            got = []
            t = threading.Thread(target=lambda: got.append(chooser.choose("file", self.start)))
            t.start()
            self.assertTrue(started.wait(5))
            with self.assertRaises(chooser.Busy):
                chooser.choose("file", self.start)
            release.set()
            t.join(5)
            self.assertEqual(got, ["/a"])
            with mock.patch.object(chooser.subprocess, "run", return_value=done("/b\n")):
                self.assertEqual(chooser.choose("file", self.start), "/b")   # free again once answered

    def test_which_dialog_this_machine_has(self):
        chooser.tool.cache_clear()
        self.addCleanup(chooser.tool.cache_clear)
        with mock.patch.object(chooser.sys, "platform", "linux"), mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(chooser.tool())                         # no display: nowhere to show it
        chooser.tool.cache_clear()
        with mock.patch.object(chooser.sys, "platform", "linux"), mock.patch.dict(os.environ, {"DISPLAY": ":0"}, clear=True), \
                mock.patch.object(chooser.shutil, "which", side_effect=lambda t: "/usr/bin/kdialog" if t == "kdialog" else None):
            self.assertEqual(chooser.tool(), "kdialog")
            self.assertEqual(chooser.name(), "the file dialog")
        chooser.tool.cache_clear()
        with mock.patch.object(chooser.sys, "platform", "darwin"), mock.patch.object(chooser.shutil, "which", return_value="/usr/bin/osascript"):
            self.assertEqual(chooser.name(), "Finder")


class FileListTest(unittest.TestCase):
    """Go to file's list: the files under a folder, the nearest first, what listings leave out left out."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.join(os.path.realpath(self.tmp.name), "proj")
        for path in ("a.py", "src/b.py", "src/deep/c.py", "node_modules/pkg/index.js", ".git_not/x.txt",
                     "build/out.txt", "src/d.py.9" + livedocs.TEMP):
            os.makedirs(os.path.dirname(os.path.join(self.root, path)), exist_ok=True)
            with open(os.path.join(self.root, path), "w") as fh:
                fh.write("x")

    def test_a_walk_the_nearest_first(self):
        got = livedocs.file_list(self.root, self.root)
        self.assertFalse(got["git"] or got["more"])
        self.assertEqual(got["files"], ["a.py", ".git_not/x.txt", "build/out.txt", "src/b.py", "src/deep/c.py"])
        self.assertEqual(livedocs.file_list(os.path.join(self.root, "src"), self.root)["files"], ["b.py", "deep/c.py"])

    def test_a_walk_stops_at_its_most(self):
        with mock.patch.object(livedocs, "FILES_MAX", 2):
            got = livedocs.file_list(self.root, self.root)
        self.assertEqual(len(got["files"]), 2)
        self.assertTrue(got["more"])

    def test_a_link_to_a_folder_is_not_followed(self):
        os.symlink(self.root, os.path.join(self.root, "src", "loop"))
        self.assertNotIn("src/loop/a.py", livedocs.file_list(self.root, self.root)["files"])

    @unittest.skipIf(shutil.which("git") is None, "git is not installed")
    def test_in_a_git_project_git_s_list(self):
        git = lambda *a: subprocess.run(["git", "-C", self.root, *a], check=True, capture_output=True)   # noqa: E731
        git("init", "-q")
        with open(os.path.join(self.root, ".gitignore"), "w") as fh:
            fh.write("build/\n")
        git("add", "a.py", "src/b.py")
        os.remove(os.path.join(self.root, "src", "b.py"))              # deleted since it was added: not listed
        got = livedocs.file_list(self.root, self.root)
        self.assertTrue(got["git"])
        # tracked, and new ones git does not ignore; not build/ (ignored) nor node_modules (left out of listings)
        self.assertEqual(got["files"], [".gitignore", "a.py", ".git_not/x.txt", "src/deep/c.py"])
        self.assertEqual(livedocs.file_list(os.path.join(self.root, "src"), self.root)["files"], ["deep/c.py"])

    def test_what_it_refuses(self):
        with self.assertRaisesRegex(livedocs.DocError, "not a directory"):
            livedocs.file_list(os.path.join(self.root, "a.py"), self.root)
        with self.assertRaisesRegex(livedocs.DocError, "not under"):
            livedocs.file_list("/etc", self.root)


class RoutesTest(unittest.TestCase):
    """The panel's side, through the dashboard's server -- the Editor app's routes, on its own origin: the listing says
    which dialog there is, the dialog answers. `self.ch`: the chooser the host's Editor runs (its own import of it)."""

    def setUp(self):
        from ag_dashboard import home as dashboard_home, server
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.saved, dashboard_home.HOME = dashboard_home.HOME, os.path.join(self.tmp.name, "home")
        self.addCleanup(setattr, dashboard_home, "HOME", self.saved)
        self.root = os.path.join(os.path.realpath(self.tmp.name), "work")
        os.makedirs(os.path.join(self.root, "src"))
        with open(os.path.join(self.root, "src", "a.py"), "w") as fh:
            fh.write("x")
        self.httpd = server.serve("127.0.0.1", 0, live_updates=False)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        self.app = f"files.localhost:{self.httpd.server_port}"
        self.httpd.app_host.backend("files")
        self.ch = sys.modules["app_kit.fileedit.chooser"]

    def get(self, path, **q):
        req = urllib.request.Request(f"{self.url}{path}?{urllib.parse.urlencode(q)}", headers={"Host": self.app})
        return json.load(urllib.request.urlopen(req, timeout=10))

    def post(self, path, body):
        req = urllib.request.Request(self.url + path, data=json.dumps(body).encode(), headers={
            "Content-Type": "application/json", "Host": self.app, "Origin": f"http://{self.app}"})
        return json.load(urllib.request.urlopen(req, timeout=10))

    def test_the_listing_names_the_dialog(self):
        with mock.patch.object(self.ch, "name", return_value="Finder"):
            self.assertEqual(self.get("/api/edit/list", dir=self.root, root=self.root)["choose"], "Finder")
        with mock.patch.object(self.ch, "name", return_value=None):
            self.assertIsNone(self.get("/api/edit/list", dir=self.root, root=self.root)["choose"])
        with mock.patch.object(self.ch, "name", return_value="Finder"):    # a folder not listed: said with its error too
            with self.assertRaises(urllib.error.HTTPError) as no:
                self.get("/api/edit/list", dir=os.path.join(self.root, "src", "a.py"), root=self.root)
        self.assertEqual(no.exception.code, 400)
        self.assertEqual(json.load(no.exception), {"error": f"{os.path.join(self.root, 'src', 'a.py')} is not a directory", "choose": "Finder"})

    def test_the_dialog_s_answer(self):
        with mock.patch.object(self.ch, "choose", return_value="/picked/plan.md") as ch:
            self.assertEqual(self.post("/api/edit/choose", {"what": "file", "start": self.root}), {"path": "/picked/plan.md"})
        ch.assert_called_once_with("file", self.root)
        with mock.patch.object(self.ch, "choose", return_value=None):
            self.assertEqual(self.post("/api/edit/choose", {"what": "folder", "start": self.root}), {"path": None})
        for raised, code in [(self.ch.Busy("A dialog is open already"), 409), (self.ch.ChooseError("no file dialog"), 400)]:
            with mock.patch.object(self.ch, "choose", side_effect=raised):
                with self.assertRaises(urllib.error.HTTPError) as no:
                    self.post("/api/edit/choose", {"what": "file", "start": self.root})
                self.assertEqual(no.exception.code, code)

    def test_a_page_elsewhere_gets_no_dialog(self):
        from ag_dashboard.api import apps as routes
        with mock.patch.object(routes, "LOOPBACK", frozenset()), mock.patch.object(self.ch, "name", return_value="Finder"), \
                mock.patch.object(self.ch, "choose") as ch:
            self.assertIsNone(self.get("/api/edit/list", dir=self.root, root=self.root)["choose"])
            with self.assertRaises(urllib.error.HTTPError) as no:
                self.post("/api/edit/choose", {"what": "file", "start": self.root})
            self.assertEqual(no.exception.code, 400)
        ch.assert_not_called()

    def test_the_files_for_go_to_file(self):
        got = self.get("/api/edit/files", dir=self.root, root=self.root)
        self.assertEqual(got["files"], ["src/a.py"])
        with self.assertRaises(urllib.error.HTTPError) as no:
            self.get("/api/edit/files", dir="/etc", root=self.root)
        self.assertEqual(no.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
