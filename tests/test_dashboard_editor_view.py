"""The Editor's files that are not edited but shown (livedocs.about): what each is -- an image, a PDF, a sound, a video, text,
or none of these -- by its name and its first bytes; its bytes served to the page (/api/edit/raw/<path>), sandboxed, in
ranges; and the system's file manager showing it where it is (chooser.reveal)."""

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app_kit.fileedit import chooser  # noqa: E402
from ag_dashboard import livedocs  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR" + bytes(range(200))


class AboutTest(unittest.TestCase):
    """What a file is opened as."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.realpath(self.tmp.name)

    def file(self, name: str, body: bytes) -> str:
        p = os.path.join(self.root, name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as fh:
            fh.write(body)
        return p

    def about(self, name: str, body: bytes) -> dict:
        return livedocs.about(self.file(name, body), self.root)

    def test_by_its_name(self):
        for name, kind, kind_type in (("a.png", "image", "image/png"), ("a.JPG", "image", "image/jpeg"),
                                      ("a.pdf", "pdf", "application/pdf"), ("a.wav", "audio", "audio/wav"),
                                      ("a.mov", "video", "video/quicktime"), ("a.webm", "video", "video/webm")):
            got = self.about(name, b"\0\1\2\3binary")
            self.assertEqual((got["kind"], got["type"], got["text"]), (kind, kind_type, False), name)

    def test_by_its_first_bytes_without_a_name_that_says(self):
        self.assertEqual(self.about("figure", PNG)["kind"], "image")
        got = self.about("build/out", b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
        self.assertEqual((got["kind"], got["type"]), ("pdf", "application/pdf"))
        self.assertEqual(self.about("pic.dat", b"RIFF\0\0\0\0WEBPVP8 ")["type"], "image/webp")

    def test_text_is_text_and_served_as_plain_text(self):
        for name in ("a.html", "a.py", "a.ts", "README", "empty.txt"):        # .ts: TypeScript, not a video
            got = self.about(name, b"" if name == "empty.txt" else b"<script>alert(1)</script>\n")
            self.assertEqual((got["kind"], got["type"], got["text"]), ("text", "text/plain; charset=utf-8", True), name)

    def test_an_svg_is_an_image_and_its_text_can_be_edited(self):
        got = self.about("d.svg", b'<svg xmlns="http://www.w3.org/2000/svg"/>')
        self.assertEqual((got["kind"], got["type"], got["text"]), ("image", "image/svg+xml", True))

    def test_named_as_an_image_but_text_is_text(self):
        got = self.about("plot.png", b"version https://git-lfs.github.com/spec/v1\noid sha256:4d7a\nsize 12345\n")
        self.assertEqual((got["kind"], got["text"]), ("text", True))           # a Git LFS pointer

    def test_anything_else_is_a_file(self):
        self.assertEqual(self.about("a.zip", b"PK\3\4\0\0rest")["kind"], "file")
        self.assertEqual(self.about("latin.txt", "café\n".encode("latin-1"))["kind"], "file")
        got = self.about("bytes.bin", bytes(range(256)))
        self.assertEqual((got["kind"], got["type"], got["text"]), ("file", "application/octet-stream", False))

    def test_text_too_large_to_edit(self):
        with mock.patch.object(livedocs, "MAX_BYTES", 100):
            got = self.about("big.log", b"a line\n" * 50)
        self.assertEqual((got["kind"], got["text"], got["max"], got["size"]), ("text", False, 100, 350))

    def test_a_character_cut_at_the_end_of_what_is_looked_at_is_still_text(self):
        body = b"a" * (livedocs.SNIFF - 1) + "é".encode() + b"more\n"
        self.assertEqual(self.about("cut.txt", body)["kind"], "text")

    def test_its_size_time_and_real_path(self):
        p = self.file("real.png", PNG)
        link = os.path.join(self.root, "link.png")
        os.symlink(p, link)
        got = livedocs.about(link, self.root)
        self.assertEqual((got["path"], got["real"], got["name"], got["size"]), (link, p, "link.png", len(PNG)))
        self.assertAlmostEqual(got["mtime"], os.stat(p).st_mtime)

    def test_what_is_refused(self):
        with self.assertRaisesRegex(livedocs.DocError, "does not exist"):
            livedocs.about(os.path.join(self.root, "none.png"), self.root)
        with self.assertRaisesRegex(livedocs.DocError, "is not a file"):
            livedocs.about(self.root, self.root)
        with self.assertRaisesRegex(livedocs.DocError, "is not under"):
            livedocs.about("/etc/hosts", self.root)


class RevealTest(unittest.TestCase):
    """The file manager, its command faked: Finder's window with the file picked out; a Linux one at its folder."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(os.path.realpath(self.tmp.name), "a.zip")
        with open(self.path, "wb") as fh:
            fh.write(b"PK")

    def test_macos_selects_it_in_finder(self):
        with mock.patch.object(chooser.sys, "platform", "darwin"), mock.patch.object(chooser.shutil, "which", return_value="/usr/bin/open"), \
                mock.patch.object(chooser.subprocess, "Popen") as popen:
            self.assertEqual(chooser.shower(), "Finder")
            chooser.reveal(self.path)
        self.assertEqual(popen.call_args.args[0], ["open", "-R", self.path])     # shown, never opened in an app

    def test_linux_opens_its_folder_with_a_display(self):
        with mock.patch.object(chooser.sys, "platform", "linux"), mock.patch.object(chooser.shutil, "which", return_value="/usr/bin/xdg-open"), \
                mock.patch.dict(os.environ, {"DISPLAY": ":0"}), mock.patch.object(chooser.subprocess, "Popen") as popen:
            self.assertEqual(chooser.shower(), "the file manager")
            chooser.reveal(self.path)
        self.assertEqual(popen.call_args.args[0], ["xdg-open", os.path.dirname(self.path)])

    def test_none_without_a_display_or_a_file(self):
        env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY")}
        with mock.patch.object(chooser.sys, "platform", "linux"), mock.patch.dict(os.environ, env, clear=True):
            self.assertIsNone(chooser.shower())
            with self.assertRaises(chooser.ChooseError):
                chooser.reveal(self.path)
        with mock.patch.object(chooser, "shower", return_value="Finder"), self.assertRaisesRegex(chooser.ChooseError, "does not exist"):
            chooser.reveal(self.path + ".gone")


class ServerTest(unittest.TestCase):
    """Through the dashboard's server, the Editor app's routes on its own origin: /api/edit/about, /api/edit/raw/<path>,
    /api/edit/reveal. `self.ch`: the chooser the host's Editor runs (its own import of it)."""

    def setUp(self):
        from ag_dashboard import home as dashboard_home, server
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.saved, dashboard_home.HOME = dashboard_home.HOME, os.path.join(self.tmp.name, "home")
        self.addCleanup(setattr, dashboard_home, "HOME", self.saved)
        self.root = os.path.join(os.path.realpath(self.tmp.name), "work")
        os.makedirs(os.path.join(self.root, "figs"))
        self.png = os.path.join(self.root, "figs", "a plot #1.png")          # a space and a '#': quoted in its URL
        with open(self.png, "wb") as fh:
            fh.write(PNG)
        self.svg = os.path.join(self.root, "d.svg")
        with open(self.svg, "w") as fh:
            fh.write('<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>')
        self.httpd = server.serve("127.0.0.1", 0, live_updates=False)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        self.app = f"editor.localhost:{self.httpd.server_port}"
        self.httpd.app_host.backend("editor")
        self.ch = sys.modules["app_kit.fileedit.chooser"]

    def get(self, path: str):
        return urllib.request.urlopen(urllib.request.Request(self.url + path, headers={"Host": self.app}), timeout=10)

    def raw(self, path: str, query: str = "", headers=None):
        url = f"{self.url}/api/edit/raw{urllib.parse.quote(path)}?root={urllib.parse.quote(self.root)}{query}"
        return urllib.request.urlopen(urllib.request.Request(url, headers={"Host": self.app, **(headers or {})}), timeout=10)

    def test_about_says_what_it_is_and_where_it_can_be_shown(self):
        q = urllib.parse.urlencode({"path": self.png, "root": self.root})
        with mock.patch.object(self.ch, "shower", return_value="Finder"):
            got = json.load(self.get(f"/api/edit/about?{q}"))
        self.assertEqual((got["kind"], got["type"], got["size"], got["reveal"]), ("image", "image/png", len(PNG), "Finder"))
        with self.assertRaises(urllib.error.HTTPError) as no:
            self.get(f"/api/edit/about?{urllib.parse.urlencode({'path': '/etc/hosts', 'root': self.root})}")
        self.assertEqual((no.exception.code, "is not under" in json.load(no.exception)["error"]), (400, True))

    def test_its_bytes_as_shown_saved_and_in_ranges(self):
        with self.raw(self.png) as resp:
            self.assertEqual(resp.read(), PNG)
            self.assertEqual(resp.headers["content-type"], "image/png")
            self.assertEqual(resp.headers["x-content-type-options"], "nosniff")
            self.assertEqual(resp.headers["content-security-policy"].split(";")[0], "sandbox")   # and the host's framing
            self.assertTrue(resp.headers["content-disposition"].startswith("inline"))
        with self.raw(self.png, "&download=1") as resp:
            self.assertTrue(resp.headers["content-disposition"].startswith("attachment"))
        with self.raw(self.png, headers={"Range": "bytes=0-7"}) as resp:          # a video's, as it plays
            self.assertEqual((resp.status, resp.read()), (206, PNG[:8]))

    def test_an_svg_or_a_page_runs_nothing_from_here(self):
        with self.raw(self.svg) as resp:
            self.assertEqual(resp.headers["content-type"], "image/svg+xml")
            self.assertEqual(resp.headers["content-security-policy"].split(";")[0], "sandbox")
        page = os.path.join(self.root, "p.html")
        with open(page, "w") as fh:
            fh.write("<script>fetch('/api/home')</script>")
        with self.raw(page) as resp:                                             # text, not a page
            self.assertEqual(resp.headers["content-type"], "text/plain; charset=utf-8")

    def test_what_is_refused(self):
        with self.assertRaises(urllib.error.HTTPError) as no:
            self.raw("/etc/hosts")
        self.assertEqual(no.exception.code, 400)
        with self.assertRaises(urllib.error.HTTPError) as no:
            self.raw(self.root)
        self.assertEqual(no.exception.code, 400)
        with self.assertRaises(urllib.error.HTTPError) as no:                    # a name rebound to this host: not
            self.raw(self.png, headers={"Host": "evil.example"})                # the app's origin, nor a dashboard route
        self.assertIn(no.exception.code, (403, 404))

    def post(self, path: str, body: dict, own: bool = True):
        headers = {"Content-Type": "application/json", "Host": self.app, **({"Origin": f"http://{self.app}"} if own else {})}
        req = urllib.request.Request(self.url + path, data=json.dumps(body).encode(), headers=headers)
        return json.load(urllib.request.urlopen(req, timeout=10))

    def test_shown_in_the_file_manager(self):
        with mock.patch.object(self.ch, "reveal") as reveal:
            self.assertEqual(self.post("/api/edit/reveal", {"path": self.png, "root": self.root}), {})
            reveal.assert_called_once_with(self.png)
            with self.assertRaises(urllib.error.HTTPError) as no:
                self.post("/api/edit/reveal", {"path": "/etc/hosts", "root": self.root})
            self.assertEqual(no.exception.code, 400)
            with self.assertRaises(urllib.error.HTTPError) as no:               # not its panel's own: another origin
                self.post("/api/edit/reveal", {"path": self.png, "root": self.root}, own=False)
            self.assertEqual(no.exception.code, 403)
            self.assertEqual(reveal.call_count, 1)


if __name__ == "__main__":
    unittest.main()
