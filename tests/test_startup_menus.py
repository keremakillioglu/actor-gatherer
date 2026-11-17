"""The menus a harness shows in its terminal as it starts, before its message box (an update it offers, a folder to
trust, a project's MCP server): read off its screen (harness_kit's `menu_shown`), shown in Chat as an ask, picked from
the page (sessions.py's `_pick`), and the harness started again after one it ends on to update itself."""

import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness_kit  # noqa: E402
from harness_kit import AnswerError  # noqa: E402
from harness_kit.base import at_option, menu_of  # noqa: E402
from harness_kit.claude import MENU_FOOT as CLAUDE_FOOT  # noqa: E402
from harness_kit.screen import Screen  # noqa: E402
from ag_dashboard import chat_view, data, sessions  # noqa: E402
from test_dashboard_sessions import SessionsBase  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "menus")
UP, DOWN, ENTER = "\x1b[A", "\x1b[B", "\r"


def fixture(name):
    """A recorded startup screen's rows (fixtures/menus/<name>.txt: what the harness drew, 110 x 34)."""
    with open(os.path.join(FIXTURES, name + ".txt"), encoding="utf-8") as fh:
        return fh.read().rstrip("\n")


def screen_of(name, cursor_shown=False):
    """A recorded startup screen, as its terminal shows it: its cursor hidden, as while a menu has the keys."""
    screen = Screen(110, 34)
    screen.feed((("\x1b[?25h" if cursor_shown else "\x1b[?25l") + fixture(name).replace("\n", "\r\n")).encode())
    return screen


def menu(cursor=0, **extra):
    """Codex's update offer as its screen shows it (menu_shown's), marked a menu (sessions.py's `_shown`)."""
    return {"title": "Update available · 0.164.0 → 0.169.0", "question": "",
            "lines": ["Release notes: https://github.com/openai/codex/releases/latest"],
            "options": ["Update now (runs `npm install -g @openai/codex`)", "Skip", "Skip until next version"],
            "cursor": cursor, "restarts": [0], "menu": True, **extra}


class ReadTest(unittest.TestCase):
    """Each harness's startup menus, as recorded live (Claude Code 2.1.326, Codex 0.164.0, Antigravity 1.5.8)."""

    def shown(self, harness, name):
        return harness_kit.get(harness).menu_shown(screen_of(name))

    def test_codex_s_update_offer_and_folder_trust(self):
        self.assertEqual(self.shown("codex", "codex-update"), {k: v for k, v in menu().items() if k != "menu"})
        got = self.shown("codex", "codex-trust")
        self.assertEqual((got["title"], got["options"], got["cursor"], got["restarts"]),
                         ("Folder access", ["Trust and continue", "Quit"], 0, []))
        self.assertEqual(got["lines"][0], "/tmp/w/cx")
        self.assertTrue(got["lines"][1].startswith("Trust this folder? Codex can read") and
                        got["lines"][1].endswith("Your trust decision will be saved."))    # its wrapped rows joined

    def test_claude_code_s_folder_trust_and_mcp_server(self):
        got = self.shown("claude", "claude-trust")
        self.assertEqual((got["title"], got["options"], got["cursor"], got["question"]),
                         ("Accessing workspace:", ["No, exit", "Yes, I trust this folder"], 0, ""))
        self.assertEqual(got["lines"][-2:], ["Claude Code'll be able to read, edit, and execute files here.", "Security guide"])
        got = self.shown("claude", "claude-mcp")
        self.assertEqual((got["title"], got["cursor"], len(got["options"])), ("New MCP server found in this project: demo", 2, 3))
        self.assertEqual(got["options"][2], "Continue without using this MCP server")

    def test_antigravity_s_folder_trust_and_sign_in(self):
        got = self.shown("antigravity", "agy-trust")
        self.assertEqual((got["title"], got["question"], got["options"]),
                         ("Accessing workspace:", "Do you trust the contents of this project?", ["Yes, I trust this folder", "No, exit"]))
        got = self.shown("antigravity", "agy-login")              # its logo, no letter in it, left out
        self.assertEqual((got["title"], got["lines"], got["options"]),
                         ("Welcome to the Antigravity CLI. You are currently not signed in.", ["Select login method:"],
                          ["Google OAuth", "Use a Google Cloud project"]))

    def test_not_a_menu(self):
        self.assertIsNone(harness_kit.get("codex").menu_shown(screen_of("codex-update", cursor_shown=True)))  # its box has the keys
        self.assertIsNone(harness_kit.get("claude").menu_shown(screen_of("codex-update")))   # another harness's
        foot = harness_kit.get("claude")
        permission = Screen(100, 20)                             # its permission dialog: "Esc to cancel" alone, numbered
        permission.feed("\x1b[?25l".encode() + "\r\n".join(["─" * 60, " Bash command", " Do you want to proceed?",
                                                               " ❯ 1. Yes", "   2. No", "", " Esc to cancel"]).encode())
        self.assertIsNone(foot.menu_shown(permission))
        self.assertIsNotNone(foot.permission_shown(permission))
        rows = ["─" * 40, " Pick one", " ❯ A", "   B", "Some line", "", " Enter to confirm · Esc to cancel"]
        self.assertIsNone(menu_of(rows, "❯", CLAUDE_FOOT))   # a row not an option among them
        rows = ["─" * 40, " Pick one", " ❯ A", "   B", "", " Enter to confirm · Esc to cancel"]
        self.assertEqual(menu_of(rows, "❯", CLAUDE_FOOT)["options"], ["A", "B"])

    def test_the_keys_that_pick_an_option(self):
        h = harness_kit.get("codex")
        self.assertEqual(h.pick_keys(menu(), 1), [DOWN, at_option(1), ENTER])
        self.assertEqual(h.pick_keys(menu(cursor=2), 0), [UP, UP, at_option(0), ENTER])
        self.assertEqual(h.pick_keys(menu(cursor=1), 1), [at_option(1), ENTER])
        for bad in (3, -1, None, "1", True):
            with self.assertRaises(AnswerError):
                h.pick_keys(menu(), bad)


class AskTest(unittest.TestCase):
    def test_the_ask_a_menu_becomes(self):
        shown = {**menu(), "since": 100.0}
        self.assertIsNone(data.shown_ask(shown, "codex", now=100.5))
        got = data.shown_ask(shown, "codex", now=101.5)
        self.assertEqual({k: got[k] for k in ("kind", "title", "said", "options", "cursor", "menu", "restarts", "at")},
                         {"kind": "dialog", "title": menu()["title"], "said": "", "options": menu()["options"], "cursor": 0,
                          "menu": True, "restarts": [0], "at": 100.0})

    @mock.patch.object(data, "_answer_given", lambda *a: None)          # no gatherer's database read
    def test_the_list_waits_on_it_before_anything_was_recorded(self):
        def status(shown, status="terminal"):
            g = [{"name": "g", "agents": [], "last": None}]
            data._with_started(g, [{"session_id": "c", "gatherer": "g", "cwd": "/", "harness": "codex", "pid": 1,
                                    "created_at": "2026-11-17T00:00:00+00:00", "status": status, "kept": 0,
                                    "shown": shown}])
            a = g[0]["agents"][0]
            return a["status"], (a.get("asking") or {}).get("title")
        self.assertEqual(status({**menu(), "since": time.time() - 5}), (data.ASKING, menu()["title"]))
        self.assertEqual(status(None), (data.IDLE, None))
        self.assertEqual(status({**menu(), "since": time.time()}), (data.IDLE, None))     # not a moment yet
        self.assertEqual(status({**menu(menu=False), "since": time.time() - 5})[0], data.IDLE)   # a permission no hook
        #                                                                                 reported: only while it runs

    def test_chat_waits_on_it_with_the_message_it_holds_back(self):
        session = {"shown": {**menu(), "since": time.time() - 5}, "harness": "codex",
                   "sent": [{"cid": "c1", "text": "hi", "at": time.time() - 6}]}
        got = chat_view.unstored(session)
        self.assertEqual((got["current"]["state"], got["current"]["turn"], got["current"]["asking"]["title"], got["opening"]["text"]),
                         (chat_view.ASKING, "opening", menu()["title"], "hi"))
        got = chat_view.unstored(dict(session, shown=None))
        self.assertEqual(got["current"]["state"], chat_view.OPENING)
        got = chat_view._state(None, "c", set(), [{"n": 3}], None, [], session, [])     # a terminal opened again later
        self.assertEqual((got["state"], got["turn"]), (chat_view.ASKING, 3))


class WatchTest(SessionsBase):
    """Menus read off a terminal's screen as it starts, until its message box has had the keys READY_SECONDS."""

    def term(self, harness, screen):
        t = sessions._Term(0, -1, open(os.devnull, "w"))
        self.addCleanup(t.log.close)
        t.harness, t.gatherer, t.screen = harness, "g", screen
        return t

    def test_read_until_its_box_has_had_the_keys(self):
        t = self.term("codex", screen_of("codex-update"))
        self.s._watch_shown("sid", t)
        self.assertEqual((t.shown["title"], t.shown["menu"], t.ready), (menu()["title"], True, False))
        box = "\x1b[2J\x1b[H\x1b[?25h› \r\n\r\n  status\x1b[2A\x1b[3G"       # its composer, empty, with the keys
        t.screen.feed(box.encode())
        with mock.patch.object(sessions, "READY_SECONDS", 0.1):
            self.s._watch_shown("sid", t)
            self.assertIsNone(t.shown)
            self.assertFalse(t.ready)                            # a moment's composer: not started yet
            time.sleep(0.15)
            self.s._watch_shown("sid", t)
        self.assertTrue(t.ready)
        t.screen.feed(("\x1b[2J\x1b[H\x1b[?25l" + fixture("codex-trust").replace("\n", "\r\n")).encode())
        self.s._watch_shown("sid", t)
        self.assertIsNone(t.shown)                               # a menu once started: the reader's own

    def test_a_moment_s_composer_between_two_menus(self):
        t = self.term("codex", screen_of("codex-update"))
        self.s._watch_shown("sid", t)
        t.screen.feed("\x1b[2J\x1b[H\x1b[?25h› \r\n\r\n  status\x1b[2A\x1b[3G".encode())
        self.s._watch_shown("sid", t)
        t.screen.feed(("\x1b[2J\x1b[H\x1b[?25l" + fixture("codex-trust").replace("\n", "\r\n")).encode())
        self.s._watch_shown("sid", t)
        self.assertEqual((t.shown["title"], t.ready), ("Folder access", False))


class PickTest(SessionsBase):
    """An option picked from the page, typed into the dashboard's terminal for the session (the fake ag echoes each
    read); the menu its screen shows, stood in for (`_shown`)."""

    def typed(self):
        return [x["typed"] for x in self.logged() if "typed" in x]

    def started(self, prompt=None):
        sid = self.s.create("g", self.work, harness="codex")["session_id"]
        self.s.terminal(sid, 100, 30, prompt=prompt)
        self.until(lambda: "fake terminal" in self.s.output(sid, -1)[0].decode("utf-8", "replace"))
        return sid

    def ask(self, **extra):
        return {**data.shown_ask({**menu(), "since": time.time() - 2}, "codex"), **extra}

    def screens(self, *shown):
        seen = list(shown)
        return mock.patch.object(sessions.Sessions, "_shown", lambda *a, **k: seen.pop(0) if len(seen) > 1 else seen[0])

    def test_its_cursor_moved_seen_there_then_enter(self):
        sid = self.started()
        with self.screens(menu(), menu(cursor=1)):
            sent = self.s.answer(sid, self.ask(), {"pick": 1})
            self.assertEqual((sent["call"], sent["summary"]), (self.ask()["id"], "Skip"))
            self.until(lambda: self.typed() == [DOWN, ENTER])
        self.assertFalse(self.s.terms[sid].restart)

    def test_no_enter_where_its_cursor_is_not_on_it(self):
        sid = self.started()
        with self.screens(menu(), menu(cursor=0)), mock.patch.object(sessions, "DENY_SECONDS", 0.3):
            self.s.answer(sid, self.ask(), {"pick": 2})
            self.until(lambda: len(self.typed()) == 2)
            time.sleep(0.8)
            self.assertEqual(self.typed(), [DOWN, DOWN])

    def test_refused(self):
        sid = self.started()
        with self.screens(None):
            with self.assertRaisesRegex(sessions.SessionError, "no longer shows"):
                self.s.answer(sid, self.ask(), {"pick": 1})
        with self.screens(dict(menu(), title="Folder access")):
            with self.assertRaisesRegex(sessions.SessionError, "no longer shows"):
                self.s.answer(sid, self.ask(), {"pick": 1})
        with self.screens(menu()):
            with self.assertRaises(AnswerError):
                self.s.answer(sid, self.ask(), {"pick": 7})
            self.s.terms[sid].typed = time.time()
            with self.assertRaisesRegex(sessions.SessionError, "typed into its terminal"):
                self.s.answer(sid, self.ask(), {"pick": 1})
        with self.assertRaisesRegex(sessions.SessionError, "does not run"):
            self.s.answer("nope", self.ask(), {"pick": 1})
        self.assertEqual(self.typed(), [])

    def test_an_update_that_ends_it_has_it_started_again_with_its_message(self):
        sid = self.started(prompt="fix the tests")
        first = [x["argv"] for x in self.logged() if "argv" in x]
        self.assertEqual(first[0][-2:], ["--", "fix the tests"])
        with self.screens(menu(), menu()):
            self.s.answer(sid, self.ask(at=time.time()), {"pick": 0})
            self.until(lambda: self.typed() == [ENTER])
        t = self.s.terms[sid]
        self.assertTrue(t.restart)
        self.s._write(t, b"\x04")                                # it ends, as codex does once its update ran
        self.until(lambda: len([x for x in self.logged() if "argv" in x]) == 2)
        again = [x["argv"] for x in self.logged() if "argv" in x][1]
        self.assertEqual(again, first[0])                         # as it was started, its message with it
        self.until(lambda: sid in self.s.terms and self.s.terms[sid] is not t)
        self.assertEqual(self.s.terms[sid].prompt, "fix the tests")

    def test_not_started_again_after_another_end(self):
        sid = self.started(prompt="hi")
        self.s._write(self.s.terms[sid], b"\x04")
        self.until(lambda: sid not in self.s.terms)
        time.sleep(0.5)
        self.assertEqual(len([x for x in self.logged() if "argv" in x]), 1)


if __name__ == "__main__":
    unittest.main()
