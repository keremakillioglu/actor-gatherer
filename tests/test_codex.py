"""The codex harness's policy-specific half: its items as the context
manager's events -- the type name, the id, the cost -- (`to_events.py`) and
the context back as codex's items (`to_messages.py`)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ag.integrations.harnesses.codex.adaptor import to_events as codex  # noqa: E402
from ag.integrations.harnesses.codex.adaptor import to_messages as back  # noqa: E402

USER_MESSAGE, AGENT_MESSAGE, TOOL_CALL, TOOL_OUTPUT, CONTEXT = (
    "user_message", "agent_message", "tool_call", "tool_output", "context")
AGENT_REASONING = "agent_reasoning"


def msg(role, *texts, **extra):
    kind = "output_text" if role == "assistant" else "input_text"
    return {"type": "message", "role": role,
            "content": [{"type": kind, "text": t} for t in texts], **extra}


class ClassifyTest(unittest.TestCase):
    def check(self, item, name):
        self.assertEqual(codex.classify(item), name, item)

    def test_messages_by_role(self):
        self.check(msg("user", "count to 3"), USER_MESSAGE)
        self.check(msg("assistant", "done"), AGENT_MESSAGE)
        self.check(msg("developer", "<permissions instructions>"), CONTEXT)
        self.check(msg("system", "be brief"), CONTEXT)

    def test_codex_context_in_the_users_name_is_context(self):
        for text in ("<environment_context>\n  <cwd>/x</cwd>", "<turn_aborted>\nThe user",
                     "# AGENTS.md instructions for /x\n<INSTRUCTIONS>"):
            self.check(msg("user", text), CONTEXT)
        self.check(msg("user", "<environment_context>x", "count to 3"), USER_MESSAGE)   # the user did say something
        self.check(msg("user"), CONTEXT)                                                 # nothing said at all
        self.check(msg("user", "   "), CONTEXT)

    def test_role_less_items_by_their_rule(self):
        for kind in ("function_call", "custom_tool_call", "local_shell_call",
                     "tool_search_call", "web_search_call", "image_generation_call"):
            self.check({"type": kind}, TOOL_CALL)
        for kind in ("function_call_output", "custom_tool_call_output", "tool_search_output"):
            self.check({"type": kind}, TOOL_OUTPUT)
        self.check({"type": "reasoning", "summary": []}, AGENT_REASONING)
        self.check({"type": "agent_message", "author": "a", "recipient": "b"}, AGENT_MESSAGE)
        for kind in ("compaction", "compaction_summary", "context_compaction", "compaction_trigger"):
            self.check({"type": kind}, CONTEXT)
        self.check({"type": "additional_tools", "role": "developer", "tools": []}, CONTEXT)
        self.check({"type": "additional_tools", "tools": []}, CONTEXT)

    def test_without_a_rule_it_is_context(self):
        self.check({"type": "something_new"}, CONTEXT)                    # what the adaptor declares, and no more
        self.check({"type": "something_new", "role": "robot"}, CONTEXT)
        self.check(msg("robot", "?"), CONTEXT)                            # an unknown role
        self.check({"type": "message", "content": []}, CONTEXT)           # no role
        self.check({"role": "user"}, CONTEXT)                             # no type, nothing said: harness context
        self.check({}, CONTEXT)
        self.check("not a dict", CONTEXT)

    def test_the_adaptor_emits_only_what_it_declares(self):
        from ag.integrations.harnesses.codex.adaptor.adaptor import CodexAdaptor
        items = [msg("user", "hi"), msg("developer", "rules"), {"type": "function_call", "call_id": "c", "name": "x"},
                 {"type": "function_call_output", "call_id": "c", "output": "ok"}, {"type": "something_new"},
                 msg("robot", "?"), {}]
        events = CodexAdaptor().to_events(items)
        self.assertTrue(events)
        self.assertLessEqual({e["type"] for e in events}, set(CodexAdaptor.outputs))

    def test_every_listed_item_lands_on_a_declared_type(self):
        five = set(codex.OUTPUTS)
        for kind, name in codex.CODEX_TYPES.items():
            if name is not None:
                self.assertIn(name, five, kind)
        for role, name in codex.ROLE_TYPES.items():
            self.assertIn(name, five, role)


class ItemIdTest(unittest.TestCase):
    def test_codex_id_when_there_is_one(self):
        self.assertEqual(codex.item_id({"id": "msg_1", "type": "message"}), "msg_1")

    def test_else_derived_from_content(self):
        tools = {"type": "additional_tools", "role": "developer", "tools": [{"name": "exec"}]}
        derived = codex.item_id(tools)
        self.assertTrue(derived.startswith("sha256:"))
        self.assertEqual(codex.item_id(dict(reversed(list(tools.items())))), derived)  # key order
        self.assertEqual(codex.item_id(dict(tools, id="")), codex.item_id(dict(tools, id="")))
        self.assertNotEqual(codex.item_id(dict(tools, tools=[])), derived)
        self.assertTrue(codex.item_id("x").startswith("sha256:"))
        self.assertTrue(codex.item_id({}).startswith("sha256:"))


class EventTest(unittest.TestCase):
    def test_an_item_is_an_event_of_its_type(self):
        item = {"type": "function_call", "id": "fc_1", "name": "exec_command", "arguments": "{}"}
        e = codex.event(item)
        self.assertEqual(e, {"type": TOOL_CALL, "id": "fc_1", "payload": item, "text": "exec_command({})"})
        self.assertIs(e["payload"], item)                                    # not copied, not changed

    def test_reasoning_costs_nothing(self):
        item = {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "gAAAA" * 400}
        self.assertEqual(codex.event(item)["tokens"], 0)
        self.assertNotIn("tokens", codex.event(msg("user", "hi")))          # counted by the server

    def test_to_events_in_order(self):
        items = [msg("developer", "rules"), msg("user", "q", id="u1")]
        self.assertEqual([(e["type"], e["payload"]) for e in codex.to_events(items)],
                         [(CONTEXT, items[0]), (USER_MESSAGE, items[1])])


class TextTest(unittest.TestCase):
    """What the model reads of an item: no ids, turn metadata, status or wrappers."""

    def test_a_message_is_its_words(self):
        item = {"type": "message", "role": "user", "id": "msg_1",
                "content": [{"type": "input_text", "text": "first"}, {"type": "input_image", "image_url": "x"},
                            {"type": "input_text", "text": "second"}],
                "internal_chat_message_metadata_passthrough": {"turn_id": "t1"}}
        self.assertEqual(codex.text_of(item), "first\n[image]\nsecond")
        self.assertEqual(codex.text_of({"type": "message", "role": "assistant", "phase": "commentary",
                                        "content": [{"type": "output_text", "text": "done"}]}), "done")

    def test_a_call_is_its_name_and_arguments_without_its_ids(self):
        call = {"type": "function_call", "id": "fc_1", "call_id": "call_9__thought__QUJD" * 40,
                "name": "exec_command", "arguments": '{"cmd": "ls"}', "status": "completed"}
        self.assertEqual(codex.text_of(call), 'exec_command({"cmd": "ls"})')
        self.assertEqual(codex.text_of({"type": "custom_tool_call", "name": "apply_patch", "input": "*** Begin"}),
                         "apply_patch(*** Begin)")
        self.assertEqual(codex.text_of({"type": "local_shell_call", "action": {"command": ["ls", "-la"]}}),
                         "local_shell(ls -la)")
        self.assertEqual(codex.text_of({"type": "web_search_call", "action": {"query": "q"}}), "web_search(q)")

    def test_an_output_is_its_text(self):
        self.assertEqual(codex.text_of({"type": "function_call_output", "call_id": "c", "output": "a\nb"}), "a\nb")
        self.assertEqual(codex.text_of({"type": "function_call_output", "call_id": "c",
                                        "output": {"content": "ok", "success": True}}), "ok")
        self.assertEqual(codex.text_of({"type": "custom_tool_call_output", "call_id": "c",
                                        "output": [{"type": "input_text", "text": "x"}]}), "x")

    def test_nothing_to_read_has_no_text(self):
        for item in ({"type": "reasoning", "encrypted_content": "gAAAA"},
                     {"type": "compaction", "encrypted_content": "gAAAA"}, "not an item"):
            self.assertIsNone(codex.text_of(item))
            self.assertNotIn("text", codex.event(item))


class ToMessagesTest(unittest.TestCase):
    def test_payloads_as_sent_and_ag_messages_as_developer_messages(self):
        a, b = msg("user", "q", id="u1"), msg("assistant", "a", id="a1")
        context = [{"type": "user_message", "id": "u1", "payload": a},
                   {"type": "ag", "name": "earlier", "text": "# Earlier\n..."},
                   {"type": "agent_message", "id": "a1", "payload": b}]
        self.assertEqual(back.to_messages(context),
                         [a, {"type": "message", "role": "developer",
                              "content": [{"type": "input_text", "text": "# Earlier\n..."}]}, b])

    def test_with_ag_codex_ag_role_user_ag_messages_are_marked_user_messages(self):
        a = msg("user", "q", id="u1")
        context = [{"type": "user_message", "id": "u1", "payload": a},
                   {"type": "ag", "name": "environment_update", "text": "File x changed."}]
        saved = os.environ.get("AG_CODEX_AG_ROLE")
        os.environ["AG_CODEX_AG_ROLE"] = "user"
        try:
            self.assertEqual(back.to_messages(context),
                             [a, {"type": "message", "role": "user", "content": [{"type": "input_text", "text":
                                  "<contextual_information>\nFile x changed.\n</contextual_information>"}]}])
        finally:
            if saved is None:
                os.environ.pop("AG_CODEX_AG_ROLE")
            else:
                os.environ["AG_CODEX_AG_ROLE"] = saved

    def test_the_round_trip_is_the_items(self):
        items = [msg("developer", "rules"), msg("user", "q", id="u1"), {"type": "reasoning", "summary": []}]
        self.assertEqual(back.to_messages(codex.to_events(items)), items)


if __name__ == "__main__":
    unittest.main()
