"""A hang-up while ag reads for a call (Esc as the read waits for its build): the hook (proxy_hook.py's `hung_up`, every
harness's) tells ag which session's read to stop -- the call's, as the hook kept it on the request."""

import os
import sys
import unittest
from types import SimpleNamespace

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from ag.integrations.tools.ag_orchestrator.ag_clients import AgClients  # noqa: E402
from ag.integrations.tools.ag_orchestrator.proxy_hook import ProxyHook  # noqa: E402


class Client:
    def __init__(self, gatherer, asked, answer):
        self.gatherer, self.asked, self.answer = gatherer, asked, answer

    async def request(self, op, body=None):
        self.asked.append((self.gatherer, op, body))
        return self.answer


class HungUpTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.asked, self.logged = [], []
        self.hook = ProxyHook(AgClients(lambda g: Client(g, self.asked, {"stopped": True})),
                              lambda g, line: self.logged.append((g, line)), sessions=None)

    async def test_nothing_is_asked_for_a_call_of_no_session_known(self):
        await self.hook.hung_up(SimpleNamespace(state={}))
        await self.hook.hung_up(SimpleNamespace())
        self.assertEqual(self.asked, [])

    async def test_the_session_the_call_was_followed_for(self):
        request = SimpleNamespace(state={})
        self.hook.following(request, "g", "c1", None)
        await self.hook.hung_up(request)
        await self.hook.hung_up(request)                     # told again: logged once
        self.assertEqual(self.asked, [("g", "hung_up", {"gatherer": "g", "properties": {"channel": "c1"}})] * 2)
        self.assertEqual(len(self.logged), 1)

    async def test_the_session_its_answer_is_kept_for_comes_first(self):
        request = SimpleNamespace(state={ProxyHook.SESSION: ("g", "parent"), ProxyHook.ANSWERED: ("g", "c2", "/w")})
        await self.hook.hung_up(request)
        self.assertEqual(self.asked, [("g", "hung_up", {"gatherer": "g", "properties": {"channel": "c2"}})])


if __name__ == "__main__":
    unittest.main()
