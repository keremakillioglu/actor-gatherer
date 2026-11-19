"""A hook's events sent through its outbox (ag/integrations/tools/ag_orchestrator/records.py's `Outbox`): in the order
sent, per channel and lane; an insert that fails in a way that may pass (the database locked past the server's wait,
the server starting again) kept and sent again -- the channel's later events behind it -- never lost to it, and no
caller waits on that; one that would fail again lost at once, holding nothing up."""
import asyncio
import os
import sys
import unittest
import unittest.mock
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ag.integrations.tools.ag_orchestrator import records  # noqa: E402
from ag.integrations.tools.ag_orchestrator.records import Outbox  # noqa: E402

LOCKED = "OperationalError: database is locked"


class Server:
    """The gatherer's server: each event stored once by its id, in the order inserts come; `errors`, the answers of
    the next inserts that fail (each taken once), as long as it has some."""

    def __init__(self):
        self.stored, self.ids, self.errors, self.tries = [], set(), [], 0

    def client(self, gatherer):
        return self

    async def request(self, op, body=None, timeout=None):
        self.tries += 1
        await asyncio.sleep(0)
        if self.errors:
            return {"error": self.errors.pop(0)}
        for e in body["events"]:
            if e["id"] not in self.ids:
                self.ids.add(e["id"])
                self.stored.append((body["properties"]["channel"], body.get("lane"), e["id"]))
        return {"rows": [1] * len(body["events"])}

    def ids_of(self, channel="c", lane=None):
        return [i for ch, ln, i in self.stored if ch == channel and ln == lane]


def ev(i):
    return {"type": "reply_part", "id": f"e{i}", "payload": {}}


class OutboxTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.server, self.logged = Server(), []
        self.outbox = Outbox(self.server, lambda g, line: self.logged.append(line))
        patched = unittest.mock.patch.multiple(records, RETRY_SECONDS=0.01, GIVE_UP_SECONDS=5.0)
        patched.start()
        self.addCleanup(patched.stop)

    async def asyncTearDown(self):
        await self.outbox.close()

    async def until(self, check, seconds=2.0):
        for _ in range(int(seconds / 0.01)):
            if check():
                return
            await asyncio.sleep(0.01)
        self.fail(f"not in time: {self.server.stored}")

    async def test_stored_at_once_it_answers_as_the_server_does(self):
        got = await self.outbox.record("g", "c", [ev(1)])
        self.assertEqual(got, {"rows": [1]})
        self.assertEqual(self.server.ids_of(), ["e1"])

    async def test_a_locked_database_its_events_sent_again_and_the_later_ones_after_them(self):
        self.server.errors = [LOCKED, LOCKED]
        self.assertIsNone(await self.outbox.record("g", "c", [ev(1)]))      # failed: the caller does not wait
        self.assertIsNone(await self.outbox.record("g", "c", [ev(2)]))      # behind it, not before it
        await self.until(lambda: self.server.ids_of() == ["e1", "e2"])
        self.assertTrue(any("recorded 2 events" in line for line in self.logged), self.logged)
        self.assertEqual(await self.outbox.record("g", "c", [ev(3)]), {"rows": [1]})   # sent at once again
        self.assertEqual(self.server.ids_of(), ["e1", "e2", "e3"])

    async def test_another_channel_or_lane_does_not_wait_behind_it(self):
        self.server.errors = [LOCKED]
        await self.outbox.record("g", "c", [ev(1)])
        self.assertIsNotNone(await self.outbox.record("g", "other", [ev(2)]))
        self.assertIsNotNone(await self.outbox.record("g", "c", [ev(3)], beside=True))
        self.assertEqual(self.server.ids_of("other") + self.server.ids_of("c", records.RECORDS_LANE), ["e2", "e3"])
        await self.until(lambda: self.server.ids_of() == ["e1"])

    async def test_a_request_refused_is_not_sent_again_nor_holds_up_the_rest(self):
        self.server.errors = ["no events"]
        self.assertIsNone(await self.outbox.record("g", "c", [ev(1)]))
        self.assertEqual(await self.outbox.record("g", "c", [ev(2)]), {"rows": [1]})
        await asyncio.sleep(0.05)
        self.assertEqual((self.server.ids_of(), self.server.tries), (["e2"], 2))
        self.assertTrue(any("not recorded: no events" in line for line in self.logged), self.logged)

    async def test_the_server_gone_a_while_its_events_come_once_it_is_back(self):
        self.server.errors = ["server gone: [Errno 32] Broken pipe", "server exited (1); see x.log", "no answer in 300 s"]
        await self.outbox.record("g", "c", [ev(1)])
        await self.until(lambda: self.server.ids_of() == ["e1"])

    async def test_failing_past_give_up_what_waits_is_dropped_and_said(self):
        self.server.errors = [LOCKED] * 10 ** 6
        with unittest.mock.patch.object(records, "GIVE_UP_SECONDS", 0.05):
            await self.outbox.record("g", "c", [ev(1)])
            await self.outbox.record("g", "c", [ev(2)])
            await self.until(lambda: any("dropped" in line for line in self.logged))
        self.assertIn("2 events (reply_part) not recorded", [line for line in self.logged if "dropped" in line][0])
        self.server.errors = []
        self.assertIsNotNone(await self.outbox.record("g", "c", [ev(3)]))   # the channel goes on
        self.assertEqual(self.server.ids_of(), ["e3"])

    async def test_in_flight_as_the_one_before_fails_it_stays_after_it(self):
        self.server.errors = [LOCKED]
        first = asyncio.ensure_future(self.outbox.record("g", "c", [ev(1)]))
        second = asyncio.ensure_future(self.outbox.record("g", "c", [ev(2)]))    # waits its turn behind the first
        self.assertEqual(await asyncio.gather(first, second), [None, None])
        await self.until(lambda: self.server.ids_of() == ["e1", "e2"])


class HookTest(unittest.IsolatedAsyncioTestCase):
    """Claude Code's hook: a turn's answer recorded as the database is locked -- its parts and its end, what tells a
    reader the turn is over -- stored once it is free, and before the next call."""

    class Server:
        """The context manager's server: reads answered, inserts kept in order -- the next `locked` failing."""

        def __init__(self):
            self.inserted, self.ids, self.locked = [], set(), 0

        async def request(self, op, body=None, timeout=None):
            if op == "latest":
                return {"events": []}
            if op == "insert":
                if self.locked:
                    self.locked -= 1
                    return {"error": LOCKED}
                for e in body["events"]:
                    if e["id"] not in self.ids:
                        self.ids.add(e["id"])
                        self.inserted.append((body.get("lane"), e["type"]))
                return {"rows": []}
            if op == "rewrite":
                return {"context": body["events"], "note": "ok", "read_id": 1, "basis": None}
            return {}

        async def stop(self):
            pass

    async def test_a_turn_s_end_recorded_as_the_database_is_locked_is_stored_before_the_next_call(self):
        from ag.integrations.harnesses.claude.ag_orchestrator import context_manager as claude_ag
        from ag.integrations.tools.ag_orchestrator.ag_clients import AgClients
        from ag.integrations.tools.hook_server.trace import response_of
        from test_pending import sse

        server = self.Server()
        hook = claude_ag.ClaudeContextManager(ag_clients=AgClients(lambda g: server), log=lambda g, l: None,
                                              count="off", files="off")
        hook.sessions = None

        def req(messages):
            return SimpleNamespace(method="POST", path="/v1/messages", label="g", limit=None, state={}, upstream=None,
                                   headers={"X-Claude-Code-Session-Id": "s"},
                                   body={"model": "m", "tools": [{"name": "Bash"}], "messages": messages})

        first = [{"role": "user", "content": "count the rows"}]
        with unittest.mock.patch.object(records, "RETRY_SECONDS", 0.02):
            r1 = req(first)
            await hook(r1)
            server.locked = 2                                    # the database locked as the answer comes back
            await hook.answered(r1, 200, response_of(sse([{"type": "text", "text": "There are 42."}], "end_turn")))
            await hook(req(first + [{"role": "assistant", "content": [{"type": "text", "text": "There are 42."}]},
                                    {"role": "user", "content": "now the columns"}]))
            for _ in range(200):
                if [t for lane, t in server.inserted if lane is None].count("model_call") == 2:
                    break
                await asyncio.sleep(0.01)
            await hook.close()
        own = [t for lane, t in server.inserted if lane is None]      # the session's lane
        self.assertEqual(own, ["model_call", "reply_part", "reply_end", "model_call"])


if __name__ == "__main__":
    unittest.main()
