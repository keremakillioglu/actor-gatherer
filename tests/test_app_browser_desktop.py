"""The ag desktop app's link (desktop/DESIGN.md; ag_dashboard/api/apps.py's /api/desktop, app_host.py's native_link,
the Browser's AppCdp): once the desktop app connects, the home's Browsers live in its native pages -- opened there,
without what only a windowless Chrome needs, no screencast for the panel -- and are paused, never moved, while it is
away; only the desktop app, with the home's token, may connect; each message is the app's it is of ("app"), and the
host hands each to that app."""
import json
import os
import queue
import socket
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wsproto import ConnectionType, WSConnection  # noqa: E402
from wsproto.events import AcceptConnection, CloseConnection, RejectConnection, Request, TextMessage  # noqa: E402

import secrets  # noqa: E402

from ag_apps.browser import core as browser  # noqa: E402
from ag_dashboard import desktop, home as dashboard_home, server  # noqa: E402
from test_app_browser import Home  # noqa: E402
from test_dashboard import HomeBase  # noqa: E402

WINDOWLESS = ("Page.setInterceptFileChooserDialog", "WebAuthn.enable", "Emulation.setDeviceMetricsOverride")


class FakeApp:
    """The app's side of the link, by hand (desktop/src/browsers.ts's Link): each page it is asked for, a target of its
    own; every message ag sends kept, as (method, params, session)."""

    def __init__(self, chrome: "browser.Chrome"):
        self.sent, self.pages, self.closed = [], {}, False
        self.todo: "queue.Queue" = queue.Queue()
        self.conn = None
        self.conn = chrome.attach_app(self.todo.put, lambda: setattr(self, "closed", True))
        threading.Thread(target=self._answer, daemon=True).start()

    def _answer(self) -> None:
        while True:
            m = json.loads(self.todo.get())
            self.sent.append((m["method"], m.get("params") or {}, m.get("sessionId")))
            if "id" not in m:                            # ag's own word (App.hold, App.esc): nothing to answer
                continue
            self.conn.got(json.dumps({"id": m["id"], "result": self._result(m["method"], m.get("params") or {}),
                                      **({"sessionId": m["sessionId"]} if m.get("sessionId") else {})}))

    def _result(self, method: str, p: dict) -> dict:
        if method == "Target.createTarget":
            target = f"T{len(self.pages) + 1}"
            self.pages[target] = p.get("url", "")
            return {"targetId": target}
        if method == "Target.attachToTarget":
            return {"sessionId": "S-" + p["targetId"]}
        if method == "Target.getTargetInfo":
            return {"targetInfo": {"targetId": p.get("targetId"), "type": "page", "title": "", "url": ""}}
        if method == "Page.navigate":
            return {"frameId": "T1", "loaderId": "L1"}
        if method == "App.find":                         # the app's own find in its page (desktop/src/browsers.ts)
            return {"count": 3, "index": 0} if p.get("q") else {"count": 0, "index": -1}
        return {}

    def methods(self, session=None):
        return [m for m, _, s in self.sent if session is None or s == session]

    def leave(self) -> None:
        """The app quit: its link closed."""
        self.conn.got(None)


def until(check, wait: float = 5.0):
    end = time.time() + wait
    while time.time() < end and not check():
        time.sleep(0.02)
    return check()


class AppHome(Home):
    """A home with a Browser, no app connected yet."""

    def setUp(self):
        super().setUp()
        self.bs = self.browsers()
        self.addCleanup(self.bs.close)
        with mock.patch.object(browser, "available", lambda: True):
            self.key = self.bs.keep(secrets.token_hex(8), self.root, "g")["key"]
        self.b = self.bs.get(self.key)


class AppModeTest(AppHome):

    def test_the_home_the_app_connects_to_is_its_and_its_browsers_open_there(self):
        self.assertNotEqual(browser.mode(), "app")
        app = FakeApp(self.bs.chrome)
        self.assertTrue(os.path.exists(browser.app_marker()))
        self.assertEqual(browser.mode(), "app")
        self.assertTrue(browser.available())
        self.b.saved = [{"url": "http://example.test/a", "title": "A"}]
        self.b.live()
        self.assertEqual(app.pages, {"T1": "about:blank"})
        self.assertIn("Page.navigate", app.methods("S-T1"))
        for method in ("Page.enable", "Runtime.enable", "DOM.enable", "Overlay.enable"):
            self.assertIn(method, app.methods("S-T1"))
        for method in WINDOWLESS:                       # the app's native page has its own size and choosers, prompts
            self.assertNotIn(method, app.methods())     # and pointer: no UI_JS either
        self.assertNotIn(browser.UI_WORLD, [p.get("worldName") for m, p, _ in app.sent])
        self.assertNotIn(browser.UI_BINDING, [p.get("name") for m, p, _ in app.sent])
        self.assertEqual(self.b.state()["tabs"][0]["target"], "T1")

    def test_without_the_app_its_homes_browsers_are_paused_not_moved(self):
        FakeApp(self.bs.chrome).leave()
        self.assertTrue(until(lambda: self.bs.chrome.app is None))
        with self.assertRaises(browser.BrowserError) as caught:
            self.b.live()
        self.assertIn("paused while the ag app is closed", str(caught.exception))
        self.assertIsNone(self.bs.chrome.conn)          # no other Chrome started in its place

    def test_the_app_quitting_pauses_its_browsers_and_its_return_reopens_their_pages(self):
        app = FakeApp(self.bs.chrome)
        viewer = self.b.join(native=True)
        self.addCleanup(self.b.leave, viewer)
        self.b.saved = [{"url": "http://example.test/a", "title": "A"}]
        self.assertTrue(until(lambda: self.b.tabs))
        app.leave()
        self.assertTrue(until(lambda: not self.b.tabs and "paused" in self.b.error))
        self.assertEqual(self.b.saved[0]["url"], "http://example.test/a")
        back = FakeApp(self.bs.chrome)                  # watched: its pages open again as the app connects
        self.assertTrue(until(lambda: back.pages and self.b.tabs and not self.b.error))
        self.assertIn(("Page.navigate", {"url": "http://example.test/a"}, "S-T1"), back.sent)

    def test_the_apps_page_gets_no_screencast_a_page_in_a_browser_does(self):
        app = FakeApp(self.bs.chrome)
        native = self.b.join(native=True)
        self.addCleanup(self.b.leave, native)
        self.assertTrue(until(lambda: self.b.tabs))
        time.sleep(0.2)
        self.assertNotIn("Page.startScreencast", app.methods())
        framed = self.b.join()
        self.addCleanup(self.b.leave, framed)
        self.assertTrue(until(lambda: "Page.startScreencast" in app.methods()))

    def test_a_new_app_link_replaces_the_old_one(self):
        first = FakeApp(self.bs.chrome)
        second = FakeApp(self.bs.chrome)
        self.assertTrue(first.closed)
        self.assertIs(self.bs.chrome.cdp(), second.conn)

    def test_a_new_page_is_asked_for_at_its_views_size(self):
        # (laid out at it while no pane shows it, not at 0 x 0: the app sizes a hidden page by emulation)
        app = FakeApp(self.bs.chrome)
        self.b.resize(900, 600, 2)
        self.b.live()
        made = [p for m, p, _ in app.sent if m == "Target.createTarget"]
        self.assertEqual(made, [{"url": "about:blank", "width": 900, "height": 600}])


class OverThePageTest(AppHome):
    """What the dashboard draws over the screen elsewhere, in the app's page (CUES_JS); Pick by Chrome's inspector;
    the user's Esc and input there (desktop/DESIGN.md, step 3)."""

    def setUp(self):
        super().setUp()
        self.app = FakeApp(self.bs.chrome)
        self.viewer = self.b.join(native=True)
        self.addCleanup(self.b.leave, self.viewer)
        self.assertTrue(until(lambda: self.b.tabs))
        self.tab = self.b.tabs[0]
        self.b.event("Runtime.executionContextCreated",               # the page's cues world, made
                     {"context": {"id": 7, "name": browser.CUES_WORLD, "auxData": {"frameId": self.tab.target}}},
                     self.tab.session)

    def drawn(self):
        return [json.loads(p["expression"].split(".draw(", 1)[1][:-1]) for m, p, _ in self.app.sent
                if m == "Runtime.evaluate" and p.get("contextId") == 7]

    def told(self, method):
        return [p for m, p, s in self.app.sent if m == method and s is None]

    def test_its_page_gets_the_cues_script_in_a_world_of_its_own(self):
        sent = {m: p for m, p, s in self.app.sent if s == self.tab.session}
        self.assertEqual(sent["Page.addScriptToEvaluateOnNewDocument"]["worldName"], browser.CUES_WORLD)
        self.assertEqual(sent["Runtime.addBinding"]["name"], browser.CUES_BINDING)

    def test_what_the_agent_is_about_to_do_is_drawn_and_its_esc_is_ags(self):
        self.b.next = {"label": 'clicking button "Pay"', "box": [10, 20, 30, 40], "tool": "click", "cue": None}
        self.b._publish()
        self.assertTrue(until(lambda: any(d["next"] == {"box": [10, 20, 30, 40], "tool": "click"} for d in self.drawn())))
        self.assertTrue(until(lambda: {"targetId": self.tab.target, "on": True} in self.told("App.esc")))
        self.b.event("App.escape", {"targetId": self.tab.target}, None)   # the user's Esc on the page
        self.assertTrue(until(lambda: self.b.halt.is_set()))
        self.b.next = None
        self.b._publish()
        self.assertTrue(until(lambda: self.told("App.esc")[-1] == {"targetId": self.tab.target, "on": False}))

    def test_its_marks_follow_the_agent_while_no_panel_shows_it(self):
        # the user goes to another task as the agent acts: its panel gone, the action's end still clears the page
        self.b.acting, self.b.acting_until, self.b.doing = {"label": "x", "box": [10, 20, 30, 40]}, 0, 'clicking "Pay"'
        self.b.doing_tool = "click"
        self.b._publish()
        self.assertTrue(until(lambda: any(d["acting"] for d in self.drawn())))
        self.b.leave(self.viewer)
        self.b.doing = ""
        self.b.acted()
        self.assertTrue(until(lambda: self.drawn()[-1]["acting"] is None))

    def test_a_tab_left_while_the_agent_acted_in_it_is_cleared(self):
        # its click opened a tab, shown at once: the marks on the tab it clicked in are not left there
        self.b.acting, self.b.acting_until, self.b.doing = {"label": "x", "box": [10, 20, 30, 40]}, 0, 'clicking "Pay"'
        self.b.doing_tool = "click"
        self.b._publish()
        self.assertTrue(until(lambda: any(d["acting"] for d in self.drawn())))
        with self.b.lock:
            self.b.tabs.append(browser.Tab("T9", "S-T9"))
            self.b.active = 1
        self.b.doing = ""
        self.b.acted()
        self.assertTrue(until(lambda: self.drawn()[-1]["acting"] is None))

    def test_a_state_read_before_another_is_never_given_after_it(self):
        # Chrome's thread and the agent's both publish: what the page and its panel keep is the state read last
        real, reading, go = self.b.state, threading.Event(), threading.Event()

        def slow():
            s = real()
            if s["acting"] and not go.is_set():          # read as the agent acts, then held up
                reading.set()
                go.wait(5)
            return s
        self.b.acting, self.b.acting_until, self.b.doing = {"label": "x", "box": [10, 20, 30, 40]}, 0, 'clicking "Pay"'
        self.b.doing_tool = "click"
        with mock.patch.object(self.b, "state", slow):
            first = threading.Thread(target=self.b._publish)
            first.start()
            self.assertTrue(reading.wait(5))
            self.b.doing = ""
            self.b.acted()                               # its action over, published meanwhile
            go.set()
            first.join(5)
        self.assertTrue(until(lambda: self.drawn() and self.drawn()[-1]["acting"] is None))
        self.assertIsNone(next(p for k, p in self.viewer.take(0) if k == "state")["acting"])

    def test_pick_runs_in_chromes_inspector_and_ends_on_a_pick_or_esc(self):
        self.b.set_mode("pick")
        self.assertEqual(self.b.state()["picking"], "pick")
        self.assertIn(("Overlay.setInspectMode", "searchForNode"),
                      [(m, p.get("mode")) for m, p, _ in self.app.sent if m == "Overlay.setInspectMode"])
        self.assertTrue(until(lambda: any(d["mode"] == "pick" for d in self.drawn())))
        self.b.event("Overlay.inspectNodeRequested", {"backendNodeId": 42}, self.tab.session)   # clicked
        self.assertTrue(until(lambda: self.b.state()["picking"] is None))
        self.assertEqual([p.get("mode") for m, p, _ in self.app.sent if m == "Overlay.setInspectMode"][-1], "none")
        self.b.set_mode("area")
        self.b.event("App.escape", {"targetId": self.tab.target}, None)
        self.assertTrue(until(lambda: self.b.state()["picking"] is None))
        self.assertFalse(self.b.halt.is_set())            # an Esc that ended a Pick or Area stops no agent

    def test_the_users_clicks_in_the_page_are_theirs_unless_the_agent_acts(self):
        said = {"name": browser.CUES_BINDING, "payload": json.dumps({"t": "click", "x": 5, "y": 6, "mods": 0})}
        before = self.b.user_at
        self.b.event("Runtime.bindingCalled", said, self.tab.session)
        self.assertGreater(self.b.user_at, before)
        self.b.acting, self.b.acting_until, self.b.acting_since = {"label": "x", "box": None}, 0, time.time()
        at = self.b.user_at
        self.b.event("Runtime.bindingCalled", said, self.tab.session)   # the agent's own click, seen in the page
        self.assertEqual(self.b.user_at, at)
        self.b.acted()                                   # its action done: a click now, just after, is the user's
        self.b.event("Runtime.bindingCalled", said, self.tab.session)
        self.assertGreater(self.b.user_at, at)

    def test_find_is_the_native_pages_own_and_cmd_f_opens_the_bar(self):
        self.assertEqual(self.b.find("Pay"), {"count": 3, "index": 0})
        self.assertIn(("App.find", {"targetId": self.tab.target, "q": "Pay", "back": False, "again": False}),
                      [(m, p) for m, p, s in self.app.sent if s is None])
        self.assertEqual(self.b.find(""), {"count": 0, "index": -1})     # the bar closed: the page's find ended
        self.b.event("Runtime.bindingCalled", {"name": browser.CUES_BINDING, "payload": json.dumps({"t": "find"})},
                     self.tab.session)                    # the user's Cmd+F, which the page didn't take
        first = self.b.state()["popup"]
        self.assertEqual(first["k"], "find")
        self.b.event("App.findBar", {"targetId": self.tab.target}, None)  # "Find in Page..." in the app's menu
        self.assertGreater(self.b.state()["popup"]["n"], first["n"])

    def test_the_users_input_is_held_off_the_page_while_the_agent_acts(self):
        self.b.acts.acquire()
        self.b.acts_by = threading.get_ident()
        self.b._hold(True)
        self.assertTrue(until(lambda: self.told("App.hold") == [{"targetId": self.tab.target, "on": True}]))
        self.b.let_go()
        self.assertTrue(until(lambda: self.told("App.hold")[-1:] == [{"targetId": self.tab.target, "on": False}]))


class Socket:
    """The app's WebSocket to /api/desktop, by hand."""

    def __init__(self, port: int, origin: str = ""):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=10)
        self.ws = WSConnection(ConnectionType.CLIENT)
        extra = [(b"origin", origin.encode())] if origin else []
        self.sock.sendall(self.ws.send(Request(host=f"127.0.0.1:{port}", target="/api/desktop", extra_headers=extra)))
        self.accepted, self.closed, self.got = None, None, []
        self._until(lambda: self.accepted is not None or self.closed is not None)

    def _until(self, done):
        while not done():
            data = self.sock.recv(1 << 16)
            self.ws.receive_data(data or None)
            for ev in self.ws.events():
                if isinstance(ev, AcceptConnection):
                    self.accepted = True
                elif isinstance(ev, RejectConnection):
                    self.accepted = False
                elif isinstance(ev, TextMessage):
                    self.got.append(json.loads(ev.data))
                elif isinstance(ev, CloseConnection):
                    self.closed = ev.code
            if not data:
                self.closed = self.closed or -1

    def say(self, text: str) -> None:
        self.sock.sendall(self.ws.send(TextMessage(data=text)))

    def wait_closed(self) -> int:
        self._until(lambda: self.closed is not None)
        return self.closed

    def next(self) -> dict:
        self._until(lambda: self.got or self.closed is not None)
        return self.got.pop(0)

    def close(self):
        self.sock.close()


class LinkRouteTest(HomeBase):
    """The desktop app's link through the dashboard: its token checked, then handed to the Browser (the app that asks
    native_view), each message tagged with it."""

    def setUp(self):
        super().setUp()
        self.saved = browser.HOME, browser.DB_PATH
        self.addCleanup(lambda: setattr(browser, "HOME", self.saved[0]) or setattr(browser, "DB_PATH", self.saved[1]))
        browser.HOME = dashboard_home.HOME                 # the test's home, before the Browser's backend says so
        self.httpd = server.serve("127.0.0.1", 0, live_updates=False)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.serving(self.httpd)
        self.hosts.append(self.httpd.app_host)
        self.port = self.httpd.server_port
        if "browser" not in self.httpd.app_host.apps:
            self.skipTest("the Browser app is not found")

    def test_a_wrong_token_or_a_web_page_is_refused(self):
        wrong = Socket(self.port)
        wrong.say("not the token")
        self.assertEqual(wrong.wait_closed(), 1008)
        wrong.close()
        page = Socket(self.port, origin=f"http://127.0.0.1:{self.port}")   # a page's socket says where it is
        self.assertFalse(page.accepted)
        page.close()
        self.assertFalse(os.path.exists(browser.app_marker()))

    def test_the_app_with_the_token_links_and_is_asked_for_pages_by_the_browser(self):
        app = Socket(self.port)
        self.addCleanup(app.close)
        app.say(desktop.app_token())
        bs = self.httpd.app_host.backend("browser").bs
        chrome = bs.chrome
        self.assertTrue(until(lambda: chrome.app is not None))
        self.assertEqual(browser.mode(), "app")
        asked = []
        threading.Thread(target=lambda: asked.append(chrome.cdp().call("Target.createTarget", {"url": "about:blank"})),
                         daemon=True).start()
        m = app.next()
        self.assertEqual((m["method"], m["app"]), ("Target.createTarget", "browser"))   # the Browser's, said
        app.say(json.dumps({"id": m["id"], "result": {"targetId": "T9"}, "app": "browser"}))
        self.assertTrue(until(lambda: asked == [{"targetId": "T9"}]))
        threading.Thread(target=lambda: asked.append(chrome.cdp().call("Target.getTargets", {})), daemon=True).start()
        m = app.next()
        app.say(json.dumps({"id": m["id"], "result": {"targetInfos": []}}))        # naming no app: the only one's
        self.assertTrue(until(lambda: asked[-1] == {"targetInfos": []}))
        app.say(json.dumps({"id": 999, "result": {}, "app": "nosuch"}))          # another app's: no one's here
        app.close()                                     # the app quit: its link gone, its Browsers paused
        self.assertTrue(until(lambda: chrome.app is None))


if __name__ == "__main__":
    unittest.main()
