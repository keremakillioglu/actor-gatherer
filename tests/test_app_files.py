"""The Files app (ag_apps/files/) and the LaTeX editor (ag_apps/latex/), the two apps the Editor was split into: what
each is (its tools, the files it takes), and the Editor's instances taken over by them -- one on a paper's folder by
the LaTeX editor, any other by the Files app (a manifest's `replaces`, App.takes_over, the host's `_taken_over`) -- with
their agents still attached and their actors' roles moved with them (app_agents.adopt_all). Their file editing is
app_kit.fileedit's, tested through the LaTeX editor (test_app_latex.py) and the Files app (test_dashboard_editor*.py)."""
import http.client
import json
import os
import sys
import threading
import time
import unittest
import unittest.mock
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app_kit  # noqa: E402
from ag_dashboard import access, app_agents, app_host, server, task_links, tasks, tool_gateway  # noqa: E402
from app_kit import Instance  # noqa: E402
from test_dashboard import HomeBase  # noqa: E402
from test_dashboard_app_host import insert_here  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ManifestTest(unittest.TestCase):
    def test_files_shows_files_for_any_agent_the_latex_editor_edits_live_its_sources_first(self):
        files, latex = (app_kit.load(os.path.join(ROOT, "ag_apps", n)) for n in ("files", "latex"))
        self.assertEqual([t.name for t in files.tools], ["open"])            # its agents edit with their own tools
        self.assertEqual([t.name for t in latex.tools], ["read", "edit", "write", "open", "preview_show",
                                                         "preview_set", "preview_run", "preview_stop", "preview_clear"])
        self.assertEqual([(h.intent, h.types) for h in files.handles], [("open-file", ())])
        self.assertEqual([(h.intent, h.types) for h in latex.handles], [("open-file", ("text/x-tex", "text/x-bibtex"))])
        self.assertEqual((files.replaces, latex.replaces), (("editor",), ("editor",)))
        self.assertEqual((files.access, files.agent.offered, files.capabilities.edit_guard), ("group", False, False))
        self.assertEqual((latex.access, latex.agent.offered, latex.capabilities.edit_guard), ("task", True, True))
        self.assertEqual((files.on_task, latex.on_task), ("folder", "join"))   # "+": Files at the actor's directory
        for m in (files, latex):
            self.assertTrue(m.capabilities.docs and m.capabilities.message_actors)
            self.assertEqual(m.instances, "many")
            self.assertNotIn("editor_", m.instructions)
        self.assertNotIn("preview", files.instructions)

    def test_both_open_files_by_link_a_path_written_with_no_app_in_files(self):
        files, latex = (app_kit.load(os.path.join(ROOT, "ag_apps", n)) for n in ("files", "latex"))
        self.assertEqual([(k.form, k.paths) for k in files.links], [(app_kit.links.FILE_FORM, True)])
        self.assertEqual([(k.form, k.paths) for k in latex.links], [(app_kit.links.FILE_FORM, False)])
        self.assertEqual(files.to_dict()["links"][0]["paths"], True)       # as the page reads it
        self.assertIn("ag://files/file/", files.told())                   # every agent of the group told how
        base = {"name": "a", "label": "A", "version": "1", "panel": {"entry": "index.html"}}
        with self.assertRaises(app_kit.ManifestError):                    # `paths`: for the file form only
            app_kit.parse({**base, "links": [{"form": "page/<id>", "paths": True}]})

    def test_replaces_names_another_app(self):
        base = {"name": "a", "label": "A", "version": "1", "backend": {"python": "backend:A"}}
        self.assertEqual(app_kit.parse({**base, "replaces": ["b"]}).replaces, ("b",))
        for bad in (["a"], ["Not a name"], "b"):
            with self.assertRaises(app_kit.ManifestError):
                app_kit.parse({**base, "replaces": bad})
        with self.assertRaises(app_kit.ManifestError):                  # its backend says which: it needs one
            app_kit.parse({"name": "a", "label": "A", "version": "1", "replaces": ["b"]})


class Sessions:
    """The sessions table, as adopt_all reads and writes it."""

    def __init__(self, rows):
        self.rows = rows

    def list(self):
        return [dict(r) for r in self.rows]

    def set_role(self, session_id, role):
        next(r for r in self.rows if r["session_id"] == session_id)["role"] = role


class TakenOverTest(HomeBase):
    """Editors open before the split: kept by the host's records as instances of "editor", an app no longer found."""

    def setUp(self):
        super().setUp()
        root = os.path.realpath(self.tmp.name)
        self.paper, self.code = os.path.join(root, "paper"), os.path.join(root, "code")
        os.makedirs(os.path.join(self.paper, "sections"))
        os.makedirs(self.code)
        for path in ("paper/main.tex", "paper/sections/one.tex", "code/notes.md", "code/app.py"):
            with open(os.path.join(root, path), "w") as fh:
                fh.write("x\n")
        old = self.new_host()
        self.editors = []
        for folder, channel in ((self.paper, "c1"), (self.code, "c2")):
            i = Instance(id=os.urandom(8).hex(), app="editor", gatherer="g", folder=folder, title="Editor")
            old._record(i, "app_opened", {"instance": i.to_dict(), "by": "user"})
            old._record(i, "app_attached", {}, channel)
            old._record(i, "app_named", {"name": f"mine {channel}"})
            self.editors.append(i)
        old.flush()

    def new_host(self):
        h = app_host.AppHost(0, write=insert_here)
        self.addCleanup(h.close)
        self.hosts.append(h)                                # closed before the home goes (HomeBase's tearDown)
        return h

    def test_a_paper_s_editor_is_the_latex_editor_s_any_other_the_files_app_s_once(self):
        h = self.new_host()
        got = h.listed("g")
        apps = {i["id"]: (i["app"], i["name"]) for i in got["instances"]}
        paper, code = self.editors
        self.assertEqual(apps, {paper.id: ("latex", "mine c1"), code.id: ("files", "mine c2")})   # its name kept
        self.assertEqual(got["attached"], {paper.id: ["c1"], code.id: ["c2"]})                 # its agent still on it
        self.assertEqual(h.instance("g", paper.id).title, "paper")                              # opened again by it
        h.flush()
        again = self.new_host()                                       # kept as theirs: not taken over a second time
        self.assertEqual({i["id"]: i["app"] for i in again.listed("g")["instances"]},
                         {paper.id: "latex", code.id: "files"})
        again.flush()
        conn = self.m._conn("g")
        moved = conn.execute("SELECT count(*) FROM events e JOIN event_types t USING (event_type_id) "
                             "WHERE t.name = 'app_opened' AND e.payload_json LIKE '%\"by\": \"replaced\"%'").fetchone()[0]
        self.assertEqual(moved, 2)

    def test_its_actor_s_role_names_the_app_that_took_it(self):
        h = self.new_host()
        paper, code = self.editors
        rows = [{"session_id": "c1", "gatherer": "g", "cwd": self.paper, "role": app_agents.role("editor", paper.id)},
                {"session_id": "c2", "gatherer": "g", "cwd": self.code, "role": app_agents.role("editor", code.id)},
                {"session_id": "c3", "gatherer": "g", "cwd": self.code, "role": None}]
        app_agents.adopt_all(Sessions(rows), h)
        self.assertEqual([app_agents.role_of(r) for r in rows], [("latex", paper.id), ("files", code.id), None])
        self.assertEqual(h.listed("g")["attached"][paper.id], ["c1"])

    def test_taken_over_by_the_files_app_it_leaves_its_task_by_the_latex_editor_it_stays(self):
        """A group's app is in no task (task_links.py's `on_load`): one an Editor was, taken over by Files, too."""
        paper, code = self.editors
        for i, channel in zip(self.editors, ("c1", "c2")):                 # each in a task with its actor, as before
            tasks.add("g", channel, [tasks.app_item(i.id)])
        h = self.new_host()
        h.loaded_then = task_links.on_load                                # as the server has it
        with unittest.mock.patch.object(tool_gateway, "HOST", h), \
                unittest.mock.patch.object(access, "STARTED", lambda g, c: True):
            got = h.listed("g")
            taskable = [task_links.taskable("g", tasks.app_item(i.id)) for i in self.editors]
        self.assertEqual({i["id"]: i["app"] for i in got["instances"]}, {paper.id: "latex", code.id: "files"})
        self.assertEqual(tasks.task_of("g", tasks.app_item(paper.id)), tasks.task_of("g", "c1"))   # LaTeX: "task", kept
        self.assertIsNotNone(tasks.task_of("g", "c1"))
        self.assertIsNone(tasks.task_of("g", tasks.app_item(code.id)))     # Files: "group", in no task
        self.assertIsNone(tasks.task_of("g", "c2"))                        # (its actor alone: the task gone with it)
        self.assertEqual(got["attached"].get(paper.id), ["c1"])
        self.assertEqual(h.listed("g")["attached"].get(code.id, []), [])  # left its task: detached, as any would be
        self.assertEqual(taskable, [True, False])                         # nor put in one again

    def test_an_editor_on_a_folder_gone_waits_as_it_did(self):
        os.rename(self.code, self.code + ".gone")                    # the Files app can't open it: no app takes it
        h = self.new_host()
        self.assertEqual([i["app"] for i in h.listed("g")["instances"]], ["latex"])


class PlainTest(HomeBase):
    """A file open plain in the Files app, through the dashboard's server: read with its version (edit/text), saved
    whole (edit/put) -- refused, 409, over a change made on disk since, unless forced -- and the listing's writers in the
    window the panel asks (since)."""

    def setUp(self):
        super().setUp()
        self.root = os.path.realpath(self.tmp.name)
        self.file = os.path.join(self.root, "notes.md")
        with open(self.file, "w") as fh:
            fh.write("one\ntwo\n")
        self.httpd = server.serve("127.0.0.1", 0, live_updates=False)
        self.httpd.app_host._write_fn = insert_here
        self.hosts.append(self.httpd.app_host)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.serving(self.httpd)
        self.port = self.httpd.server_port
        self.inst = self.httpd.app_host.open("files", "g", self.root)
        self.q = f"gatherer=g&instance={self.inst.id}"

    def at(self, path, method="GET", body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        headers = {"Host": f"files.localhost:{self.port}"}
        if body is not None:
            headers["Origin"] = f"http://files.localhost:{self.port}"
        conn.request(method, f"{path}{'&' if '?' in path else '?'}{self.q}", json.dumps(body) if body is not None else None,
                     headers)
        r = conn.getresponse()
        got = json.loads(r.read() or b"{}")
        conn.close()
        return r.status, got

    def text(self, have=""):
        return self.at(f"/api/edit/text?path={urllib.parse.quote(self.file)}&root=/&have={have}")[1]

    def test_read_with_its_version_saved_whole_and_not_over_a_change_made_since(self):
        got = self.text()
        self.assertEqual(got["text"], "one\ntwo\n")
        self.assertEqual(self.text(got["version"]), {"version": got["version"], "same": True})   # unchanged: no text
        status, put = self.at("/api/edit/put", "POST", {"path": self.file, "root": "/", "text": "one\n2\n",
                                                        "base": got["version"]})
        self.assertEqual(status, 200)
        with open(self.file) as fh:
            self.assertEqual(fh.read(), "one\n2\n")
        time.sleep(0.01)
        with open(self.file, "w") as fh:                         # an actor's change, on disk
            fh.write("one\n2\nthree\n")
        status, refused = self.at("/api/edit/put", "POST", {"path": self.file, "root": "/", "text": "mine\n",
                                                            "base": put["version"]})
        self.assertEqual(status, 409)
        self.assertIn("changed on disk", refused["error"])
        with open(self.file) as fh:
            self.assertEqual(fh.read(), "one\n2\nthree\n")   # kept
        self.assertEqual(self.text(put["version"])["text"], "one\n2\nthree\n")
        status, _ = self.at("/api/edit/put", "POST", {"path": self.file, "root": "/", "text": "mine\n",
                                                      "base": put["version"], "force": True})   # the reader's Keep mine
        self.assertEqual(status, 200)
        with open(self.file) as fh:
            self.assertEqual(fh.read(), "mine\n")
        os.remove(self.file)
        self.assertEqual(self.text(), {"version": None, "missing": True})
        status, _ = self.at("/api/edit/put", "POST", {"path": self.file, "root": "/", "text": "back\n", "base": None})
        self.assertEqual(status, 200)                            # Save restores a file deleted on disk

    def test_the_listing_s_writers_are_those_of_the_window_asked(self):
        from ag_dashboard import livedocs
        now = time.time()
        found = {"notes.md": [{"gatherer": "g", "channel": "c1", "at": now - 1200, "how": "modified"}]}   # by its path in it
        asked = []

        def writers(dirs, since):
            asked.append(since)
            return {p: [w for w in ws if w["at"] >= since] for p, ws in found.items()}
        with unittest.mock.patch.object(livedocs, "writers", writers):
            ten = self.at(f"/api/edit/list?dir={urllib.parse.quote(self.root)}&root=/&since={int(now - 600)}")[1]
            half = self.at(f"/api/edit/list?dir={urllib.parse.quote(self.root)}&root=/")[1]
        names = lambda got: [e["name"] for e in got["entries"] if e.get("writers")]   # noqa: E731
        self.assertEqual((names(ten), names(half)), ([], ["notes.md"]))   # 20 min ago: in the half hour, not the 10 min
        self.assertEqual(int(asked[0]), int(now - 600))


if __name__ == "__main__":
    unittest.main()
