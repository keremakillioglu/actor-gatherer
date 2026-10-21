"""The claude harness: Claude Code's Anthropic Messages API messages as the context manager's
events and back (`ag/integrations/harnesses/claude/adaptor/`), and the hook that routes its model
calls (`ag/integrations/harnesses/claude/ag_orchestrator/context_manager.py`). Behind the hook, a fake
server client; nothing of the context manager is imported here."""

import asyncio
import json
import os
import sys
import unittest
from unittest import mock
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ag.integrations.harnesses.claude.adaptor import to_events as claude  # noqa: E402
from ag.integrations.harnesses.claude.adaptor import to_messages as back  # noqa: E402
from ag.integrations.harnesses.claude.adaptor.adaptor import ClaudeAdaptor  # noqa: E402
from ag.integrations.harnesses.claude.ag_orchestrator import context_manager as claude_ag  # noqa: E402
from ag.integrations.harnesses.codex.ag_orchestrator.ag_clients import AgClients  # noqa: E402

USER_MESSAGE, AGENT_MESSAGE, TOOL_CALL, TOOL_OUTPUT, CONTEXT, AGENT_REASONING = claude.OUTPUTS

REMINDER = {"type": "text", "text": "<system-reminder>\nAs you answer the user's questions...\n</system-reminder>"}
ENV = {"role": "system", "content": [{"type": "text", "text": "# Environment\n - Primary working directory: /w/ws\n"}]}


def first_turn(cache=True):
    ask = {"type": "text", "text": "count the rows"}
    if cache:
        ask = {**ask, "cache_control": {"type": "ephemeral"}}
    return [{"role": "user", "content": [REMINDER, ask]}, ENV]


def tool_turn():
    return [{"role": "assistant", "content": [{"type": "thinking", "thinking": "", "signature": "sig"},
                                              {"type": "text", "text": "Checking."},
                                              {"type": "tool_use", "id": "toolu_1", "name": "Bash",
                                               "input": {"command": "sqlite3 db 'select count(*) from t'"}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1",
                                          "content": [{"type": "text", "text": "42"}],
                                          "cache_control": {"type": "ephemeral"}}]}]


class EventsTest(unittest.TestCase):
    def test_each_block_is_an_event_typed_by_its_block(self):
        events = claude.to_events(first_turn() + tool_turn())
        self.assertEqual([e["type"] for e in events],
                         [CONTEXT, USER_MESSAGE, CONTEXT, AGENT_REASONING, AGENT_MESSAGE, TOOL_CALL, TOOL_OUTPUT])

    def test_the_users_request_is_the_first_calls_last_event(self):
        # Claude Code sends its environment notes after the request; the read must answer the request
        events = claude.to_events(first_turn())
        self.assertEqual([e["type"] for e in events], [CONTEXT, CONTEXT, USER_MESSAGE])
        self.assertTrue(events[1]["text"].startswith("# Environment"))
        later = claude.to_events(first_turn() + tool_turn())          # the same events, stored once
        self.assertEqual({e["id"] for e in events} - {e["id"] for e in later}, set())
        self.assertEqual(set(e["type"] for e in events) - set(claude.OUTPUTS), set())

    def test_a_string_content_is_one_text_block(self):
        events = claude.to_events([{"role": "user", "content": "hello"}])
        self.assertEqual([(e["type"], e["text"]) for e in events], [(USER_MESSAGE, "hello")])

    def test_harness_text_in_the_users_name_is_context(self):
        for text in ("<system-reminder>x</system-reminder>", "<local-command-stdout>ok</local-command-stdout>", "  "):
            self.assertEqual(claude.classify({"role": "user", "content": [{"type": "text", "text": text}]}), CONTEXT)

    def test_ids_do_not_move_with_cache_control(self):
        a = claude.to_events(first_turn(cache=True))
        b = claude.to_events(first_turn(cache=False))
        self.assertEqual([e["id"] for e in a], [e["id"] for e in b])
        self.assertNotIn("cache_control", json.dumps([e["payload"] for e in a]))

    def test_a_resent_history_is_the_same_events(self):
        once = claude.to_events(first_turn() + tool_turn())
        again = claude.to_events(first_turn(cache=False) + tool_turn() + [{"role": "assistant", "content": "done"}])
        self.assertEqual([e["id"] for e in once], [e["id"] for e in again][:len(once)])

    def test_text_is_what_the_model_reads(self):
        events = {e["type"]: e for e in claude.to_events(tool_turn())}
        self.assertEqual(events[TOOL_CALL]["text"], 'Bash({"command": "sqlite3 db \'select count(*) from t\'"})')
        self.assertEqual(events[TOOL_OUTPUT]["text"], "42")
        self.assertNotIn("text", events[AGENT_REASONING])
        self.assertEqual(events[AGENT_REASONING]["tokens"], 0)

    def test_an_error_result_says_so(self):
        e = claude.to_events([{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t",
                                                             "is_error": True, "content": "no such file"}]}])[0]
        self.assertEqual(e["text"], "error: no such file")


class MessagesTest(unittest.TestCase):
    def test_round_trip_joins_the_pieces_again(self):
        messages = first_turn(cache=False) + tool_turn()               # the notes are not last: kept in place
        events = claude.to_events(messages)
        out = back.to_messages(events)                                   # no original messages: no markers
        stripped = claude.without_cache_control(messages)
        self.assertEqual(out, stripped)

    def test_ag_messages_are_system_messages_where_the_api_takes_them(self):
        events = claude.to_events([{"role": "user", "content": "q"}])
        out = back.to_messages(events + [{"type": "ag", "name": "notice", "text": "N"}])      # last: kept
        self.assertEqual(out[-1], {"role": "system", "content": [{"type": "text", "text": "N"}]})
        out = back.to_messages([{"type": "ag", "name": "earlier", "text": "SUMMARY"}] + events)  # before a user turn
        self.assertEqual(out, [{"role": "user", "content": [{"type": "text", "text": "SUMMARY"},
                                                            {"type": "text", "text": "q"}]}])

    def test_every_system_message_is_last_or_before_an_assistant(self):
        sent = first_turn() + tool_turn() + [ENV, {"role": "user", "content": "next"}]
        ctx = [{"type": "ag", "name": "earlier", "text": "S"}] + claude.to_events(sent)
        out = back.to_messages(ctx, sent)
        for i, m in enumerate(out):
            if m["role"] == "system":
                self.assertTrue(i == len(out) - 1 or out[i + 1]["role"] == "assistant", out)
        self.assertTrue(all(out[i]["role"] != out[i + 1]["role"] for i in range(len(out) - 1)))

    def test_a_tool_result_stays_right_after_its_call(self):
        out = back.to_messages(claude.to_events(tool_turn()))
        self.assertEqual([m["role"] for m in out], ["assistant", "user"])
        self.assertEqual(out[0]["content"][-1]["type"], "tool_use")
        self.assertEqual(out[1]["content"][0]["type"], "tool_result")

    def test_claude_codes_cache_marker_comes_back_on_the_last_message(self):
        sent = first_turn(cache=False) + tool_turn()                    # tool_turn's result carries the marker
        events = claude.to_events(sent)
        out = back.to_messages([{"type": "ag", "name": "earlier", "text": "SUMMARY"}] + events, sent)
        marked = [(i, b) for i, m in enumerate(out) for b in m["content"] if "cache_control" in b]
        self.assertEqual(marked, [(len(out) - 1, {**out[-1]["content"][-1]})])
        self.assertEqual(marked[0][1]["cache_control"], {"type": "ephemeral"})
        self.assertNotIn("cache_control", json.dumps([e["payload"] for e in events]))   # stored without

    def test_a_marker_goes_back_on_the_block_it_was_on(self):
        sent = first_turn(cache=False) + tool_turn()
        sent[2] = {**sent[2], "content": [*sent[2]["content"][:2],
                                          {**sent[2]["content"][2], "cache_control": {"type": "ephemeral", "ttl": "1h"}}]}
        out = back.to_messages(claude.to_events(sent), sent)
        marked = [(m["role"], b["type"]) for m in out for b in m["content"] if "cache_control" in b]
        self.assertIn(("assistant", "tool_use"), marked)                  # where Claude Code put it
        self.assertIn(("user", "tool_result"), marked)                    # tool_turn()'s own marker

    def test_no_marker_sent_none_put_back(self):
        sent = first_turn(cache=False)
        out = back.to_messages(claude.to_events(sent), sent)
        self.assertNotIn("cache_control", json.dumps(out))

    def test_a_marker_skips_a_thinking_block(self):
        out = back.with_markers([{"role": "assistant", "content": [{"type": "text", "text": "a"},
                                                                    {"type": "thinking", "thinking": ""}]}],
                                [({"type": "text", "text": "gone"}, {"type": "ephemeral"})])
        self.assertIn("cache_control", out[0]["content"][0])
        self.assertNotIn("cache_control", out[0]["content"][1])

    def test_closing_notes_go_back_at_the_end_with_the_marker(self):
        sent = first_turn(cache=False)
        sent = [sent[0], {**sent[1], "content": [{**sent[1]["content"][0], "cache_control": {"type": "ephemeral"}}]}]
        events = claude.to_events(sent)                                  # stored: notes before the request
        self.assertEqual([e["type"] for e in events][-1], USER_MESSAGE)
        out = back.to_messages([{"type": "ag", "name": "earlier", "text": "S"}] + events, sent)
        self.assertEqual([m["role"] for m in out], ["user", "system"])
        self.assertEqual(out[0]["content"][0]["text"], "S")
        self.assertEqual(out[-1]["content"], [{**ENV["content"][0], "cache_control": {"type": "ephemeral"}}])
        self.assertNotIn("# Environment", json.dumps(out[0]))

    def test_claude_codes_notes_stay_after_the_request_in_later_calls(self):
        # call 1 stores the notes before the request; on call 2 Claude Code has them after it, before
        # the assistant's turn -- and so must the context, not inside the user's turn
        call1 = first_turn(cache=False)
        call2 = call1 + tool_turn()
        events = claude.to_events(call1) + claude.to_events(call2)[3:]    # as stored: notes first
        self.assertEqual(events[1]["text"][:13], "# Environment")
        out = back.to_messages([{"type": "ag", "name": "earlier", "text": "S"}] + events, call2)
        self.assertEqual([m["role"] for m in out], ["user", "system", "assistant", "user"])
        self.assertEqual(out[1]["content"][0]["text"], ENV["content"][0]["text"])
        self.assertNotIn("# Environment", json.dumps(out[0]))
        call2 = [call2[0], {**ENV, "output_config": {"effort": "medium"}}] + call2[2:]   # its effort, kept
        out = back.to_messages(events, call2)
        self.assertEqual(out[1]["output_config"], {"effort": "medium"})

    def test_a_messages_own_fields_are_not_stored(self):
        env = {**ENV, "output_config": {"effort": "medium"}}
        events = claude.to_events([{"role": "user", "content": "q"}, env])
        self.assertNotIn("output_config", json.dumps([e["payload"] for e in events]))
        self.assertEqual(events[0]["id"], claude.to_events([{"role": "user", "content": "q"}, ENV])[0]["id"])

    def test_a_messages_fields_go_back_where_claude_code_sent_them(self):
        # Claude Code's first call: [request, system notes carrying output_config]. The notes are stored
        # before the request, and go back after it with their field, as sent
        sent = [{"role": "user", "content": [REMINDER, {"type": "text", "text": "q"}]},
                {**ENV, "output_config": {"effort": "medium"}}]
        out = back.to_messages(claude.to_events(sent), sent)
        self.assertEqual([m["role"] for m in out], ["user", "system"])      # the notes back at the end, as sent
        self.assertEqual(out[-1]["output_config"], {"effort": "medium"})   # and the request's fields with them
        self.assertEqual(sum("output_config" in m for m in out), 1)
        later = sent + [{"role": "assistant", "content": "a"}, {**ENV, "content": [{"type": "text", "text": "n2"}],
                                                                "output_config": {"effort": "low"}}]
        out = back.to_messages(claude.to_events(later), later)
        self.assertEqual([m["role"] for m in out], [m["role"] for m in later])
        self.assertEqual([m.get("output_config") for m in out], [m.get("output_config") for m in later])

    def test_the_adaptor_declares_what_it_makes(self):
        a = ClaudeAdaptor()
        self.assertEqual(a.name, "claude")
        self.assertEqual(set(a.accepts), set(claude.OUTPUTS) | {"ag"})


class HookDecisionsTest(unittest.TestCase):
    def test_the_agents_turns_are_model_calls(self):
        body = {"messages": first_turn(), "tools": [{"name": "Bash"}]}
        self.assertTrue(claude_ag.is_model_call("POST", "/v1/messages?beta=true", body))
        self.assertFalse(claude_ag.is_model_call("POST", "/v1/messages", {**body, "tools": []}))   # a side call
        self.assertFalse(claude_ag.is_model_call("GET", "/v1/messages", body))
        self.assertFalse(claude_ag.is_model_call("POST", "/v1/models", body))
        self.assertFalse(claude_ag.is_model_call("POST", "/v1/messages", {"messages": [ENV], "tools": [{}]}))

    def test_the_session_from_the_header_then_the_metadata(self):
        meta = {"metadata": {"user_id": json.dumps({"device_id": "d", "session_id": "s-meta"})}}
        self.assertEqual(claude_ag.session_of({"X-Claude-Code-Session-Id": "s-hdr"}, meta), "s-hdr")
        self.assertEqual(claude_ag.session_of({}, meta), "s-meta")
        self.assertIsNone(claude_ag.session_of({}, {"metadata": {"user_id": "not json"}}))
        self.assertIsNone(claude_ag.session_of({}, {}))

    def test_cwd_from_the_environment_notes(self):
        self.assertEqual(claude_ag.cwd_of(first_turn()), "/w/ws")
        self.assertIsNone(claude_ag.cwd_of([{"role": "user", "content": "q"}]))


class FakeClient:
    """Answers a `rewrite` with an ag message in front of the events it was sent."""

    def __init__(self):
        self.asked = []

    async def request(self, op, body=None, timeout=None):
        self.asked.append((op, body))
        return {"context": [{"type": "ag", "name": "earlier", "text": "SUMMARY"}] + body["events"], "note": "ok"}

    async def stop(self):
        pass


class HookTest(unittest.TestCase):
    def run_hook(self, request, client):
        hook = claude_ag.ClaudeContextManager(ag_clients=AgClients(lambda gatherer: client), log=lambda h, l: None)
        return asyncio.run(hook(request))

    def test_messages_are_replaced_and_the_rest_kept(self):
        client = FakeClient()
        body = {"model": "m", "system": [{"type": "text", "text": "SYS"}], "tools": [{"name": "Bash"}],
                "messages": first_turn(), "metadata": {}}
        req = SimpleNamespace(method="POST", path="/v1/messages", label="ag-x",
                              headers={"X-Claude-Code-Session-Id": "sess"}, body=body)
        out = self.run_hook(req, client)
        self.assertEqual(out["system"], body["system"])
        self.assertEqual(out["tools"], body["tools"])
        self.assertEqual(out["messages"][0]["role"], "user")             # before the request: in its turn
        self.assertEqual(out["messages"][0]["content"][0], {"type": "text", "text": "SUMMARY"})
        op, sent = client.asked[0]
        self.assertEqual((op, sent["gatherer"], sent["properties"]["channel"]), ("rewrite", "ag-x", "sess"))
        self.assertEqual(sent["cwd"], "/w/ws")

    def test_a_subagents_calls_go_through_as_they_are(self):
        client = FakeClient()
        req = SimpleNamespace(method="POST", path="/v1/messages", label="ag-x",
                              headers={"X-Claude-Code-Session-Id": "sess", "x-claude-code-agent-id": "a1"},
                              body={"messages": first_turn(), "tools": [{"name": "Bash"}]})
        self.assertIsNone(self.run_hook(req, client))
        self.assertEqual(client.asked, [])

    def test_no_session_leaves_the_request_alone(self):
        client = FakeClient()
        req = SimpleNamespace(method="POST", path="/v1/messages", label=None, headers={},
                              body={"messages": first_turn(), "tools": [{"name": "Bash"}]})
        self.assertIsNone(self.run_hook(req, client))
        self.assertEqual(client.asked, [])


class StoreClient:
    """A stand-in for the context manager's server: stores each event once by its id, in order, and
    answers a rewrite with everything stored -- as a read before any build does."""

    def __init__(self):
        self.ids, self.events = set(), []

    async def request(self, op, body=None, timeout=None):
        for e in body["events"]:
            if e["id"] not in self.ids:
                self.ids.add(e["id"])
                self.events.append(e)
        return {"context": [{"type": e["type"], "id": e["id"], "payload": e["payload"]} for e in self.events],
                "note": "ok"}

    async def stop(self):
        pass


def txt(role, text):
    return {"role": role, "content": [{"type": "text", "text": text}]}


TOOL = {"name": "mcp__demo__search", "description": "Search.", "input_schema": {"type": "object"}}
ADD = {"type": "tool_addition", "tool": {"type": "tool_definition", "definition": TOOL}}
REMOVE = {"type": "tool_removal", "tool": {"type": "tool_reference", "name": TOOL["name"]}}
NOTE = lambda text, block: {"role": "system", "content": [{"type": "text", "text": text}, block]}
ADDED = [txt("user", "What is 2+2?"), NOTE("Tools just became available: mcp__demo__search", ADD)]
REMOVED = ADDED + [txt("assistant", "4"), txt("user", "And 3+3?"),
                   NOTE("Tools are no longer available: mcp__demo__search", REMOVE)]
READDED = REMOVED + [txt("assistant", "6"), txt("user", "And 4+4?"),
                     NOTE("Tools just became available (reconnected): mcp__demo__search", ADD)]


def layout(messages):
    """Each message's role and block types: what the API's rules are about."""
    return [(m["role"], [b["type"] for b in (m["content"] if isinstance(m["content"], list) else [])])
            for m in messages]


class RepeatsTest(unittest.TestCase):
    """Issue #35: blocks Claude Code sends twice word for word are events of their own."""

    def setUp(self):
        self.client = StoreClient()
        self.hook = self.new_hook()

    def new_hook(self):
        return claude_ag.ClaudeContextManager(ag_clients=AgClients(lambda gatherer: self.client),
                                              log=lambda h, l: None)

    def call(self, messages, hook=None):
        body = {"model": "m", "tools": [{"name": "Bash"}], "messages": messages}
        req = SimpleNamespace(method="POST", path="/v1/messages", label="g",
                              headers={"X-Claude-Code-Session-Id": "sess"}, body=body)
        out = asyncio.run((hook or self.hook)(req))
        return messages if out is None else out["messages"]

    def test_a_tool_added_removed_and_added_again_goes_out_as_sent(self):
        for messages in (ADDED, REMOVED, READDED):
            self.assertEqual(layout(self.call(messages)), layout(messages))
        self.assertEqual(sum(e["payload"]["content"][0] == ADD for e in self.client.events), 2)

    def test_a_repeated_user_message_is_kept(self):
        first = [txt("user", "Write step 1."), txt("assistant", "Step 1 done."), txt("user", "continue")]
        second = first + [txt("assistant", "Step 2 done."), txt("user", "continue")]
        self.call(first)
        out = self.call(second)
        self.assertEqual([m["content"][0]["text"] for m in out],
                         ["Write step 1.", "Step 1 done.", "continue", "Step 2 done.", "continue"])

    def test_the_same_request_again_stores_nothing_new(self):
        self.call(READDED)
        stored = len(self.client.events)
        self.call(READDED)
        self.assertEqual(len(self.client.events), stored)

    def test_a_retry_without_inline_tools_gets_none_back(self):
        self.call(REMOVED)
        retry = [m if m["role"] != "system" else txt("system", m["content"][0]["text"]) for m in READDED]
        out = self.call(retry)
        self.assertFalse(any(b["type"] in ("tool_addition", "tool_removal") for _, kinds in layout(out)
                             for b in [{"type": k} for k in kinds]))

    def test_a_restarted_hook_finds_the_history_it_stored(self):
        self.call(REMOVED)
        stored = len(self.client.events)
        self.call(REMOVED, hook=self.new_hook())                 # no memory of the last request
        self.assertEqual(len(self.client.events), stored)

    def test_history_rewritten_further_back_stores_only_what_is_new(self):
        long = [txt("user" if i % 2 == 0 else "assistant", f"turn {i}") for i in range(40)]
        self.call(long)
        stored = len(self.client.events)
        compacted = [txt("user", "Summary of turns 0-19.")] + long[20:] + [txt("assistant", "ok"),
                                                                           txt("user", "next")]
        self.call(compacted)
        new = [e["payload"]["content"][0]["text"] for e in self.client.events[stored:]]
        self.assertEqual(new, ["ok", "next"])                    # the window found; nothing re-stored


def R(text):
    """A text block as the system reminder a system message's text goes out as with system_messages="user"."""
    return {"type": "text", "text": f"<system-reminder>\n{text}\n</system-reminder>"}


class GatewayTest(unittest.TestCase):
    """system_messages="user": every system message that says something goes out as user-turn system
    reminders (for a gateway that moves system messages into the model's system instruction)."""

    def back(self, context, messages=None):
        return back.to_messages(context, messages, system_messages="user")

    def test_the_default_keeps_system_messages(self):
        sent = first_turn(cache=False) + tool_turn()
        self.assertEqual(ClaudeAdaptor.system_messages, "keep")
        self.assertIn("system", [m["role"] for m in ClaudeAdaptor().to_messages(claude.to_events(sent), sent)])
        with self.assertRaises(ValueError):
            back.to_messages([], [], system_messages="maybe")

    def test_round_trip(self):
        messages = first_turn(cache=False) + tool_turn()
        out = self.back(claude.to_events(messages))
        stripped = claude.without_cache_control(messages)
        user = {"role": "user", "content": stripped[0]["content"] + [R(ENV["content"][0]["text"])]}
        self.assertEqual(out, [user] + stripped[2:])

    def test_ag_messages_are_user_turn_reminders(self):
        events = claude.to_events([{"role": "user", "content": "q"}])
        self.assertEqual(self.back(events + [{"type": "ag", "name": "notice", "text": "N"}]),
                         [{"role": "user", "content": [{"type": "text", "text": "q"}, R("N")]}])
        self.assertEqual(self.back([{"type": "ag", "name": "earlier", "text": "SUMMARY"}] + events),
                         [{"role": "user", "content": [R("SUMMARY"), {"type": "text", "text": "q"}]}])

    def test_no_system_message_that_says_something_goes_out(self):
        sent = first_turn() + tool_turn() + [ENV, {"role": "user", "content": "next"}]
        out = self.back([{"type": "ag", "name": "earlier", "text": "S"}] + claude.to_events(sent), sent)
        self.assertFalse([m for m in out if m["role"] == "system"])
        self.assertTrue(all(out[i]["role"] != out[i + 1]["role"] for i in range(len(out) - 1)))
        already = back.reminder({"type": "text", "text": "<system-reminder>\nx\n</system-reminder>"})
        self.assertEqual(already["text"].count("<system-reminder>"), 1)  # not wrapped twice

    def test_notes_stay_where_claude_code_sent_them_with_the_marker(self):
        sent = first_turn(cache=False)
        sent = [sent[0], {**sent[1], "content": [{**sent[1]["content"][0], "cache_control": {"type": "ephemeral"}}]}]
        out = self.back([{"type": "ag", "name": "earlier", "text": "S"}] + claude.to_events(sent), sent)
        self.assertEqual([m["role"] for m in out], ["user"])
        blocks = out[0]["content"]
        self.assertEqual(blocks[0], R("S"))
        self.assertEqual(blocks[-1], {**R(ENV["content"][0]["text"]), "cache_control": {"type": "ephemeral"}})
        self.assertEqual([b.get("text") for b in blocks].index("count the rows"), len(blocks) - 2)
        call2 = [sent[0], {**ENV, "output_config": {"effort": "medium"}}] + tool_turn()
        out = self.back(claude.to_events(call2), call2)
        self.assertEqual([m["role"] for m in out], ["user", "assistant", "user"])
        self.assertNotIn("output_config", json.dumps(out))               # a user message cannot carry it

    def test_what_only_a_system_message_may_hold_stays_one(self):
        added = {"role": "system", "content": [{"type": "text", "text": "The following tools just became available"},
                                               {"type": "tool_addition", "tool": {"name": "mcp__x"}}]}
        sent = first_turn(cache=False) + tool_turn() + [added]
        self.assertEqual(self.back(claude.to_events(sent), sent)[-1], added)
        directive = {"role": "system", "content": [], "output_config": {"effort": "low"}}
        later = first_turn(cache=False) + [{"role": "assistant", "content": "a"}, directive]
        out = self.back(claude.to_events(later), later)
        self.assertEqual(out[-1], directive)

    def test_the_hook_chooses_by_the_model(self):
        sent = first_turn(cache=False) + tool_turn()

        def roles(model, **opts):
            client = FakeClient()
            hook = claude_ag.ClaudeContextManager(ag_clients=AgClients(lambda gatherer: client), log=lambda h, l: None, **opts)
            body = {"model": model, "tools": [{"name": "Bash"}], "messages": sent}
            req = SimpleNamespace(method="POST", path="/v1/messages", label="h",
                                  headers={"X-Claude-Code-Session-Id": "s"}, body=body)
            return [m["role"] for m in asyncio.run(hook(req))["messages"]]
        self.assertNotIn("system", roles("gemini-3.1-pro-preview"))        # Gemini: as user-turn reminders
        self.assertNotIn("system", roles("vertex_ai/gemini-3.8-flash"))
        for model in ("claude-opus-5-5", "gpt-5.6-sol", "openai/gpt-5.6-terra"):
            self.assertIn("system", roles(model), model)                  # any other: as Claude Code sends them
        self.assertIn("system", roles("gemini-3.1-pro-preview", system_messages="keep"))   # forced
        self.assertNotIn("system", roles("claude-opus-5-5", system_messages="user"))
        with self.assertRaises(ValueError):
            claude_ag.ClaudeContextManager(ag_clients=AgClients(lambda gatherer: FakeClient()), system_messages="x")

    def test_the_launcher_passes_the_setting_only_when_set(self):
        from ag.integrations.harnesses.claude.setup import launch
        seen = []

        class Servers:
            def running(self):
                return []

            def start(self, setup, upstream, port, log_dir, options, **kw):
                seen.append(dict(options))
                return SimpleNamespace(url="http://127.0.0.1:4113")
        for setting, want in (("", None), ("keep", "keep"), ("user", "user")):
            launcher = launch.ClaudeLauncher({**launch.ClaudeLauncher.defaults, "upstream": "http://127.0.0.1:4011",
                                              "system_messages": setting}, "/tmp/home")
            launcher.servers = Servers()
            with mock.patch.object(launch, "probe", lambda *a: None):       # no Claude Code to ask
                launcher.launch(SimpleNamespace(args=[], command=["claude"], env={}, gatherer="h", adaptor="",
                                                dry_run=False))
            self.assertEqual(seen[-1].get("system_messages"), want, setting)


class TraceAnswerTest(unittest.TestCase):
    """The hook server's model trace reads an Anthropic Messages API answer, streamed or not."""

    def sse(self, *events):
        return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()

    def test_a_stream_is_put_together(self):
        from ag.integrations.tools.hook_server.trace import response_of
        raw = self.sse(
            {"type": "message_start", "message": {"id": "msg_1", "usage": {
                "input_tokens": 10, "cache_read_input_tokens": 100, "cache_creation_input_tokens": 5, "output_tokens": 1}}},
            {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": ""}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "hm"}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "s"}},
            {"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "Run"}},
            {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "ning."}},
            {"type": "content_block_start", "index": 2, "content_block": {"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}},
            {"type": "content_block_delta", "index": 2, "delta": {"type": "input_json_delta", "partial_json": '{"command": '}},
            {"type": "content_block_delta", "index": 2, "delta": {"type": "input_json_delta", "partial_json": '"ls"}'}},
            {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 42}},
            {"type": "message_stop"})
        r = response_of(raw)
        self.assertEqual((r["response_id"], r["status"]), ("msg_1", "tool_use"))
        self.assertEqual(r["output_items"], [{"type": "thinking", "thinking": "hm", "signature": "s"},
                                             {"type": "text", "text": "Running."},
                                             {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}])
        self.assertEqual(r["token_usage"], {"input_tokens": 115, "cached_input_tokens": 100, "cache_write_input_tokens": 5,
                                            "output_tokens": 42, "reasoning_output_tokens": 0, "total_tokens": 157})

    def test_a_json_answer_and_an_error(self):
        from ag.integrations.tools.hook_server.trace import response_of
        body = {"type": "message", "id": "msg_2", "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "7"}], "usage": {"input_tokens": 3, "output_tokens": 1}}
        r = response_of(json.dumps(body).encode())
        self.assertEqual((r["response_id"], r["output_items"], r["token_usage"]["total_tokens"]),
                         ("msg_2", [{"type": "text", "text": "7"}], 4))
        err = response_of(json.dumps({"type": "error", "error": {"type": "invalid_request_error", "message": "x"}}).encode())
        self.assertEqual(err["error"]["type"], "invalid_request_error")


class LauncherTraceTest(unittest.TestCase):
    def test_trace_root_is_handed_to_the_hook_server_with_claude_codes_session_header(self):
        from ag.integrations.harnesses.claude.setup import launch
        seen = {}

        class Servers:
            def running(self):
                return []

            def start(self, *args, **kwargs):
                seen.update(args=args, kwargs=kwargs)
                return SimpleNamespace(url="http://127.0.0.1:4113")
        launcher = launch.ClaudeLauncher({**launch.ClaudeLauncher.defaults, "trace_root": "/tmp/tr",
                                          "upstream": "https://api.anthropic.com"}, "/tmp/home")
        launcher.servers = Servers()
        run = SimpleNamespace(args=["-p", "hi"], command=["claude"], env={}, gatherer="h", adaptor="", dry_run=False)
        with mock.patch.object(launch, "probe", lambda *a: None):           # no Claude Code to ask
            out = launcher.launch(run)
        self.assertEqual(seen["kwargs"]["trace_root"], "/tmp/tr")
        self.assertEqual(seen["kwargs"]["thread_headers"], ("x-claude-code-session-id",))
        self.assertIn("model trace: /tmp/tr", out.notes)


if __name__ == "__main__":
    unittest.main()
