"""The policy's limits count all the model gets with a call: the context it arranges, the history's
preamble, the sections' overview, and what the harness sends besides the context -- its system
prompt and tools, stated with the call (the rewrite's `preamble`), whose size the read is given
(`Read.fixed_tokens`) and the read log keeps (a build, which has no read, takes it from there)."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ag.ag_harness import Manager  # noqa: E402
from ag.ag_harness.store import operations as store  # noqa: E402
from ag.ag_harness.store import paths  # noqa: E402
from ag.ag_policies.proactive_context_manager import ProactiveContextManager  # noqa: E402
from ag.ag_policies.proactive_context_manager import tables  # noqa: E402
from channels import ch  # noqa: E402
from test_core import PREAMBLE, SMALL, Recording, ScriptedLLM, conversation, long_turn, user  # noqa: E402
import codex_items  # noqa: E402


class WholeContextTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = paths.TRACE_DIR
        paths.TRACE_DIR = os.path.join(self.tmp.name, "traces")
        self.spawned = []

    def tearDown(self):
        paths.TRACE_DIR = self.saved
        self.tmp.cleanup()

    def make(self, **options):
        self.policy = ProactiveContextManager(codex_items.FORMAT, ScriptedLLM(), options=dict(SMALL, **options))
        self.policy.jobs = Recording(lambda s, c, job, job_id: self.spawned.append(job))
        self.m = Manager(self.policy)
        self.m.init("s")
        self.items = codex_items.CodexItems(self.m)

    def put(self, items):
        for item in items:
            self.items.insert("s", item, channel_id="c1")

    def system(self, tokens):
        """A system prompt of about `tokens` tokens, as the harness states it with a call."""
        return [{"name": "instructions", "text": "word " * tokens}]

    def read(self, preamble=None):
        return self.m._context("s", store.high_water(self.m._conn("s")), ch("c1"), preamble=preamble)

    def test_the_harness_s_part_counts_toward_the_max(self):
        self.make(min_context_tokens=2900)
        self.put(PREAMBLE + conversation(4))
        ctx, _ = self.read()
        self.assertLess(ctx.tokens, 2900)
        self.assertEqual(self.spawned, [])                     # under the min, by the context alone
        self.read(self.system(3000))
        self.assertEqual(self.spawned, ["build"])              # with the system prompt: over the max, built

    def test_and_toward_the_min(self):
        self.make(min_context_tokens=1500, max_context_tokens=100_000)
        self.put(PREAMBLE + conversation(4))
        ctx, _ = self.read()
        self.assertLess(ctx.tokens, 1500)
        self.assertEqual(self.spawned, [])
        self.put([user("one more question", 9)])
        self.read()
        self.assertEqual(self.spawned, [])                     # at a user message, under the min: nothing
        self.put([user("and another", 10)])
        self.read(self.system(1500))
        self.assertEqual(self.spawned, ["check"])              # with the system prompt, over it: asked

    def test_the_read_s_own_size_is_still_what_the_policy_arranges(self):
        self.make(min_context_tokens=100_000, max_context_tokens=200_000)
        self.put(PREAMBLE + conversation(4))
        plain, _ = self.read()
        with_system, _ = self.read(self.system(1000))
        self.assertEqual(with_system.tokens, plain.tokens)     # est_tokens: as before

    def test_the_read_log_keeps_the_fixed_size(self):
        self.make()
        self.put(PREAMBLE + conversation(2))
        pre = self.system(300)
        self.read(pre)
        self.assertEqual(store.last_read(self.m._conn("s"), ch("c1"))["fixed_tokens"],
                         self.policy.tokenizer.count(pre[0]["text"]))

    def test_steps_are_left_out_until_all_of_it_fits(self):
        self.make(min_context_tokens=2999)
        self.policy.jobs = None                                # nothing to build with: stubbing alone
        self.put(PREAMBLE + long_turn(12))
        pre = self.system(1500)
        ctx, _ = self.read(pre)
        conn = self.m._conn("s")
        rows = {r.row_id: r for r in store.rows(conn, match=ch("c1"))}
        opening = sum(r.tokens for r in rows.values() if r.event_id in {e["id"] for e in PREAMBLE})
        self.assertLessEqual(ctx.tokens + opening + self.policy.tokenizer.count(pre[0]["text"]), 3000)

    def test_a_one_turn_build_counts_the_harness_s_part_too(self):
        self.make()
        self.put(PREAMBLE + long_turn(3))                      # one turn, under the max by itself
        self.read(self.system(2900))                           # with the system prompt, over it
        conn = self.m._conn("s")
        build_id = tables.new_build(conn, "c1")
        self.policy.build("s", ch("c1"), build_id)
        self.assertNotEqual((tables.get_build(conn, build_id) or {}).get("error"), "fewer than two turns")


if __name__ == "__main__":
    unittest.main()
