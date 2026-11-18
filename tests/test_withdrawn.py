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
import time
import unittest
import unittest.mock
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
from ag.integrations.tools.ag_orchestrator.proxy_hook import process_ended  # noqa: E402


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
        server = self.server = server_for()

        class Local:                                                         # the server, in this process
            async def request(self, op, body=None, timeout=None):
                return server.answer(dict(body or {}, op=op, id=1))

            async def stop(self):
                pass

        self.hook = claude_ag.ClaudeContextManager(ag_clients=AgClients(lambda gatherer: Local()), log=lambda g, l: None,
                                                   count="off", files="off")

    def send(self, messages):
        """One model call: the messages the model is sent, and the request, for `failed`."""
        req = SimpleNamespace(method="POST", path="/v1/messages", label="g", headers={"X-Claude-Code-Session-Id": "sess"},
                              body={"model": "m", "tools": [{"name": "Bash"}], "messages": messages}, state={})
        out = asyncio.run(self.hook(req))
        self.assertIsNotNone(out, "ag's context, not the request as it came")
        return out["messages"], req

    def call(self, messages):
        """One model call: what the model is sent (its texts, in order), and the request, for `failed`."""
        sent, req = self.send(messages)
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

    def test_a_hang_up_withdraws_before_it_is_recorded(self):
        """What the call stored is withdrawn before the hang-up is recorded: a reader that finds the hang-up finds what
        it took back with it (the dashboard tells a message taken back from a turn stopped by the two together)."""
        _, req = self.call([user(*REMINDERS, "Write a 900-word story.")])
        order, recorded = [], []

        async def withdraw(*a):
            order.append("withdrawn")
            return True

        async def record(gatherer, channel, events):
            order.append("recorded")
            recorded.extend(events)
        with unittest.mock.patch.object(claude_ag, "report_withdrawn", side_effect=withdraw), \
                unittest.mock.patch.object(self.hook, "recorded", side_effect=record):
            self.hang_up(req)
        self.assertEqual(order, ["withdrawn", "recorded"])
        self.assertEqual([(e["type"], e["payload"].get("withdrawn")) for e in recorded], [("call_failed", True)])

    def test_a_hang_up_as_claude_code_ends_withdraws_nothing(self):
        """Its terminal closed mid-call: Claude Code drops the call once its process is gone, and keeps the message in
        its record -- a resumed session shows it and sends it with its next call. Nothing withdrawn, and the hang-up
        says so; the next call carries the message once."""
        first = [user(*REMINDERS, "Write a 900-word story."), NOTES]
        _, req = self.call(first)
        done = os.fork()
        if done == 0:
            os._exit(129)
        os.waitpid(done, 0)                                                  # gone: as a closed terminal's process
        req.run = str(done)
        recorded = []
        withdraw = unittest.mock.AsyncMock(return_value=True)

        async def record(gatherer, channel, events):
            recorded.extend(events)
        with unittest.mock.patch.object(claude_ag, "report_withdrawn", withdraw), \
                unittest.mock.patch.object(self.hook, "recorded", side_effect=record):
            self.hang_up(req)
        withdraw.assert_not_called()
        self.assertEqual([(e["type"], e["payload"].get("withdrawn")) for e in recorded], [("call_failed", False)])
        sent, _ = self.call(first + [user("go on")])                         # resumed: the message, then the next
        self.assertEqual(sent.count("Write a 900-word story."), 1)
        self.assertIn("go on", sent)

    def test_a_hang_up_while_claude_code_runs_withdraws(self):
        """Esc: Claude Code drops the call and goes on running -- its run names a process that runs."""
        _, req = self.call([user(*REMINDERS, "Write a 900-word story.")])
        req.run = str(os.getpid())
        withdraw = unittest.mock.AsyncMock(return_value=True)
        with unittest.mock.patch.object(claude_ag, "report_withdrawn", withdraw):
            self.hang_up(req)
        withdraw.assert_called_once()

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

    def test_a_tool_s_result_withdrawn_then_sent_again_changed_still_comes_right_after_its_call(self):
        """The computer slept as the call after a tool's result was answered: the hang-up withdrew the result (the
        call's newest user row), not its tool call. Resumed, Claude Code sent the result again with a note of its own
        appended inside it, so it was stored as a new row -- after a stream message that came in meanwhile. Sorted by
        row, the message went between the tool call and its result, became user text ahead of the result, and the
        API refused every call: "`tool_use` ids were found without `tool_result` blocks immediately after"."""
        tool_use = {"role": "assistant", "content": [{"type": "tool_use", "id": "toolu_1", "name": "Bash",
                                                      "input": {"command": "grep -n INSERT sessions.py"}}]}

        def result(text, *after):
            return {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": text}]
                    + [{"type": "text", "text": t} for t in after]}

        first = [user(*REMINDERS, "Find every insert into sessions."), NOTES]
        self.call(first)
        _, req = self.call(first + [tool_use, result("sessions.py:844: INSERT INTO sessions")])
        self.hang_up(req)                                                    # asleep while the answer came
        stored = self.server.answer({"op": "insert", "id": 1, "gatherer": "g", "properties": {"channel": "sess"},
                                     "events": [{"type": "context_stream", "payload": {
                                         "stream": "Browser", "author": "the user", "timestamp": 1794967308,
                                         "text": "the page went to http://127.0.0.1:4918/"}}]})
        self.assertTrue(stored["rows"][0])
        again = result("sessions.py:844: INSERT INTO sessions\n\n<system-reminder>\nInstruction files were re-read "
                       "when this session started.\n</system-reminder>", "Continue")
        sent, _ = self.send(first + [tool_use, again])
        at = next(i for i, m in enumerate(sent) if m["role"] == "assistant"
                  and any(b.get("type") == "tool_use" for b in m["content"]))
        after = sent[at + 1]
        self.assertEqual((after["role"], after["content"][0].get("type"), after["content"][0].get("tool_use_id")),
                         ("user", "tool_result", "toolu_1"))
        self.assertEqual(sum(b.get("type") == "tool_result" for m in sent for b in m["content"]), 1)
        texts = [b.get("text") or "" for m in sent[at + 1:] for b in m["content"] if b.get("type") == "text"]
        shown = [i for i, t in enumerate(texts) if "the page went to http://127.0.0.1:4918/" in t]
        self.assertEqual(len(shown), 1)                                      # still shown, once: after the result
        self.assertLess(shown[0], texts.index("Continue"))                   # and before the user's next words


class EndedTest(unittest.TestCase):
    """process_ended: whether a harness's process has ended -- the hook's tell of a terminal closed from an Esc."""

    def test_a_process_running_exited_and_gone(self):
        self.assertIs(process_ended(os.getpid()), False)              # this one runs
        child = os.fork()
        if child == 0:
            os._exit(0)
        try:
            for _ in range(200):                                      # exited, not reaped: a zombie
                if process_ended(child):
                    break
                time.sleep(0.01)
            self.assertIs(process_ended(child), True)
        finally:
            os.waitpid(child, 0)
        self.assertIs(process_ended(child), True)                     # reaped: gone
        self.assertIsNone(process_ended("not a pid"))
        self.assertIsNone(process_ended(0))


if __name__ == "__main__":
    unittest.main()
