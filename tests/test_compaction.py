"""Claude Code compacting its own history becomes a build in the gatherer. Its compaction call (the
conversation, the instruction to summarize it at the end of its last user message) is not a turn:
the hook asks the server for `compaction` -- the events inserted, a `compaction` build started and
waited for, the context answered read only -- and sends that with the instruction after it. The
build closes the running task, as one over the limit does, and is adopted at the next read whatever
its size; the summary Claude Code goes on from is not stored."""
import asyncio
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ag.ag_harness import Manager  # noqa: E402
from ag.ag_harness.store import operations as store  # noqa: E402
from ag.ag_harness.store import paths  # noqa: E402
from ag.ag_policies.proactive_context_manager import ProactiveContextManager, ProactiveContextManagerConfig  # noqa: E402
from ag.ag_policies.proactive_context_manager import tables  # noqa: E402
from ag.integrations.harnesses.claude.adaptor import to_events as claude  # noqa: E402
from ag.integrations.harnesses.claude.ag_orchestrator import context_manager as claude_ag  # noqa: E402
from ag.integrations.harnesses.codex.ag_orchestrator.ag_clients import AgClients  # noqa: E402
from channels import ch  # noqa: E402
from test_core import PREAMBLE, Recording, ScriptedLLM, conversation, user  # noqa: E402
import codex_items  # noqa: E402

INSTRUCTION = {"type": "text", "text": "CRITICAL: Respond with TEXT ONLY. Do NOT call any tools.\n\n"
                                       "- Do NOT use Read, Bash, Grep, Glob, Edit, Write, or ANY other tool.\n..."}
SUMMARY = ("This session is being continued from a previous conversation that ran out of context. The summary "
           "below covers the earlier portion of the conversation.\n\nSummary: the user asked about salaries.")


class PolicyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = paths.TRACE_DIR
        paths.TRACE_DIR = os.path.join(self.tmp.name, "traces")
        cfg = ProactiveContextManagerConfig(min_context_tokens=0, require_smaller=True, sync_seconds=0, build_timeout=5)
        self.policy = ProactiveContextManager(codex_items.FORMAT, ScriptedLLM(), cfg)
        self.spawned = []

        def run(gatherer, channel_id, job, job_id):          # the worker's job, here and now
            self.spawned.append(job)
            if job == "build":
                self.policy.build(gatherer, ch(channel_id), job_id)
        self.policy.jobs = Recording(run)
        self.m = Manager(self.policy)
        self.m.init("s")
        self.items = codex_items.CodexItems(self.m)

    def tearDown(self):
        paths.TRACE_DIR = self.saved
        self.tmp.cleanup()

    def put(self, items):
        for item in items:
            self.items.insert("s", item, channel_id="c1")

    def test_a_compaction_builds_and_waits_for_it(self):
        self.put(PREAMBLE + conversation(6))
        row = store.high_water(self.m._conn("s"))
        self.assertEqual(self.m.compacted("s", row, properties=ch("c1")), "ready")
        build = tables.latest_build(self.m._conn("s"), "c1")
        self.assertEqual((build["reason"], build["status"]), (tables.COMPACTION, "ready"))
        self.assertEqual(self.spawned, ["build"])

    def test_its_build_is_adopted_whatever_its_size(self):
        self.put(PREAMBLE + conversation(6))
        self.m.compacted("s", store.high_water(self.m._conn("s")), properties=ch("c1"))
        self.put([user("which country was highest?", 20)])       # the user's next words, after the compaction
        ctx, _ = self.m._context("s", store.high_water(self.m._conn("s")), ch("c1"))
        self.assertIsNotNone(ctx.basis)                          # adopted: require_smaller does not refuse it
        build = tables.latest_build(self.m._conn("s"), "c1")
        self.assertEqual(build["status"], "ready")
        self.assertEqual(str(build["build_id"]), ctx.basis)

    def test_without_background_work_nothing_is_built(self):
        self.policy.jobs = None
        self.put(PREAMBLE + conversation(2))
        self.assertEqual(self.m.compacted("s", store.high_water(self.m._conn("s")), properties=ch("c1")), "")


class Server:
    def __init__(self):
        self.asked = []

    async def request(self, op, body=None, timeout=None):
        self.asked.append((op, body))
        if op in ("rewrite", "context", "compaction"):
            return {"context": body["events"], "note": "ok", **({"read_id": len(self.asked)} if op == "rewrite" else {}),
                    "basis": None}
        return {}

    async def stop(self):
        pass


def conversation_so_far():
    return [{"role": "user", "content": "count the rows"},
            {"role": "assistant", "content": [{"type": "text", "text": "There are 42 rows."}]},
            {"role": "user", "content": [{"type": "text", "text": "and the columns?"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "Three."}]}]


class HookTest(unittest.TestCase):
    def call(self, hook, messages):
        req = SimpleNamespace(method="POST", path="/v1/messages", label="g", limit=None, state={}, upstream=None,
                              headers={"X-Claude-Code-Session-Id": "s"},
                              body={"model": "m", "tools": [{"name": "Bash"}], "messages": messages})
        return asyncio.run(hook(req))

    def hook(self, server):
        return claude_ag.ClaudeContextManager(ag_clients=AgClients(lambda g: server), log=lambda g, l: None)

    def test_the_compaction_call_asks_the_gatherer_to_build(self):
        server = Server()
        last = {"role": "user", "content": [{"type": "text", "text": "thanks, that's all"}, INSTRUCTION]}
        messages = conversation_so_far() + [last]
        out = self.call(self.hook(server), messages)
        self.assertEqual([op for op, _ in server.asked], ["compaction"])          # no rewrite, no read
        events = server.asked[0][1]["events"]
        self.assertFalse(any("CRITICAL: Respond" in json.dumps(e) for e in events))   # the instruction not stored
        self.assertTrue(any("thanks, that's all" in json.dumps(e) for e in events))  # the user's words are
        self.assertEqual(out["messages"][-1]["content"][-1], INSTRUCTION)           # the instruction, after it all
        self.assertEqual(out["messages"][-1]["content"][0]["text"], "thanks, that's all")

    def test_the_split(self):
        last = {"role": "user", "content": [{"type": "text", "text": "thanks"}, INSTRUCTION]}
        history, instruction = claude_ag.compaction_split(conversation_so_far() + [last])
        self.assertEqual(instruction, [INSTRUCTION])
        self.assertEqual(history[-1], {"role": "user", "content": [{"type": "text", "text": "thanks"}]})
        alone = {"role": "user", "content": [INSTRUCTION]}
        self.assertEqual(claude_ag.compaction_split(conversation_so_far() + [alone])[0], conversation_so_far())
        note = {"role": "system", "content": [{"type": "text", "text": "hook note"}]}
        self.assertIsNotNone(claude_ag.compaction_split(conversation_so_far() + [last, note]))
        self.assertIsNone(claude_ag.compaction_split(conversation_so_far()))

    def test_what_claude_code_sends_with_a_compacted_history_is_not_stored(self):
        # the layout of Claude Code 2.1.308's first call after /compact (saved from a live session)
        reminder = {"type": "text", "text": "<system-reminder>\nCodebase and user instructions ...\n</system-reminder>"}
        tool = {"type": "tool_addition", "tool": {"type": "tool_definition", "definition": {"name": "mcp__x__y",
                                                                                            "input_schema": {}}}}
        opening = [{"role": "user", "content": [{"type": "text", "text": SUMMARY}]},
                   {"role": "system", "content": [{"type": "text", "text": ""}]},
                   {"role": "assistant", "content": [{"type": "text", "text": "The median is 55,120."}]},
                   {"role": "user", "content": [reminder,
                                                {"type": "text", "text": "<local-command-caveat>The command below ...</local-command-caveat>"},
                                                {"type": "text", "text": "<command-name>/compact</command-name>"},
                                                {"type": "text", "text": "<local-command-stdout>Compacted</local-command-stdout>"},
                                                {"type": "text", "text": "Which three countries were highest?"}]},
                   {"role": "system", "content": [{"type": "text", "text": "Called the Read tool with the following input: "
                                                   "{\"file_path\": \"/w/ag_readme.md\"}\nResult of calling the Read tool: ..."}, tool]}]
        self.assertEqual([(e["type"], e["payload"]["content"][0].get("text")) for e in claude.to_events(opening)],
                         [(claude.AGENT_MESSAGE, "The median is 55,120."),
                          (claude.USER_MESSAGE, "Which three countries were highest?")])
        later = opening + [{"role": "assistant", "content": [{"type": "text", "text": "Switzerland, the US, Norway."}]},
                           {"role": "user", "content": [{"type": "text", "text": "<system-reminder>a task finished</system-reminder>"},
                                                        {"type": "text", "text": "thanks"}]}]
        events = claude.to_events(later)
        self.assertEqual(len(events), 5)                                  # the next turn's note is kept
        self.assertIn("<system-reminder>a task finished</system-reminder>", [e["payload"]["content"][0].get("text") for e in events])
        plain = [{"role": "user", "content": [reminder, {"type": "text", "text": "hi"}]}]
        self.assertEqual([e["type"] for e in claude.to_events(plain)], [claude.CONTEXT, claude.USER_MESSAGE])   # not compacted: kept

    def test_the_summary_claude_code_goes_on_from_is_not_stored(self):
        after = [{"role": "user", "content": [{"type": "text", "text": SUMMARY}]},
                 {"role": "assistant", "content": [{"type": "text", "text": "Three."}]},
                 {"role": "user", "content": "which country was highest?"}]
        events = claude.to_events(after)
        self.assertFalse(any(SUMMARY[:40] in json.dumps(e) for e in events))
        self.assertEqual([e["type"] for e in events], [claude.AGENT_MESSAGE, claude.USER_MESSAGE])


if __name__ == "__main__":
    unittest.main()
