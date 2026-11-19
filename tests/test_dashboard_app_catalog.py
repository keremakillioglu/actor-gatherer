"""The Apps page's server side (app_catalog.py, api/app_catalog.py): what is installed and what it costs agents, an
app installed from a folder and updated, uninstalled with its windows put aside and back when it is installed again,
and an app that comes with ag uninstalled through config.toml and installed again -- each found again by the host at
once, and so on, or off, in every group."""

import json
import os
import sys
import threading
import unittest
import unittest.mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ag_dashboard import app_requests, app_settings, server, tool_gateway  # noqa: E402
import app_kit  # noqa: E402
from test_dashboard_app_host import NOTES, ROOT, HostBase, insert_here, write_app  # noqa: E402

PAGER = (NOTES.replace('name = "notes"', 'name = "pager"').replace('label = "Notes"', 'label = "Pager"')
         .replace("notes.added", "pager.added").replace('instances = "per-folder"', 'instances = "many"'))
MARK = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="12"/></svg>'


class CatalogTest(HostBase):
    def setUp(self):
        super().setUp()
        env = unittest.mock.patch.dict(os.environ, {"PYTHONPATH": ROOT})
        env.start()
        self.addCleanup(env.stop)
        self.builtin = os.path.join(self.tmp.name, "no-apps")                  # HostBase's BUILTIN: ag's own apps here
        folder = write_app(self.builtin, "slate", NOTES.replace('name = "notes"', 'name = "slate"').replace(
            'label = "Notes"', 'label = "Slate"\nmark = "mark.svg"').replace("notes.added", "slate.added"))
        with open(os.path.join(folder, "mark.svg"), "w") as fh:
            fh.write(MARK)
        self.src = write_app(os.path.join(self.tmp.name, "src"), "pager", PAGER)
        self.httpd = server.serve("127.0.0.1", 0, live_updates=False)
        self.httpd.app_host._write_fn = insert_here
        self.hosts.append(self.httpd.app_host)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.serving(self.httpd)
        self.port = self.httpd.server_port
        self.h = self.httpd.app_host
        tool_gateway.HOST = self.h
        self.addCleanup(setattr, tool_gateway, "HOST", None)

    def api(self, method, path, body=None):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        headers = {"Host": f"127.0.0.1:{self.port}"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        conn.request(method, path, json.dumps(body) if body is not None else None, headers)
        r = conn.getresponse()
        raw = r.read()
        conn.close()
        return r.status, (json.loads(raw) if raw[:1] in (b"{", b"[") else raw)

    def installed(self):
        return {a["name"]: a for a in self.api("GET", "/api/apps/catalog")[1]["installed"]}

    def on(self):
        return [m.name for m in tool_gateway.on("g")]

    def test_each_app_installed_says_what_agents_get_what_it_costs_and_its_windows(self):
        i = self.h.open("notes", "g", self.folder)
        got = self.installed()
        self.assertEqual(set(got), {"notes", "slate"})
        notes = got["notes"]
        self.assertEqual((notes["origin"], notes["access"], notes["tools"]),
                         ("path", "group", ["notes_add", "notes_picked"]))
        self.assertGreater(notes["tokens"], 20)
        self.assertEqual(notes["open"], {"g": 1})
        self.assertIn("reading these events of the gatherer: user_message", notes["can"])
        self.assertEqual(got["slate"]["origin"], "builtin")
        self.assertEqual(self.api("GET", "/api/apps/catalog")[1]["available"], [])
        self.assertTrue(i.id)

    def test_an_app_with_an_agent_of_its_own_opens_with_it_until_the_reader_chooses_on_its_own(self):
        write_app(self.builtin, "scribe", NOTES.replace('name = "notes"', 'name = "scribe"').replace(
            'label = "Notes"', 'label = "Scribe"').replace("notes.added", "scribe.added") + '\n[agent]\noffered = true\n')
        listed = lambda: {a["name"]: a["opens_with_agent"] for a in self.api("GET", "/api/apps")[1]["apps"]}  # noqa: E731
        self.assertEqual(self.installed()["scribe"]["opens_with_agent"], True)       # yes, until chosen otherwise
        self.assertEqual(listed(), {"notes": False, "scribe": True, "slate": False})  # (no agent to have: never)
        self.assertEqual(self.api("POST", "/api/apps/settings", {"app": "scribe", "agent": False}), (200, {"agent": False}))
        self.assertEqual((self.installed()["scribe"]["opens_with_agent"], listed()["scribe"]), (False, False))
        with open(app_settings.path(), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), {"scribe": {"agent": False}})         # the dashboard's own file, kept
        self.api("POST", "/api/apps/settings", {"app": "scribe", "agent": True})
        self.assertEqual(listed()["scribe"], True)
        # refused: an app with no agent of its own, one not installed, and a choice that isn't one
        self.assertEqual(self.api("POST", "/api/apps/settings", {"app": "notes", "agent": True})[0], 400)
        self.assertEqual(self.api("POST", "/api/apps/settings", {"app": "nope", "agent": True})[0], 404)
        self.assertEqual(self.api("POST", "/api/apps/settings", {"app": "scribe", "agent": "no"})[0], 400)
        self.assertEqual(listed()["scribe"], True)

    def test_installed_from_a_folder_it_is_on_in_every_group_at_once_and_an_update_says_what_changes(self):
        status, st = self.api("POST", "/api/apps/stage", {"source": self.src})
        self.assertEqual(status, 200)
        self.assertEqual((st["name"], st["tools"], st["kind"]), ("pager", ["pager_add", "pager_picked"], "folder"))
        self.assertNotIn("pager", self.on())                                     # staged: not yet
        self.assertEqual(self.api("POST", "/api/apps/install", {"id": st["id"]}), (200, {"name": "pager"}))
        self.assertIn("pager", self.on())
        self.assertEqual(self.installed()["pager"]["origin"], "home")
        self.assertIn("pager", [a["name"] for a in self.api("GET", "/api/apps")[1]["apps"]])
        with open(os.path.join(self.src, "app.toml"), "a") as fh:                 # its next version: a new tool
            fh.write('\n[[tools]]\nname = "ring"\ndescription = "Ring."\n')
        st = self.api("POST", "/api/apps/stage", {"source": self.src})[1]
        self.assertEqual(st["changes"]["tools_added"], ["pager_ring"])
        status, got = self.api("POST", "/api/apps/install", {"id": st["id"]})
        self.assertEqual(status, 400)
        self.assertIn("update it instead", got["error"])
        self.assertEqual(self.api("POST", "/api/apps/install", {"id": st["id"], "update": True})[0], 200)
        self.assertIn("pager_ring", self.installed()["pager"]["tools"])

    def test_an_agent_s_install_and_uninstall_wait_for_the_user_s_answer_and_the_agent_is_told(self):
        app_requests.forget()
        self.addCleanup(app_requests.forget)
        self.httpd.sessions.list = lambda: [{"session_id": "c1", "gatherer": "g", "cwd": self.folder,
                                             "harness": "claude"}]
        told = []
        self.h.tell_agent = lambda g, c, text, record: told.append((g, c, text, record["state"]))
        st = self.api("POST", "/api/apps/stage", {"source": self.src})[1]
        status, got = self.api("POST", "/api/apps/install", {"id": st["id"], "actor": "c1"})
        self.assertEqual((status, got["waiting"]["state"], got["waiting"]["op"]), (200, "waiting", "install"))
        self.assertNotIn("pager", self.on())                                     # not until the user approves
        rid = got["waiting"]["id"]
        self.assertEqual([r["id"] for r in self.api("GET", "/api/apps/requests")[1]["requests"]], [rid])
        self.assertEqual(app_requests.pending()[0]["about"]["name"], "pager")      # as the home lists them
        status, done = self.api("POST", f"/api/apps/requests/{rid}", {"approve": True})
        self.assertEqual((status, done["state"]), (200, "approved"))
        self.assertIn("pager", self.on())
        self.assertEqual(told[-1][:2] + told[-1][3:], ("g", "c1", "approved"))
        self.assertIn("The user approved: Pager is installed.", told[-1][2])
        self.assertEqual(self.api("GET", f"/api/apps/requests/{rid}")[1]["state"], "approved")   # as `ag apps` waits
        self.assertEqual(self.api("GET", "/api/apps/requests")[1]["requests"], [])
        rid = self.api("POST", "/api/apps/uninstall", {"name": "pager", "actor": "c1"})[1]["waiting"]["id"]
        self.assertEqual(self.api("POST", f"/api/apps/requests/{rid}", {"approve": False})[1]["state"], "declined")
        self.assertIn("pager", self.on())                                        # declined: still installed
        self.assertIn("The user declined", told[-1][2])
        self.assertEqual(self.api("POST", f"/api/apps/requests/{rid}", {"approve": True})[0], 404)   # answered once

    def test_ag_apps_install_in_an_agent_s_shell_waits_for_the_user(self):
        import contextlib
        import io
        from ag.cli import actors as actors_cli
        from ag.cli import apps as apps_cli
        app_requests.forget()
        self.addCleanup(app_requests.forget)
        env = {actors_cli.DASHBOARD_VAR: f"http://127.0.0.1:{self.port}", "AG_ACTOR": "c1"}
        out = io.StringIO()
        with unittest.mock.patch.dict(os.environ, env), unittest.mock.patch.object(apps_cli, "WAIT", 0.5), \
                unittest.mock.patch.object(apps_cli, "POLL", 0.1), contextlib.redirect_stdout(out):
            for v in ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID"):
                os.environ.pop(v, None)
            code = apps_cli.main(["install", self.src, "--yes"])                 # --yes: only its own question
        self.assertEqual(code, 1)
        self.assertIn("Asked the user to approve this in the dashboard", out.getvalue())
        self.assertIn("No answer yet", out.getvalue())
        self.assertNotIn("pager", self.on())
        (r,) = app_requests.pending()
        self.assertEqual((r["actor"], r["op"]), ("c1", "install"))

    def test_uninstalled_its_windows_go_and_come_back_when_it_is_installed_again(self):
        st = self.api("POST", "/api/apps/stage", {"source": self.src})[1]
        self.api("POST", "/api/apps/install", {"id": st["id"]})
        i = self.h.open("pager", "g", self.folder)
        self.h.call("pager", i, "add", {"text": "x"}, app_kit.Caller(channel=""))   # its backend started
        backend = self.h.apps["pager"].app
        stopped = unittest.mock.patch.object(backend, "stop", wraps=backend.stop)
        stop = stopped.start()
        self.addCleanup(stopped.stop)
        self.h.flush()
        self.assertEqual(self.api("POST", "/api/apps/uninstall", {"name": "pager"}),
                         (200, {"name": "pager", "how": "home"}))
        stop.assert_called_once()
        self.assertNotIn("pager", self.on())
        self.assertEqual([x for x in self.h.listed("g")["instances"] if x["app"] == "pager"], [])
        self.assertTrue(os.path.isdir(os.path.join(self.h_home(), "apps", "pager")))      # its data/ folder kept
        st = self.api("POST", "/api/apps/stage", {"source": self.src})[1]
        self.api("POST", "/api/apps/install", {"id": st["id"]})
        self.assertEqual([x["id"] for x in self.h.listed("g")["instances"] if x["app"] == "pager"], [i.id])

    def test_an_app_that_comes_with_ag_is_uninstalled_by_config_toml_and_installed_again(self):
        self.assertEqual(self.api("POST", "/api/apps/uninstall", {"name": "slate"})[1]["how"], "builtin")
        self.assertNotIn("slate", self.on())
        got = self.api("GET", "/api/apps/catalog")[1]
        self.assertEqual([(a["name"], a["origin"]) for a in got["available"]], [("slate", "builtin")])
        status, mark = self.api("GET", "/apps/mark/slate.svg")                    # its mark, to list it
        self.assertEqual((status, mark.decode()), (200, MARK))
        self.assertEqual(self.api("POST", "/api/apps/install", {"builtin": "slate"}), (200, {"name": "slate"}))
        self.assertIn("slate", self.on())

    def test_refused_an_app_from_ag_apps_path_a_bad_source_and_one_not_installed(self):
        status, got = self.api("POST", "/api/apps/uninstall", {"name": "notes"})
        self.assertEqual(status, 400)
        self.assertIn("AG_APPS_PATH", got["error"])
        self.assertEqual(self.api("POST", "/api/apps/uninstall", {"name": "nope"})[0], 400)
        status, got = self.api("POST", "/api/apps/stage", {"source": os.path.join(self.tmp.name, "nowhere")})
        self.assertEqual(status, 400)
        self.assertIn("isn't a folder or a git URL", got["error"])

    def test_a_tool_called_after_its_app_was_uninstalled_is_refused_saying_why(self):
        from ag_dashboard import mcp
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": "pager_page", "arguments": {}}}).encode()
        status, got = mcp.handle(body, tool_gateway.tools("g"), lambda n, a: {}, unknown=tool_gateway.gone)
        self.assertEqual(status, 200)
        self.assertTrue(got["result"]["isError"])
        said = got["result"]["content"][0]["text"]
        self.assertIn("pager_page: no such tool now", said)
        self.assertIn("installed now: notes, slate", said)
        self.assertIn("error", mcp.handle(body, [], lambda n, a: {})[1])           # no `unknown`: the protocol's error

    def test_each_read_finds_what_is_in_the_folders_now_an_app_put_there_by_hand_too(self):
        got = self.api("GET", "/api/apps/catalog")[1]
        self.assertEqual(got["found"], {"added": [], "gone": [], "changed": []})
        write_app(os.path.join(self.h_home(), "apps"), "pager", PAGER)        # copied in by hand, not installed
        got = self.api("GET", "/api/apps/catalog")[1]
        self.assertEqual(got["found"]["added"], ["pager"])
        self.assertIn("pager", [a["name"] for a in got["installed"]])
        self.assertIn("pager", self.on())                                        # on everywhere, as an install's
        os.remove(os.path.join(self.h_home(), "apps", "pager", "app.toml"))      # and removed by hand
        self.assertEqual(self.api("GET", "/api/apps/catalog")[1]["found"]["gone"], ["pager"])
        self.assertNotIn("pager", self.on())

    def test_no_updates_for_apps_not_installed_from_git(self):
        self.assertEqual(self.api("GET", "/api/apps/updates"), (200, {"updates": {}}))

    def test_ag_apps_installs_lists_and_uninstalls_asking_first_unless_told_yes(self):
        import contextlib
        import io
        from ag.cli import actors as actors_cli
        from ag.cli import apps as apps_cli
        env = unittest.mock.patch.dict(os.environ, {actors_cli.DASHBOARD_VAR: f"http://127.0.0.1:{self.port}"})
        env.start()
        self.addCleanup(env.stop)
        for v in actors_cli.ACTOR_VARS:                                         # the user's own terminal: no agent's
            os.environ.pop(v, None)

        def run(*args):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                    unittest.mock.patch.object(sys.stdin, "isatty", return_value=False):
                code = apps_cli.main(list(args))
            return code, out.getvalue() + err.getvalue()

        code, said = run("install", self.src)                                   # no terminal to ask in: not done
        self.assertEqual(code, 1)
        self.assertIn("--yes", said)
        self.assertNotIn("pager", self.on())
        self.assertEqual(os.listdir(os.path.join(self.h_home(), "apps", ".incoming")), [])   # nothing left staged
        code, said = run("install", self.src, "--yes")
        self.assertEqual(code, 0, said)
        self.assertIn("pager_add", said)
        self.assertIn("pager", self.on())
        code, said = run("list", "--all")
        self.assertIn("Pager (pager) 1", said)
        self.assertEqual(run("uninstall", "slate", "--yes")[0], 0)
        self.assertIn("Slate (slate) -- ", run("list", "--all")[1].split("Available to install")[1])
        self.assertEqual(run("install", "slate")[0], 0)                          # one of ag's, back: nothing to ask
        self.assertIn("slate", self.on())
        self.assertEqual(run("uninstall", "pager", "--yes")[0], 0)
        self.assertNotIn("pager", self.on())

    def h_home(self):
        from ag_dashboard import home
        return home.HOME


if __name__ == "__main__":
    unittest.main()
