"""The Browser as an app, through the dashboard as its host (ag_apps/browser/backend.py; app_kit/DESIGN.md step 8): its
manifest, its tools and instructions for its agent alone, what the user does told its agent in its channel, their
next message seen, its older actors adopted and its tabs copied from the dashboard's database once, the desktop app's
link handed to it with its messages tagged, and its panel's routes on the app's own origin."""
import base64
import http.client
import json
import os
import sqlite3
import sys
import threading
import time
import tomllib
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ag_apps.browser import core  # noqa: E402
from ag_dashboard import app_agents, app_host, server, sessions, task_links, tool_gateway  # noqa: E402
from test_dashboard import HomeBase  # noqa: E402
from test_dashboard_app_host import insert_here  # noqa: E402

KEY = "0123456789abcdef"


def until(check, wait: float = 5.0) -> bool:
    end = time.time() + wait
    while time.time() < end:
        if check():
            return True
        time.sleep(0.02)
    return bool(check())


class Hosted(HomeBase):
    """The Browser as the dashboard hosts it: an AppHost on the test's home (gatherer `g`), a folder to work in; no
    Chrome started (`available` said yes)."""

    def setUp(self):
        super().setUp()
        self.root = os.path.join(os.path.realpath(self.tmp.name), "site")
        os.makedirs(self.root)
        self.host = self.new_host()
        if "browser" not in self.host.apps:
            self.skipTest("the Browser app is not found")
        # the host's own copy of the app's core (app_host.py's `_import`: a package of its own), as its backend uses it
        self.host.backend("browser")
        self.core = sys.modules["_ag_app_browser.core"]
        avail = mock.patch.object(self.core, "available", lambda: True)
        avail.start()
        self.addCleanup(avail.stop)

    def new_host(self):
        h = app_host.AppHost(0, write=insert_here)
        self.addCleanup(h.close)
        self.hosts.append(h)
        return h

    def bs(self, h=None):
        return (h or self.host).backend("browser").bs


class AppTest(Hosted):
    def test_its_manifest_an_agent_of_its_own_its_tools_and_a_native_page(self):
        m = self.host.apps["browser"].manifest
        self.assertEqual((m.instances, m.access, m.agent.offered, m.capabilities.native_view, m.capabilities.reads),
                         ("many", "task", True, True, ("user_message",)))
        self.assertEqual([t.name for t in m.tools], [t["name"] for t in core.TOOLS])   # tools.json: core's (make.py)
        self.assertTrue(all(t.handled_by == "backend" for t in m.tools))
        self.assertEqual(m.instructions.strip(), core.instructions().strip())            # instructions.md: core's

    def test_an_instance_is_a_browser_on_its_folder(self):
        i = self.host.open("browser", "g", self.root)
        self.assertEqual(i.title, "site")
        self.assertEqual(self.bs().config(i.id), {"key": i.id, "root": self.root, "gatherer": "g"})
        with mock.patch.object(self.core, "available", lambda: False):
            with self.assertRaisesRegex(Exception, "no Chrome here"):
                self.host.open("browser", "g", self.root)

    def test_what_the_user_does_is_told_its_agents_in_their_channels(self):
        i = self.host.open("browser", "g", self.root)
        self.host.attach("g", i.id, "c1")
        b = self.bs().get(i.id)
        with mock.patch.object(self.core, "TELL_AFTER", 30):
            b.note('clicked button "Pay"')
        b._tell()
        self.host.flush()
        got = self.host.read("browser", i, ["context_stream"], channel="c1")
        self.assertEqual(len(got), 1)
        self.assertEqual((got[0]["payload"]["stream"], got[0]["payload"]["author"]), (f"Browser ({i.id})", "the user"))
        self.assertIn('the user: clicked button "Pay"', got[0]["payload"]["text"])
        with self.assertRaises(Exception):                     # another agent's: not this Browser's to read
            self.host.read("browser", i, ["context_stream"], channel="c2")

    def test_its_agents_next_message_puts_the_picks_away_and_lifts_a_stop(self):
        i = self.host.open("browser", "g", self.root)
        self.host.attach("g", i.id, "c1")
        backend = self.host.backend("browser")
        b = self.bs().get(i.id)
        backend._seen(i)                                       # where the agent's messages are now
        b.picks = [{"kind": "area", "id": "p1", "label": "an area", "box": [0, 0, 5, 5]}]
        b.halt.set()
        backend._seen(i)
        self.assertTrue(b.halt.is_set())                       # no message since: as it was
        insert_here("g", {"channel": "c1"}, [{"type": "user_message", "payload": {"text": "now this", "role": "user"}}], [])
        backend._seen(i)
        self.assertEqual((b.picks, b.halt.is_set()), ([], False))

    def test_an_older_browser_s_actor_is_adopted_and_its_tabs_copied_once(self):
        old = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(self.host.data_folder("browser")))),
                           "dashboard.db")
        conn = sqlite3.connect(old)
        conn.execute(self.core.SCHEMA)
        conn.execute("INSERT INTO browser (key, gatherer, root, session_id, created_at, tabs, active) VALUES "
                     "(?, 'g', ?, 'c1', 0, ?, 0)", (KEY, self.root, json.dumps([{"url": "https://example.com/", "title": "Ex"}])))
        conn.commit()
        conn.close()
        os.remove(self.core.DB_PATH)                           # the app's own: none yet, as in a home that had no app
        again = self.new_host()
        i = again.adopt("browser", "g", KEY, self.root, "c1")
        self.assertEqual((i.id, again.agents_of(i)), (KEY, ["c1"]))
        self.assertEqual(self.bs(again).get(KEY).saved, [{"url": "https://example.com/", "title": "Ex"}])
        rows = [{"session_id": "c1", "gatherer": "g", "cwd": self.root, "role": json.dumps({"browser": KEY})}]
        with mock.patch.object(again, "adopt", wraps=again.adopt) as adopted:
            app_agents.adopt_all(type("S", (), {"list": lambda self: rows})(), again)
        self.assertEqual([c.args[:3] for c in adopted.call_args_list], [("browser", "g", KEY)])


class GatewayTest(Hosted):
    """Only an agent attached to a Browser is given its tools and its instructions."""

    def setUp(self):
        super().setUp()
        saved = tool_gateway.HOST, tool_gateway.ORIGIN
        tool_gateway.HOST, tool_gateway.ORIGIN = self.host, "http://127.0.0.1:4999"
        self.addCleanup(lambda: setattr(tool_gateway, "HOST", saved[0]) or setattr(tool_gateway, "ORIGIN", saved[1]))
        self.inst = self.host.open("browser", "g", self.root)
        task_links.link("g", self.inst.id, "c1")

    def test_its_tools_for_its_agent_alone(self):
        self.assertIn("browser_snapshot", {t["name"] for t in tool_gateway.tools("g", ("c1",))})
        self.assertNotIn("browser_snapshot", {t["name"] for t in tool_gateway.tools("g", ("c2",))})

    def test_claude_code_gets_the_server_and_the_instructions_codex_too(self):
        s = {"session_id": "c1", "gatherer": "g", "harness": "claude", "cwd": self.root,
             "role": app_agents.role("browser", self.inst.id)}
        args = sessions.extra_args(s)
        self.assertTrue(json.loads(args[args.index("--mcp-config") + 1])["mcpServers"]["ag-apps"]["url"].endswith("/mcp/c1"))
        told = args[args.index("--append-system-prompt") + 1]
        self.assertIn("browser_snapshot", told)
        self.assertIn("Click only when there is no other way", told)          # dedicated tools first, the page last
        self.assertNotIn("<browser_state>", told)
        self.assertNotIn("--settings", args)                                   # no guard: it edits no files
        task_links.link("g", self.inst.id, "c3")
        parsed = {}
        for one in [a for k, a in zip(sessions.extra_args({**s, "session_id": "c3", "harness": "codex"}),
                                      sessions.extra_args({**s, "session_id": "c3", "harness": "codex"})[1:]) if k == "-c"]:
            parsed.update(tomllib.loads(one))
        self.assertIn("browser_snapshot", parsed["developer_instructions"])


class NativeLinkTest(Hosted):
    """The desktop app's link, as the host hands it to the Browser: what it sends tagged, what comes to it routed."""

    def test_its_messages_are_tagged_and_the_desktop_app_s_routed(self):
        sent, closed = [], []
        got = self.host.native_link(sent.append, lambda: closed.append(1))
        chrome = self.bs().chrome
        self.assertTrue(until(lambda: chrome.app is not None))
        answer = []
        threading.Thread(target=lambda: answer.append(chrome.cdp().call("Target.getTargets", {})), daemon=True).start()
        self.assertTrue(until(lambda: sent))
        m = json.loads(sent[0])
        self.assertEqual((m["method"], m["app"]), ("Target.getTargets", "browser"))
        got(json.dumps({"id": m["id"], "result": {"targetInfos": []}, "app": "notes"}))   # another app's: not the Browser's
        time.sleep(0.2)
        self.assertEqual(answer, [])
        got(json.dumps({"id": m["id"], "result": {"targetInfos": []}, "app": "browser"}))
        self.assertTrue(until(lambda: answer == [{"targetInfos": []}]))
        got(None)                                              # the link gone
        self.assertTrue(until(lambda: chrome.app is None))


class ServedTest(Hosted):
    """Its panel's routes, on the app's own origin, through the dashboard's server."""

    def setUp(self):
        super().setUp()
        self.httpd = server.serve("127.0.0.1", 0, live_updates=False)
        self.httpd.app_host._write_fn = insert_here
        self.hosts.append(self.httpd.app_host)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.serving(self.httpd)
        self.port = self.httpd.server_port
        self.origin = f"http://browser.localhost:{self.port}"
        self.inst = self.httpd.app_host.open("browser", "g", self.root)
        self.base = f"/api/w/g/{self.inst.id}"

    def ask(self, method, path, body=None, origin="mine", host="browser.localhost", raw=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Host": f"{host}:{self.port}", "Content-Type": "application/json",
                   **({"Origin": self.origin if origin == "mine" else origin} if origin else {})}
        conn.request(method, path, raw if raw is not None else (json.dumps(body) if body is not None else None), headers)
        r = conn.getresponse()
        data, kind = r.read(), r.getheader("content-type") or ""
        conn.close()
        return r.status, (json.loads(data) if "json" in kind and data else data)

    def test_what_the_panel_shows_is_answered_and_a_file_kept_for_it(self):
        self.assertEqual(self.ask("POST", f"{self.base}/choose", {"n": 7, "index": 0})[0], 409)   # a list gone
        status, got = self.ask("POST", f"{self.base}/file", {"name": "a.txt", "data": base64.b64encode(b"hi").decode()})
        self.assertEqual(status, 200)
        b = self.httpd.app_host.backend("browser").bs.get(self.inst.id)
        with open(b.uploads[got["id"]]) as fh:
            self.assertEqual(fh.read(), "hi")
        self.assertEqual(self.ask("POST", f"{self.base}/file", {"name": "a.txt", "data": "not base64!"})[0], 400)
        self.assertEqual(self.ask("POST", f"{self.base}/reveal", {"i": 3})[0], 404)
        self.ask("POST", f"{self.base}/stop", {})                            # the user's Esc: until their next message
        self.assertTrue(b.state()["halted"])
        viewer = b.join(page="pg1", visible=True)
        self.addCleanup(b.leave, viewer)
        self.assertTrue(b.watching())
        self.ask("POST", f"{self.base}/watch", {"page": "pg1", "visible": False})   # its panel out of sight
        self.assertFalse(b.watching())

    def test_a_link_its_panel_is_given_is_opened_through_its_route_and_only_a_page_on_the_web(self):
        b = self.httpd.app_host.backend("browser").bs.get(self.inst.id)
        with mock.patch.object(type(b), "open_link", lambda me, url: url):
            self.assertEqual(self.ask("POST", f"{self.base}/open", {"url": "https://example.com/a"}),
                             (200, {"done": "https://example.com/a"}))
        status, got = self.ask("POST", f"{self.base}/open", {"url": "file:///etc/hosts"})
        self.assertEqual(status, 400)
        self.assertIn("not a link a Browser opens", got["error"])

    def test_the_address_bar_s_suggestions_for_every_browser(self):
        self.core.in_db(lambda c: sys.modules["_ag_app_browser.visited"].visit(c, "https://example.com/a", "A page"))
        status, got = self.ask("GET", "/api/visited?q=exam")
        self.assertEqual((status, got), (200, {"pages": [{"url": "https://example.com/a", "title": "A page"}]}))
        self.assertEqual(self.ask("POST", "/api/visited", {"forget": "https://example.com/a"})[0], 200)
        self.assertEqual(self.ask("GET", "/api/visited?q=exam")[1], {"pages": []})
        self.assertEqual(self.ask("POST", "/api/visited", {"forget": "x"}, origin="http://evil.example")[0], 403)

    def test_only_its_own_panel_may_post_and_an_unknown_browser_is_not_found(self):
        self.assertEqual(self.ask("POST", f"{self.base}/nav", {"url": "x"}, origin="http://evil.example")[0], 403)
        self.assertEqual(self.ask("POST", f"{self.base}/nav", {"url": "x"}, origin=None)[0], 403)
        self.assertEqual(self.ask("POST", f"/api/w/g/{'0' * 16}/nav", {"url": "x"})[0], 404)
        self.assertEqual(self.ask("POST", f"{self.base}/nosuch", {})[0], 404)
        self.assertEqual(self.ask("POST", f"{self.base}/file", raw=b"x" * 40_000_001)[0], 413)   # too large a body

    def test_its_stream_is_server_sent_events(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("GET", f"{self.base}/stream?page=pg1&native=1", headers={"Host": f"browser.localhost:{self.port}"})
        r = conn.getresponse()
        self.assertEqual((r.status, r.getheader("content-type").split(";")[0]), (200, "text/event-stream"))
        first = r.read(12).decode()
        self.assertEqual(first, "event: state")
        conn.close()

    def test_a_new_one_and_its_actor_from_the_page_s_menu(self):
        with mock.patch.object(app_agents, "_name", lambda *a: None):
            status, got = self.ask("POST", "/api/apps/start",
                                   {"app": "browser", "gatherer": "g", "cwd": self.root, "harness": "claude"},
                                   origin=f"http://127.0.0.1:{self.port}", host="127.0.0.1")
        self.assertEqual(status, 200, got)
        self.assertEqual(json.loads(got["session"]["role"]), {"app": "browser", "key": got["instance"]["id"]})
        status, svg = self.ask("GET", "/apps/mark/browser.svg", origin=None, host="127.0.0.1")
        self.assertEqual(status, 200)
        self.assertIn(b"#2563EB", svg)


if __name__ == "__main__":
    unittest.main()
