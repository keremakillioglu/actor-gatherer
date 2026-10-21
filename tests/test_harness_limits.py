"""A harness's own limit for its calls -- where it compacts by itself, or where its model's
window ends -- stated with each call: the launchers find it (codex: 90% of its model's
window; Claude Code: its documented thresholds), the hook server carries it from the URL
(`/l/<n>`), the server keeps it on the read, and the policy keeps max_context_tokens at
harness_limit_fraction of it for that channel's reads and builds, unless the gatherer sets
max_context_tokens itself."""
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ag.ag_harness import Manager  # noqa: E402
from ag.ag_harness import home as ag_home  # noqa: E402
from ag.ag_harness.server import serve  # noqa: E402
from ag.ag_harness.server.__main__ import server_for  # noqa: E402
from ag.ag_harness.store import operations as store  # noqa: E402
from ag.ag_harness.store import paths  # noqa: E402
from ag.ag_policies.proactive_context_manager import ProactiveContextManager, ProactiveContextManagerConfig  # noqa: E402
from ag.ag_policies.proactive_context_manager import tables  # noqa: E402
from ag.ag_policies.proactive_context_manager.config import within_limit  # noqa: E402
from ag.integrations.harnesses.claude.setup import launch as claude  # noqa: E402
from ag.integrations.harnesses.codex.adaptor import to_events as codex_events  # noqa: E402
from ag.integrations.harnesses.codex.setup import launch as codex  # noqa: E402
from channels import ch  # noqa: E402
from test_core import PREAMBLE, SMALL, Recording, ScriptedLLM, conversation, long_turn  # noqa: E402
import codex_items  # noqa: E402

DEV = {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "instructions"}]}
UNSIZED = {k: v for k, v in SMALL.items() if k != "max_context_tokens"}   # the gatherer sets no max


class WithinLimitTest(unittest.TestCase):
    def test_above_the_default_only_the_max_moves(self):
        cfg = ProactiveContextManagerConfig()
        wide = within_limit(cfg, 967_000)
        self.assertEqual(wide.max_context_tokens, int(967_000 * 0.9))
        self.assertEqual((wide.section_budgets, wide.min_context_tokens), (cfg.section_budgets, cfg.min_context_tokens))

    def test_below_it_the_budgets_shrink_with_it(self):
        cfg = ProactiveContextManagerConfig()
        narrow = within_limit(cfg, 111_616)                  # pi on a 128K model: window less its reserve
        self.assertEqual(narrow.max_context_tokens, 100_454)
        self.assertLess(narrow.section_budgets + narrow.keep_pinned_tokens, narrow.max_context_tokens)
        self.assertAlmostEqual(narrow.keep_so_far_tokens / cfg.keep_so_far_tokens, 100_454 / 200_000, places=3)


class PolicyBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = paths.TRACE_DIR
        paths.TRACE_DIR = os.path.join(self.tmp.name, "traces")
        self.spawned = []

    def tearDown(self):
        paths.TRACE_DIR = self.saved
        self.tmp.cleanup()

    def make(self, options):
        self.policy = ProactiveContextManager(codex_items.FORMAT, ScriptedLLM(), options=options)
        self.policy.jobs = Recording(lambda s, c, job, job_id: self.spawned.append(job))
        self.m = Manager(self.policy)
        self.m.init("s")
        self.items = codex_items.CodexItems(self.m)

    def put(self, items):
        for item in items:
            self.items.insert("s", item, channel_id="c1")

    def read(self, limit=None):
        return self.m._context("s", store.high_water(self.m._conn("s")), ch("c1"), limit)


class PolicyLimitTest(PolicyBase):
    LIMIT = 3334                                           # 0.9 of it: SMALL's own max, 3000

    def test_a_stated_limit_sets_the_max_for_the_read(self):
        self.make(UNSIZED)
        self.put(PREAMBLE + long_turn(40))                 # far over 3000, far under the default 200000
        self.read()
        self.assertEqual(self.spawned, [])                 # no limit stated: the default holds
        ctx, read_id = self.read(self.LIMIT)
        self.assertEqual(self.spawned, ["build"])          # over 0.9 of the harness's limit: built
        self.assertLessEqual(ctx.tokens, 3000)
        self.assertEqual(store.last_read(self.m._conn("s"))["limit_tokens"], self.LIMIT)
        self.assertEqual(self.policy.config.max_context_tokens, 200_000)   # the policy's own config, after

    def test_the_gatherer_s_own_max_wins(self):
        self.make(dict(UNSIZED, max_context_tokens=200_000))
        self.put(PREAMBLE + long_turn(40))
        self.read(self.LIMIT)
        self.assertEqual(self.spawned, [])

    def test_a_build_works_within_its_channel_s_last_limit(self):
        self.make(UNSIZED)
        self.put(PREAMBLE + conversation(8) + long_turn(3, start=50))
        self.read(self.LIMIT)
        seen = []
        within = self.policy.build_within
        self.policy.build_within = lambda *a: seen.append(self.policy.config.max_context_tokens) or within(*a)
        self.policy.build("s", ch("c1"), tables.new_build(self.m._conn("s"), "c1"))
        self.assertEqual(seen, [3000])
        self.assertEqual(self.policy.config.max_context_tokens, 200_000)


class ServerLimitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = paths.TRACE_DIR, paths.AG_HOME
        root = os.path.join(self.tmp.name, "ag")
        paths.AG_HOME, paths.TRACE_DIR = root, os.path.join(root, "gatherers")
        ag_home._HOMES.clear()

    def tearDown(self):
        paths.TRACE_DIR, paths.AG_HOME = self.saved
        ag_home._HOMES.clear()
        self.tmp.cleanup()

    def test_a_rewrite_s_limit_is_kept_on_its_read(self):
        out = io.StringIO()
        requests = [{"op": "rewrite", "gatherer": "s", "events": codex_events.to_events([DEV]), "limit": 244800},
                    {"op": "rewrite", "gatherer": "s", "events": codex_events.to_events([DEV]), "limit": "big"}]
        serve(server_for(), [json.dumps(dict(r, id=i)) for i, r in enumerate(requests, 1)], out)
        conn = sqlite3.connect(paths.db_path("s"))
        try:
            limits = [v for (v,) in conn.execute("SELECT limit_tokens FROM _reads ORDER BY read_id")]
        finally:
            conn.close()
        self.assertEqual(limits[0], 244800)
        self.assertTrue(all(v is None for v in limits[1:]))   # not a limit: none stated


class RouteTest(unittest.TestCase):
    def test_the_url_s_limit_follows_its_label(self):
        try:
            from ag.integrations.tools.hook_server.hook_server import limit_of, route_of
        except ImportError:
            self.skipTest("the hook server needs aiohttp")
        label, rest = route_of("/h/demo/l/244800/v1/responses")
        self.assertEqual((label, limit_of(rest)), ("demo", (244800, "/v1/responses")))
        self.assertEqual(limit_of("/v1/responses"), (None, "/v1/responses"))
        self.assertEqual(limit_of("/l/0/v1"), (None, "/l/0/v1"))              # zero states nothing
        self.assertEqual(limit_of("/l/12"), (12, "/"))


def plan(**kw):
    return codex.Plan("openai", "https://api.openai.com", "/v1", [], "/h", **kw)


class CodexLimitTest(unittest.TestCase):
    CATALOG = {"gpt-5.5": {"slug": "gpt-5.5", "context_window": 272000, "max_context_window": 272000},
               "gpt-5.4": {"slug": "gpt-5.4", "context_window": 272000, "max_context_window": 1000000}}

    def test_ninety_percent_of_the_catalog_s_window(self):
        self.assertEqual(codex.harness_limit(plan(model="gpt-5.5"), lambda: self.CATALOG)[0], 244800)

    def test_a_set_window_is_capped_at_the_model_s_largest(self):
        self.assertEqual(codex.harness_limit(plan(model="gpt-5.4", window=800000), lambda: self.CATALOG)[0], 720000)
        self.assertEqual(codex.harness_limit(plan(model="gpt-5.5", window=800000), lambda: self.CATALOG)[0], 244800)

    def test_a_model_codex_does_not_know_gets_its_fallback_window(self):
        asked = []
        self.assertEqual(codex.harness_limit(plan(model="gemini-3.1-pro-preview"),
                                             lambda: asked.append(1) or self.CATALOG)[0], 244800)
        self.assertEqual(codex.harness_limit(plan(), lambda: asked.append(2) or {})[0], 244800)
        self.assertEqual(asked, [1])                       # no model named: the catalog is not asked

    def test_the_run_s_own_limit_when_lower(self):
        limit, found = codex.harness_limit(plan(model="gpt-5.5", own_limit=150000), lambda: self.CATALOG)
        self.assertEqual((limit, found), (150000, "model_auto_compact_token_limit=150000"))
        self.assertEqual(codex.harness_limit(plan(model="gpt-5.5", own_limit=900000), lambda: self.CATALOG)[0], 244800)

    def test_the_plan_finds_the_model_and_window_and_the_url_states_the_limit(self):
        with tempfile.TemporaryDirectory() as home:
            with open(os.path.join(home, "config.toml"), "w") as fh:
                fh.write('model = "gpt-5.4"\nmodel_context_window = 600000\n')
            p = codex.plan(["-m", "gpt-5.5", "exec", "hi"], {}, {"CODEX_HOME": home})
            self.assertEqual((p.model, p.window, p.own_limit), ("gpt-5.5", 600000, None))
            p.limit = 244800
            self.assertEqual(p.base_url("http://127.0.0.1:4013", "demo"), "http://127.0.0.1:4013/h/demo/l/244800/v1")


CONTEXT_REPORT = """## Context Usage

**Model:** claude-sonnet-4-6
**Tokens:** 30.4k / 200k (15%)

| Category | Tokens | Percentage |
|----------|--------|------------|
| System prompt | 6.9k | 3.5% |
| Free space | 136.6k | 68.3% |
| Autocompact buffer | 33k | 16.5% |
"""


class ClaudeLimitTest(unittest.TestCase):
    """Without /context (the probe answers nothing): the documented rules, less the buffer."""

    def limit(self, args=(), env=None, settings=None):
        return claude.harness_limit(list(args), env or {}, settings or {}, lambda: None)[0]

    def test_windows_by_model(self):
        self.assertEqual(self.limit(), 167_000)                                          # no model named: 200K
        self.assertEqual(self.limit(["--model", "claude-sonnet-4-6"]), 167_000)
        self.assertEqual(self.limit(["--model", "claude-sonnet-4-6[1m]"]), 967_000)
        self.assertEqual(self.limit(["--model=claude-opus-5-5"]), 967_000)               # native 1M
        self.assertEqual(self.limit(env={"ANTHROPIC_MODEL": "claude-fable-5-1"}), 967_000)
        self.assertEqual(self.limit(settings={"model": "opus"}), 967_000)                # an alias: the newest
        self.assertEqual(self.limit(settings={"model": "opus"}, env={"CLAUDE_CODE_DISABLE_1M_CONTEXT": "1"}), 167_000)
        self.assertEqual(self.limit(["--model", "gateway-x"], {"CLAUDE_CODE_MAX_CONTEXT_TOKENS": "400k"}), 367_000)

    def test_an_auto_compact_window_and_a_percentage_lower_it(self):
        opus = ["--model", "claude-opus-5-5"]
        self.assertEqual(self.limit(opus + ["--autocompact", "500"]), 467_000)            # bare 100-1000: thousands
        self.assertEqual(self.limit(opus, {"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "300000"}), 267_000)
        self.assertEqual(self.limit(opus, settings={"autoCompactWindow": 400000}), 367_000)
        self.assertEqual(self.limit(opus, settings={"modelSettings": {"claude-opus-5-5": {"autoCompactWindow": 350000}},
                                                    "autoCompactWindow": 400000}), 317_000)
        self.assertEqual(self.limit(["--model", "claude-sonnet-4-6", "--autocompact", "500k"]), 167_000)   # capped
        self.assertEqual(self.limit(opus, {"CLAUDE_AUTOCOMPACT_PCT_OVERRIDE": "50"}), 500_000)
        self.assertEqual(self.limit(opus, {"CLAUDE_AUTOCOMPACT_PCT_OVERRIDE": "150"}), 967_000)   # only lowers


class ClaudeContextTest(unittest.TestCase):
    """With /context: Claude Code's own window and buffer."""

    def test_the_report_s_window_and_buffer(self):
        self.assertEqual(claude.context_of(CONTEXT_REPORT), (200_000, 33_000))
        self.assertEqual(claude.context_of(CONTEXT_REPORT.replace("200k", "1m").splitlines()[3]), (1_000_000, None))
        self.assertIsNone(claude.context_of("Error: something else"))

    def test_the_limit_is_its_window_less_its_buffer(self):
        self.assertEqual(claude.harness_limit([], {}, {}, lambda: (500_000, 33_000)), (
            467_000, "Claude Code's /context: window 500000, auto-compact buffer 33000"))
        self.assertEqual(claude.harness_limit([], {}, {}, lambda: (200_000, None))[0], 167_000)   # none shown
        self.assertEqual(claude.harness_limit([], {"CLAUDE_AUTOCOMPACT_PCT_OVERRIDE": "60"}, {},
                                              lambda: (1_000_000, 33_000))[0], 600_000)

    def test_the_probe_asks_claude_code_with_the_run_s_flags_and_no_api(self):
        with tempfile.TemporaryDirectory() as d:
            fake, seen = os.path.join(d, "claude"), os.path.join(d, "seen")
            with open(fake, "w") as fh:          # a stand-in: records its arguments and API, prints a report
                fh.write(f"#!/bin/sh\necho \"$*\" > {seen}\necho \"$ANTHROPIC_BASE_URL\" >> {seen}\n"
                         "printf '**Tokens:** 1k / 500k\\n| Autocompact buffer | 33k | 6%% |\\n'\n")
            os.chmod(fake, 0o755)
            got = claude.probe([fake], ["--model", "m1", "--autocompact=500k", "-c", "--verbose", "hi"],
                               {"ANTHROPIC_BASE_URL": "https://api.anthropic.com"})
            with open(seen) as fh:
                args, api = fh.read().splitlines()
        self.assertEqual(got, (500_000, 33_000))
        self.assertEqual(args, "-p /context --no-session-persistence --strict-mcp-config --model m1 --autocompact 500k")
        self.assertEqual(api, claude.DEAD_API)  # whatever the run's API: nothing is billed


if __name__ == "__main__":
    unittest.main()
