"""Events the harness took back (`_withdrawn`, the server's `withdraw`): stored for a model call it hung up on before
the answer came, and not in what it sent after. Claude Code, stopped with Esc before any of the answer, puts the
user's message back in its input box and sends the next one without it. Kept, the message stayed in every later
context; and in a session's first turn -- Claude Code's notes come after the user's words there, and the stored notes
linked up again -- the next message was taken for one stored and never sent, so the model answered the one taken
back. Withdrawn, they are in no read and not where a request picks up its history, until the harness sends one again."""
import asyncio
import os
import sqlite3
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ag.ag_harness import home as ag_home  # noqa: E402
from ag.ag_harness.server.__main__ import server_for  # noqa: E402
from ag.ag_harness.store import operations as store  # noqa: E402
from ag.ag_harness.store import paths, schema  # noqa: E402
from ag.ag_interface import Event  # noqa: E402
from ag.integrations.harnesses.claude.ag_orchestrator import context_manager as claude_ag  # noqa: E402
from ag.integrations.harnesses.codex.ag_orchestrator.ag_clients import AgClients  # noqa: E402
from ag.integrations.tools.ag_orchestrator.call_ag import HUNG_UP  # noqa: E402


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conn = sqlite3.connect(os.path.join(self.tmp.name, "g.db"))
        self.addCleanup(self.conn.close)
        schema.create(self.conn)
        store.add_event_types(self.conn, ["user_message"]) if hasattr(store, "add_event_types") else \
            self.conn.execute("INSERT INTO event_types (name, created_at) VALUES ('user_message', '')")
        self.type_id = self.conn.execute("SELECT event_type_id FROM event_types WHERE name = 'user_message'").fetchone()[0]
        self.tok = SimpleNamespace(count=lambda text: len(text.split()))

    def add(self, event_id, text, kept=None):
        return store.insert(self.conn, Event(self.type_id, {"text": text}, id=event_id, text=text), self.tok, kept=kept)

    def test_withdrawn_events_are_in_no_read_until_sent_again(self):
        a, b, c = self.add("a", "first"), self.add("b", "taken back"), self.add("c", "a note after it")
        self.assertEqual(store.withdraw(self.conn, [b, c, c, 999]), 2)        # each once; no such row: none
        self.assertEqual([r.payload["text"] for r in store.rows(self.conn)], ["first"])
        self.assertEqual([i for i, _ in store.latest(self.conn, {}, 10)], ["a"])
        kept = []
        self.assertIsNone(self.add("b", "taken back", kept))                 # sent again: stored, and kept again
        self.assertEqual(kept, [b])                                          # its row, for the caller to withdraw
        self.add("a", "first", kept)
        self.assertEqual(kept, [b])                                          # one never taken back: not
        self.assertEqual([r.payload["text"] for r in store.rows(self.conn)], ["first", "taken back"])
        self.assertEqual([i for i, _ in store.latest(self.conn, {}, 10)], ["a", "b"])
        self.assertEqual(store.withdraw(self.conn, [b]), 1)                  # and may be taken back again


def user(*texts):
    return {"role": "user", "content": [{"type": "text", "text": t} for t in texts]}


def system(*texts):
    return {"role": "system", "content": [{"type": "text", "text": t} for t in texts]}


REMINDERS = ("<system-reminder>\nAs you answer the user's questions, you can use the following context.\n</system-reminder>",
             "<system-reminder>\nAttribution for commits.\n</system-reminder>")
NOTES = system("# Environment\nYou have been invoked in the following environment.", "tool added: a", "tool added: b")


class HookTest(unittest.TestCase):
    """The Claude hook, the real context manager server behind it, on a throwaway home."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        saved = paths.TRACE_DIR, paths.AG_HOME
        paths.AG_HOME = os.path.join(self.tmp.name, "ag")
        paths.TRACE_DIR = os.path.join(paths.AG_HOME, "gatherers")
        ag_home._HOMES.clear()
        self.addCleanup(lambda: (setattr(paths, "TRACE_DIR", saved[0]), setattr(paths, "AG_HOME", saved[1]),
                                 ag_home._HOMES.clear()))
        server = server_for()

        class Local:                                                         # the server, in this process
            async def request(self, op, body=None, timeout=None):
                return server.answer(dict(body or {}, op=op, id=1))

            async def stop(self):
                pass

        self.hook = claude_ag.ClaudeContextManager(ag_clients=AgClients(lambda gatherer: Local()), log=lambda g, l: None,
                                                   count="off", files="off")

    def call(self, messages):
        """One model call: what the model is sent (its texts, in order), and the request, for `failed`."""
        req = SimpleNamespace(method="POST", path="/v1/messages", label="g", headers={"X-Claude-Code-Session-Id": "sess"},
                              body={"model": "m", "tools": [{"name": "Bash"}], "messages": messages}, state={})
        out = asyncio.run(self.hook(req))
        self.assertIsNotNone(out, "ag's context, not the request as it came")
        sent = out["messages"]
        return [b.get("text") for m in sent for b in (m["content"] if isinstance(m["content"], list) else [])
                if isinstance(b, dict) and b.get("type") == "text"], req

    def hang_up(self, req):
        asyncio.run(self.hook.failed(req, HUNG_UP, "the harness hung up before the answer was through"))

    def test_a_first_message_taken_back_is_not_answered_in_place_of_the_next(self):
        _, req = self.call([user(*REMINDERS, "Write a 900-word story."), NOTES])
        self.hang_up(req)                                                    # Esc before any of the answer
        sent, _ = self.call([user(*REMINDERS, "Reply with the single word ok"), NOTES])
        self.assertIn("Reply with the single word ok", sent)
        self.assertNotIn("Write a 900-word story.", sent)
        self.assertEqual(sum("# Environment" in (t or "") for t in sent), 1)   # its notes once, not twice

    def test_a_later_message_taken_back_is_left_out(self):
        first = [user(*REMINDERS, "What is 2+2?"), NOTES, user("4")]
        first[-1]["role"] = "assistant"
        self.call(first)
        _, req = self.call(first + [user("Now write a long essay.")])
        self.hang_up(req)
        sent, _ = self.call(first + [user("And 3+3?")])
        self.assertEqual(sent[-2:], ["4", "And 3+3?"])
        self.assertNotIn("Now write a long essay.", sent)

    def test_a_message_taken_back_twice_is_left_out(self):
        """Esc before the answer, Enter on the message Claude Code put back, Esc again: sent again, it was kept again,
        and the second hang-up withdrew nothing -- the next message was taken for it, and the model answered it."""
        first = [user(*REMINDERS, "Reply with just the word hello."), NOTES, user("hello")]
        first[-1]["role"] = "assistant"
        self.call(first)
        for _ in range(2):
            _, req = self.call(first + [user("Write a 300-word story about a lighthouse.")])
            self.hang_up(req)
        sent, _ = self.call(first + [user("Reply with just the word fresh.")])
        self.assertEqual(sent[-2:], ["hello", "Reply with just the word fresh."])
        self.assertNotIn("Write a 300-word story about a lighthouse.", sent)

    def test_a_message_claude_code_kept_and_sent_again_stays(self):
        """Esc once some of the answer came: Claude Code keeps the message, and sends it again with the next."""
        first = [user(*REMINDERS, "What is 2+2?"), NOTES]
        _, req = self.call(first)
        self.hang_up(req)
        sent, _ = self.call(first + [{"role": "assistant", "content": [{"type": "text", "text": "It is"}]},
                                     user("[Request interrupted by user]", "go on")])
        self.assertEqual(sent.count("What is 2+2?"), 1)
        self.assertIn("go on", sent)


if __name__ == "__main__":
    unittest.main()
