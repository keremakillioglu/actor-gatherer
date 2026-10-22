"""`ag dashboard` (ag/dashboard): what it reads from a home -- its gatherers and agents,
one agent over time, what a read held, the Gatherer's own model calls -- and the page,
served on localhost or written with its data inside it."""
import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ag.ag_harness import Manager  # noqa: E402
from ag.ag_harness.store import operations as store  # noqa: E402
from ag.ag_harness.store import paths  # noqa: E402
from ag.ag_policies.proactive_context_manager import ProactiveContextManager  # noqa: E402
from ag.ag_policies.proactive_context_manager import tables  # noqa: E402
from ag.dashboard import data, server  # noqa: E402
from channels import ch  # noqa: E402
from test_core import PREAMBLE, ScriptedLLM, conversation, long_turn, user  # noqa: E402
import codex_items  # noqa: E402


class HomeBase(unittest.TestCase):
    """A home of the test's own, with gatherer `g`: agent c1 with a history, reads (one
    with the provider's count and the harness's limit) and a build; agent c2 with events only."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = paths.TRACE_DIR, paths.AG_HOME
        paths.AG_HOME = os.path.join(self.tmp.name, "ag")
        paths.TRACE_DIR = os.path.join(paths.AG_HOME, "gatherers")
        os.makedirs(os.path.join(paths.TRACE_DIR, "g"))
        with open(os.path.join(paths.TRACE_DIR, "g", "gatherer.toml"), "w") as fh:
            fh.write('policy = "proactive_context_manager"\n')
        self.policy = ProactiveContextManager(codex_items.FORMAT, ScriptedLLM(),
                                              options={"min_context_tokens": 0, "sync_seconds": 0, "require_smaller": False})
        self.m = Manager(self.policy)
        self.m.init("g")
        items = codex_items.CodexItems(self.m)
        for item in PREAMBLE + conversation(4) + long_turn(2, start=50):
            items.insert("g", item, channel_id="c1")
        self.reads = []
        for limit in (None, 244800):
            ctx, read_id = self.m._context("g", store.high_water(self.m._conn("g")), ch("c1"), limit)
            self.reads.append(read_id)
        self.m.record_real_tokens("g", self.reads[0], 9999)
        self.build_id = tables.new_build(self.m._conn("g"), "c1")
        self.policy.build("g", ch("c1"), self.build_id)
        items.insert("g", user("the next request", 90), channel_id="c1")   # a new turn: the build is taken
        self.reads.append(self.m._context("g", store.high_water(self.m._conn("g")), ch("c1"), 244800)[1])
        items.insert("g", PREAMBLE[0], channel_id="c2")

    def tearDown(self):
        paths.TRACE_DIR, paths.AG_HOME = self.saved
        self.tmp.cleanup()

    def log_call(self, name, **record):
        os.makedirs(os.path.join(paths.AG_HOME, "logs", "llm"), exist_ok=True)
        with open(os.path.join(paths.AG_HOME, "logs", "llm", name), "w") as fh:
            json.dump(record, fh)


class DataTest(HomeBase):
    def test_the_home_lists_each_gatherer_s_agents_with_their_state(self):
        h = data.home()
        (g,) = h["gatherers"]
        self.assertEqual((g["name"], g["policy"]), ("g", "proactive_context_manager"))
        agents = {a["channel"]: a for a in g["agents"]}
        self.assertEqual(set(agents), {"c1", "c2"})
        c1 = agents["c1"]
        self.assertEqual((c1["reads"], c1["limit_tokens"], c1["harness"]), (3, 244800, "codex"))
        self.assertTrue(c1["running"])                      # read just now
        self.assertFalse(agents["c2"]["running"] and agents["c2"]["reads"])

    def test_an_agent_over_time(self):
        a = data.agent("g", "c1", [])
        self.assertEqual([r["read_id"] for r in a["reads"]], self.reads)
        first, second, third = a["reads"]
        self.assertEqual((first["real_tokens"], first["limit_tokens"], second["limit_tokens"]), (9999, None, 244800))
        self.assertTrue(all(r["est_tokens"] and r["sent_tokens"] >= r["est_tokens"] for r in a["reads"]))
        self.assertEqual([r["rebuild"] for r in a["reads"]], [False, False, True])   # the third took the build
        self.assertEqual(a["rebuilds"], 1)
        self.assertEqual(a["builds"][0]["build_id"], self.build_id)
        self.assertGreaterEqual(len(a["tasks"]), 2)
        self.assertEqual(third["tasks"], sum(1 for t in a["tasks"] if t["started"] <= third["at"]))
        self.assertTrue(all(t["started"] for t in a["tasks"]))

    def test_every_call_s_tokens_added_up_by_kind(self):
        a = data.agent("g", "c1", [])
        u = a["usage"]
        self.assertEqual(u["tokens"], sum(r["sent_tokens"] for r in a["reads"]))    # each message once per call
        self.assertEqual(u["calls"], 3)
        self.assertEqual(u["real_tokens"], 9999)
        groups = {e["group"] for e in u["entries"]}
        self.assertTrue({"Recent history", "Kept from before the cut", "ag's sections"} <= groups)

    def test_a_file_from_before_reads_had_sizes_still_has_ag_s_count(self):
        conn = sqlite3.connect(paths.db_path("g"))
        conn.executescript("ALTER TABLE _reads DROP COLUMN est_tokens; ALTER TABLE _reads DROP COLUMN real_tokens; "
                           "ALTER TABLE _reads DROP COLUMN limit_tokens;")
        conn.close()
        reads = data.agent("g", "c1", [])["reads"]
        self.assertTrue(all(r["sent_tokens"] > 0 and r["est_tokens"] is None and r["real_tokens"] is None for r in reads))
        c1 = next(a for a in data.home()["gatherers"][0]["agents"] if a["channel"] == "c1")
        self.assertEqual((c1["reads"], c1["real_tokens"]), (3, None))
        self.assertGreater(c1["sent_tokens"], 0)

    def test_what_a_read_held(self):
        r = data.read("g", self.reads[-1])
        groups = {g["group"]: g for g in r["groups"]}
        self.assertIsNotNone(r["cut"])                           # made from the build: the history was cut
        self.assertIn("Recent history", groups)
        self.assertIn("Kept from before the cut", groups)         # the preamble
        self.assertIn("ag's sections", groups)                   # the build's sections
        self.assertEqual(sum(g["tokens"] for g in r["groups"]),
                         data.agent("g", "c1", [])["reads"][-1]["sent_tokens"])   # what the chart plots

    def test_the_context_item_by_item(self):
        c = data.context("g", self.reads[-1])
        self.assertEqual([i["position"] for i in c["items"]], list(range(len(c["items"]))))     # in order
        self.assertEqual(c["tokens"], data.agent("g", "c1", [])["reads"][-1]["sent_tokens"])
        groups = [i["group"] for i in c["items"]]
        self.assertIn("ag's sections", groups)
        self.assertTrue(all(i["text"] for i in c["items"] if i["group"] == "ag's sections"))   # the section's text
        self.assertEqual(c["basis"], str(self.build_id))
        old = data.TEXT_CHARS
        data.TEXT_CHARS = 5
        try:
            clipped = data.context("g", self.reads[-1])["items"]
        finally:
            data.TEXT_CHARS = old
        self.assertTrue(all(len(i["text"]) <= 5 for i in clipped) and any(i["clipped"] for i in clipped))

    def test_the_gatherer_s_calls_go_to_the_agent_by_job_or_by_time(self):
        build = data.agent("g", "c1", [])["builds"][0]
        self.log_call("1-a-1-summarize.json", purpose="summarize", model="openai/gpt-4o-mini",
                      started="2000-01-01T00:00:00+00:00", usage={"prompt_tokens": 1000, "completion_tokens": 100},
                      seconds=1.0, error=None, job={"gatherer": "g", "job": "build", "id": 1, "properties": {"channel": "c1"}})
        self.log_call("2-b-1-rank.json", purpose="rank", model="codex/gpt-5.5", seconds=2.0, error=None,
                      started=time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(build["started"])),
                      usage={"input_tokens": 50, "output_tokens": 5})
        self.log_call("3-c-1-rank.json", purpose="rank", model="codex/gpt-5.5", seconds=2.0, error="boom",
                      started="2000-01-01T00:00:00+00:00", usage={})          # no job, outside every build
        llm = data.agent("g", "c1")["llm"]
        by = {p["purpose"]: p for p in llm["by_purpose"]}
        self.assertEqual((by["summarize"]["calls"], by["rank"]["calls"]), (1, 1))
        self.assertEqual((by["rank"]["tokens_in"], by["rank"]["unpriced"]), (50, 1))   # a CLI model: no price
        self.assertEqual(data.agent("g", "c2")["llm"]["total"]["calls"], 0)


class ReadableTest(unittest.TestCase):
    def test_the_words_of_an_event_ag_keeps_no_text_for(self):
        pi = {"api": "x", "role": "assistant", "content": [{"type": "thinking", "thinking": "Plan it."},
                                                             {"type": "text", "text": ""}]}
        self.assertEqual(data.readable(json.dumps(pi)), "Plan it.")
        self.assertEqual(data.readable(json.dumps({"role": "assistant", "content": [{"type": "text", "text": ""}]})), "")
        codex = {"type": "reasoning", "summary": [{"type": "summary_text", "text": "Checking."}], "encrypted_content": "zz"}
        self.assertEqual(data.readable(json.dumps(codex)), "Checking.")
        self.assertEqual(data.readable('{"a": 1}'), '{"a": 1}')                 # no blocks: the payload itself


class HarnessTest(unittest.TestCase):
    """Which harness an agent runs on, from its events' shape."""

    def test_each_harness_s_events(self):
        user = {"role": "user", "content": [{"type": "text", "text": "hi"}]}       # pi and Claude Code alike
        cases = {
            "codex": [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": "hi"}]}],
            "claude": [user, {"role": "assistant", "content": [{"type": "tool_use", "id": "t", "name": "Bash", "input": {}}]}],
            "pi": [user, {"role": "assistant", "api": "google-generative-ai", "content": [{"type": "toolCall", "name": "read"}]}],
            "opencode": [{"info": {"role": "user", "sessionID": "ses_1"}, "parts": []}],
        }
        for harness, payloads in cases.items():
            self.assertEqual(data.harness_of(payloads), harness, harness)
        self.assertIsNone(data.harness_of([user]))          # a lone user message tells nothing


class PageTest(HomeBase):
    def test_a_snapshot_stands_alone(self):
        text = server.page(data.snapshot())
        self.assertNotIn("/*SNAPSHOT*/null", text)
        embedded = text.split("const SNAPSHOT = ", 1)[1].split(";\nconst POLL_MS", 1)[0]
        snap = json.loads(embedded.replace("<\\/", "</"))
        self.assertIn("g\u0000c1", snap["agents"])
        self.assertIn(f"g\u0000{self.reads[-1]}", snap["reads"])     # the last read's contents, inside
        self.assertIn(f"g\u0000{self.reads[-1]}", snap["contexts"])

    def test_a_snapshot_cannot_close_its_script(self):
        text = server.page({"home": {"x": "</script><script>alert(1)</script>"}})
        self.assertEqual(text.count("</script>"), server.page().count("</script>"))

    def test_the_server_answers_the_page_and_its_data(self):
        httpd = server.serve("127.0.0.1", 0)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        url = f"http://127.0.0.1:{httpd.server_port}"
        get = lambda path: urllib.request.urlopen(url + path, timeout=10)  # noqa: E731
        self.assertIn("ag dashboard", get("/").read().decode())
        self.assertEqual(json.load(get("/api/home"))["gatherers"][0]["name"], "g")
        self.assertEqual(len(json.load(get("/api/agent?gatherer=g&channel=c1"))["reads"]), 3)
        self.assertTrue(json.load(get(f"/api/read?gatherer=g&read_id={self.reads[0]}"))["groups"])
        self.assertTrue(json.load(get(f"/api/context?gatherer=g&read_id={self.reads[0]}"))["items"])
        with self.assertRaises(urllib.error.HTTPError) as caught:
            get("/api/read?gatherer=g&read_id=x")
        self.assertEqual(caught.exception.code, 404)


class CommandTest(HomeBase):
    def test_out_writes_the_page_and_a_bad_argument_is_refused(self):
        from ag.cli import main
        out = os.path.join(self.tmp.name, "d.html")
        self.assertEqual(main.dashboard(["--out", out]), 0)
        with open(out) as fh:
            self.assertIn('"g\\u0000c1"', fh.read())
        with self.assertRaises(main.AgError):
            main.dashboard(["--bogus"])


if __name__ == "__main__":
    unittest.main()
