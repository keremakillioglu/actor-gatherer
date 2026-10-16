"""The harness side's routing in Python (`ag/integrations/tools/ag_orchestrator/call_ag.py`): one
model call through a harness's adaptor and the server, with every way it can
fail leaving the harness's own messages, and the adaptor held to what it
declares. The adaptor and the server are stand-ins: routing never looks
inside a message."""

import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ag.integrations.tools.ag_orchestrator.adaptor import CHANNEL, AG, CWD, Adaptor  # noqa: E402
from ag.integrations.tools.ag_orchestrator.call_ag import call_ag  # noqa: E402


class Client:
    """Stands in for the server's client: records requests, gives `answer`."""

    def __init__(self, answer):
        self.answer, self.requests = answer, []

    async def request(self, op, body=None):
        self.requests.append((op, body))
        return self.answer(body) if callable(self.answer) else self.answer


def to_events(messages):
    return [{"type": "t", "id": str(i), "payload": m} for i, m in enumerate(messages)]


def to_messages(context, messages):
    return [e.get("payload", f"<{e.get('text')}>") for e in context]


class Stand(Adaptor):
    name, outputs, accepts, properties = "stand", ("t",), ("t", AG), (CHANNEL, CWD)

    def __init__(self, events=to_events, back=to_messages):
        self.events, self.back = events, back

    def to_events(self, messages):
        return self.events(messages)

    def to_messages(self, context, messages):
        return self.back(context, messages)


def run(client, messages=("a", "b"), events=to_events, back=to_messages, properties=None):
    return asyncio.run(call_ag(client, "s", {CHANNEL: "c"} if properties is None else properties, "/w",
                               list(messages), Stand(events, back)))


class RouteTest(unittest.TestCase):
    def test_messages_to_events_to_the_server_and_back(self):
        client = Client(lambda body: {"context": [{"type": "ag", "text": "note"}] + body["events"], "note": "ok"})
        out, note = run(client)
        self.assertEqual((out, note), (["<note>", "a", "b"], "ok"))
        self.assertEqual(client.requests, [("rewrite", {"gatherer": "s", "properties": {"channel": "c", "cwd": "/w"}, "cwd": "/w",
                                                        "events": to_events(["a", "b"])})])

    def test_every_failure_leaves_the_harness_s_own_messages(self):
        def broken(*_):
            raise ValueError("no")
        cases = [
            (Client({"error": "server exited (1)"}), to_events, to_messages, "server: server exited (1)"),
            (Client({"context": None, "note": "insert failed"}), to_events, to_messages, "insert failed"),
            (Client("garbage"), to_events, to_messages, "server: 'garbage'"),
            (Client({"context": []}), broken, to_messages, "could not make events"),
            (Client({"context": []}), to_events, broken, "could not make messages"),
        ]
        for client, events, back, why in cases:
            out, note = run(client, events=events, back=back)
            self.assertIsNone(out, why)
            self.assertIn(why, note)

    def test_a_converter_that_fails_on_the_way_in_sends_nothing(self):
        client = Client({"context": []})
        run(client, events=lambda m: 1 / 0)
        self.assertEqual(client.requests, [])

    def test_an_event_of_a_type_the_adaptor_does_not_declare_sends_nothing(self):
        client = Client({"context": []})
        out, note = run(client, events=lambda m: [{"type": "other", "id": "1", "payload": "a"}])
        self.assertIsNone(out)
        self.assertIn("does not declare (other)", note)
        self.assertEqual(client.requests, [])

    def test_a_property_the_adaptor_does_not_declare_sends_nothing(self):
        client = Client({"context": []})
        out, note = run(client, properties={CHANNEL: "c", "user": "u"})
        self.assertIsNone(out)
        self.assertIn("does not declare the properties user", note)
        self.assertEqual(client.requests, [])

    def test_a_context_entry_the_adaptor_does_not_accept_is_noted(self):
        client = Client({"context": [{"type": "environment_update", "payload": "x"}, {"type": "t", "payload": "a"}],
                         "note": "ok"})
        out, note = run(client)
        self.assertEqual(out, ["x", "a"])
        self.assertIn("does not accept environment_update", note)


if __name__ == "__main__":
    unittest.main()
