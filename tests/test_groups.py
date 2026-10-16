"""The proactive context manager works from the event types its groups name
(tools/groups.py): what it loads, what it pins, and what it leaves alone."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ag.ag_harness import Event, EventType  # noqa: E402
import codex_items as codex  # noqa: E402
from ag.ag_interface.policy import TypeIds     # noqa: E402
from ag.ag_policies.proactive_context_manager import events, layout  # noqa: E402
from ag.ag_policies.proactive_context_manager import tables  # noqa: E402
from ag.ag_policies.tools import history  # noqa: E402
from ag.ag_policies.tools.groups import Groups  # noqa: E402
from ag.ag_harness.store import operations as store  # noqa: E402
from test_core import PREAMBLE, Base, agent, call, conversation, output, user  # noqa: E402
from channels import CHANNEL, ch, on  # noqa: E402
from ag.ag_interface import Property  # noqa: E402

OUTSIDE = (events.ENVIRONMENT_UPDATE, events.CONTEXT_STREAM)   # the outside types, in no group
CHANGE = EventType("file_changed", (Property(CHANNEL),))   # a type the policy does not know


def developer(text, n):
    return {"type": "message", "role": "developer", "id": f"dev{n}",
            "content": [{"type": "input_text", "text": text}]}


def compaction(text, n):
    return {"type": "compaction", "id": f"cmp{n}", "summary": text}


def agents_md(text, n):
    return {"type": "message", "role": "user", "id": f"env{n}",
            "content": [{"type": "input_text", "text": f"# AGENTS.md instructions for /x\n{text}"}]}


class GroupsBase(Base):
    def setUp(self):
        super().setUp()
        self.wrapped = codex.CodexItems(self.m)
        self.wrapped.init("s")
        self.change_id = self.m.add_event_type("s", CHANGE)

    def change(self, path, n, channel="c1"):
        return self.m.insert("s", on(Event(self.change_id, {"file_path": path, "timestamp": n}, id=f"chg{n}"), channel))

    def sections(self, context):
        """The condensation sections' texts: what the build made (not an
        AGENTS.md fragment, which also starts with `# `)."""
        return [t for t in (codex.text(i) for i in context) if t.startswith("# ") and not t.startswith("# AGENTS.md")]


class DeclarationTest(unittest.TestCase):
    def test_the_groups_the_policy_works_from(self):
        groups = Groups()
        self.assertEqual(groups.history, ("user_message", "agent_message", "tool_call", "tool_output", "context",
                                          "agent_reasoning"))
        self.assertEqual(groups.user, ("user_message",))
        self.assertEqual(groups.messages, ("user_message", "agent_message"))
        self.assertEqual(groups.tools, ("tool_call", "tool_output"))
        self.assertEqual(groups.pinned, ("context",))
        self.assertEqual([t.name for t in events.EVENT_TYPES if t.name not in OUTSIDE], list(groups.history))   # every type it declares, but the outside ones


class TypeIdsTest(GroupsBase):
    def test_names_resolve_to_the_gatherers_ids(self):
        types = TypeIds.load(self.m.store("s"))
        by_name = {t.name: t.id for t in types.types}
        self.assertEqual(list(by_name), [t.name for t in events.EVENT_TYPES] + ["file_changed"])
        self.assertEqual(types.of("user_message"), {by_name["user_message"]})
        self.assertEqual(types.of("context"), {by_name["context"]})
        self.assertEqual(types.of("agent_message"), {by_name["agent_message"]})
        self.assertEqual(types.of("file_changed"), {self.change_id})
        self.assertEqual(types.of("nothing"), frozenset())
        self.assertEqual(types.of(*Groups().history), set(by_name.values()) - {self.change_id} - types.of(*OUTSIDE))
        self.assertEqual(types.name(self.change_id), "file_changed")
        self.assertIsNone(types.name(999))


def thought(n):
    """A codex reasoning item: an encrypted blob, as codex sends it."""
    return {"type": "reasoning", "id": f"rs{n}", "summary": [], "encrypted_content": "gAAAAAB" + "Qx9z" * 400}


def with_reasoning(turns, start=1):
    items = []
    for n in range(start, start + turns):
        items += [user(f"question {n}", n), thought(f"{n}a"), call(n), output(n), thought(f"{n}b"), agent(f"answer {n}", n)]
    return items


class ReasoningTest(GroupsBase):
    """The model's reasoning (`agent_reasoning`): sent back as it was where the history is verbatim,
    never rendered into a section, never counted in a task's size."""

    def test_returned_verbatim_before_a_build(self):
        items = PREAMBLE + with_reasoning(3)
        self.put(items)
        self.assertEqual(self.read(), items)

    def test_costs_nothing_and_is_not_a_message(self):
        self.put(PREAMBLE + with_reasoning(2))
        conn = self.m.store("s")
        types = TypeIds.load(conn)
        rows = history.rows(conn, types, self.policy.groups, "c1")
        blobs = [r for r in rows if r.type.name == "agent_reasoning"]
        self.assertEqual(len(blobs), 4)
        self.assertEqual({r.tokens for r in blobs}, {0})
        _, turns = history.split(rows, types, self.policy.groups, self.policy.tokenizer)
        reasoning = [e for t in turns for e in t.entries if e.type == "agent_reasoning"]
        self.assertTrue(reasoning and not any(e.is_message or e.is_tool or e.is_user for e in reasoning))
        self.assertEqual({e.tokens for e in reasoning}, {0})
        messages_only = sum(r.tokens for r in rows if r.type.name in ("user_message", "agent_message")
                            and r.row_id >= turns[0].first_row)
        self.assertEqual(sum(t.message_tokens for t in turns), messages_only)   # the blobs add nothing

    def test_never_in_a_section_but_kept_in_the_running_task(self):
        self.put(PREAMBLE + with_reasoning(12))
        self.run_build("s", "c1")
        self.put([user("q", 50)])
        self.assertTrue(self.sections(self.read()))                             # switched to at the user message
        self.put([thought("50a"), call(50)])
        context = self.read()
        self.assertTrue(self.sections(context))
        self.assertNotIn("encrypted_content", "\n".join(self.sections(context)))
        self.assertEqual(context[-2:], [thought("50a"), call(50)])              # the running task: as it was

class UngroupedTypeTest(GroupsBase):
    """An event of a type none of the policy's groups names is not its
    business: never loaded, counted or returned."""

    def test_not_returned_before_or_after_a_build(self):
        items = PREAMBLE + conversation(6)
        self.put(items)
        self.change("a.py", 1)
        self.assertEqual(self.read(), items)
        self.put(conversation(6, start=7))
        self.change("b.py", 2)
        self.run_build("s", "c1")
        self.put([user("q", 50)])
        context = self.read()
        payloads = [i for i in context if isinstance(i, dict) and "file_path" in i]
        self.assertEqual(payloads, [])
        self.assertTrue(self.sections(context))
        self.assertNotIn("a.py", "\n".join(self.sections(context)))

    def test_a_trailing_one_does_not_hide_the_user_message(self):
        self.put(PREAMBLE + conversation(12))
        self.run_build("s", "c1")
        self.put([user("q", 50)])
        self.change("a.py", 1)                                    # after the user's message
        context = self.read()                                     # still a read at a user message:
        self.assertTrue(any(t.startswith("# Previous task") for t in self.sections(context)))   # it switched
        self.assertEqual(codex.text(context[-1]), "q")

    def test_not_counted(self):
        from ag.ag_policies.proactive_context_manager import report
        self.put(PREAMBLE + conversation(2))
        before = report.describe(self.m.store("s"), "c1")
        self.change("a.py", 1)
        after = report.describe(self.m.store("s"), "c1")
        self.assertEqual((after["events"], after["trace_tokens"]), (before["events"], before["trace_tokens"]))


class PinnedContextTest(GroupsBase):
    """CONTEXT events are returned verbatim wherever they are, never condensed."""

    def test_mid_history_context_survives_a_build_between_sections_and_tail(self):
        self.put(PREAMBLE + conversation(6))
        self.put([developer("Remember: always run the linter.", 1)])
        self.put([compaction("older history was summarized", 1)])
        self.put(conversation(6, start=7))
        self.put([agents_md("Use tabs.", 1)])
        self.put(conversation(2, start=13))
        self.run_build("s", "c1")
        self.put([user("q", 50)])
        context = self.read()
        texts = [codex.text(i) for i in context]
        self.assertTrue(self.sections(context))
        last_section = max(i for i, t in enumerate(texts) if t in self.sections(context))
        first_tail = texts.index("question 13") if "question 13" in texts else texts.index("q")
        kept = ["Remember: always run the linter.", "# AGENTS.md instructions for /x\nUse tabs."]
        for text in kept:
            at = texts.index(text)
            self.assertGreater(at, last_section, text)             # after the sections
            self.assertLess(at, first_tail, text)                  # before the verbatim tail
        # the compaction item has no text the model reads, but it is there too
        self.assertTrue(any(isinstance(i, dict) and i.get("type") == "compaction" for i in context))
        # in row order among themselves
        self.assertLess(texts.index(kept[0]), texts.index(kept[1]))
        # and in no section
        for text in kept + ["older history was summarized"]:
            self.assertNotIn(text, "\n".join(self.sections(context)))

    def test_pinned_rows_do_not_count_as_replaced_history(self):
        self.put(PREAMBLE + conversation(4))
        self.put([developer("x" * 4000, 1)])                      # a big instruction mid-history
        self.put(conversation(4, start=5))
        conn = self.m.store("s")
        types = TypeIds.load(conn)
        groups = self.policy.groups
        rows = history.rows(conn, types, groups, "c1")
        _, turns = history.split(rows, types, groups, self.policy.tokenizer)
        cut = turns[-1].first_row
        secs = layout.Sections(sections=[("x", "small section")], open_from_row=cut)
        replaced_without = sum(r.tokens for r in rows if turns[0].first_row <= r.row_id < cut
                               and r.type.name != "context")
        self.assertIsNone(self.policy.not_smaller(secs, rows, turns, types))    # small section < replaced
        big = layout.Sections(sections=[("x", "y " * replaced_without)], open_from_row=cut)
        self.assertIsNotNone(self.policy.not_smaller(big, rows, turns, types))
        self.assertIn(f"({replaced_without})", self.policy.not_smaller(big, rows, turns, types))

    def test_a_user_context_message_opens_no_turn(self):
        self.put(PREAMBLE + conversation(2))
        self.put([agents_md("Use tabs.", 1)])
        self.put([agent("ok", 99)])
        conn = self.m.store("s")
        _, turns = history.turns(conn, TypeIds.load(conn), self.policy.groups, self.policy.tokenizer, "c1")
        self.assertEqual(len(turns), 2)                           # not three
        self.assertEqual([e.type for e in turns[-1].entries][-2:], ["context", "agent_message"])


if __name__ == "__main__":
    unittest.main()
