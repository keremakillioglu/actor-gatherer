"""ag's hook following the harness's own record of each session (ag/integrations/tools/ag_orchestrator/session_files.py):
what the record says, recorded as events of the session as it is written -- each the same event however often it is
read -- and the launchers naming the harness's own folder in the hook server's URL, where the hook looks for it."""
import asyncio
import json
import os
import sys
import tempfile
import time
import unittest
import unittest.mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness_kit import ClaudeCode, Codex  # noqa: E402
from harness_kit.base import Facts, follow  # noqa: E402
from harness_kit import claude as claude_rules, codex as codex_rules  # noqa: E402

from ag.integrations.harnesses.claude.setup.launch import base_url  # noqa: E402
from ag.integrations.harnesses.codex.setup.hook_servers import config_part  # noqa: E402
from ag.integrations.harnesses.codex.setup.launch import Plan  # noqa: E402
from ag.integrations.tools.ag_orchestrator import session_files  # noqa: E402
from ag.integrations.tools.ag_orchestrator.session_files import SessionFiles  # noqa: E402

SESSION = "0e1d2c3b-0000-4000-8000-000000000009"
THREAD = "01a17625-344f-7ce2-8c1e-dd7931e0e2d9"


def stamp(at=None):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() if at is None else at))


class Server:
    """The gatherer's server, as the hook sees it: each `insert` kept, each event once by its id."""

    def __init__(self):
        self.inserted, self.ids, self.lanes = [], set(), []

    def client(self, gatherer):
        return self

    async def request(self, op, body=None, timeout=None):
        assert op == "insert", op
        self.lanes.append(body.get("lane"))
        for e in body["events"]:
            if e["id"] not in self.ids:
                self.ids.add(e["id"])
                self.inserted.append((body["properties"]["channel"], e))
        return {"rows": [1] * len(body["events"])}

    def types(self):
        return [e["type"] for _, e in self.inserted]


class FollowTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = os.path.join(self.tmp.name, "claude config")
        self.cwd = "/work/repo"
        self.path = os.path.join(self.config, "projects", "-work-repo", f"{SESSION}.jsonl")
        os.makedirs(os.path.dirname(self.path))
        self.server = Server()
        self.files = SessionFiles(self.server, lambda g, line: None, poll=0.01, quiet=60)

    async def asyncTearDown(self):
        await self.files.close()

    def write(self, *lines):
        with open(self.path, "a") as fh:
            for line in lines:
                fh.write(json.dumps(line) + "\n")

    def op(self, operation, text=None, **more):
        line = {"type": "queue-operation", "operation": operation, "timestamp": stamp()}
        return {**line, **({"content": text} if text is not None else {}), **more}

    def follow(self, files=None):
        (files or self.files).follow("g", SESSION, ClaudeCode(), SESSION, self.cwd, self.config)

    async def until(self, check, seconds=2.0):
        end = time.time() + seconds
        while not check():
            if time.time() > end:
                self.fail(f"not in time: {self.server.types()}")
            await asyncio.sleep(0.01)

    async def test_what_it_says_is_recorded_as_it_is_written(self):
        self.write(self.op("enqueue", "also do b"))
        self.follow()
        await self.until(lambda: self.server.types() == ["session_file", "message_queued"])
        channel, first = self.server.inserted[0]
        self.assertEqual((channel, first["payload"]), (SESSION, {"harness": "claude", "path": self.path}))
        queued = self.server.inserted[1][1]
        self.assertRegex(queued["id"], rf"^message_queued:{SESSION}\.jsonl:0\.[0-9a-f]{{8}}$")   # its line: where, and its bytes
        self.assertEqual((queued["payload"]["words"], queued["payload"]["queued"]), ("also do b", queued["id"].rsplit(":", 1)[1]))
        self.write(self.op("remove", "also do b", reason="absorbed_mid_turn"))           # no call: still followed
        await self.until(lambda: self.server.types()[-1:] == ["message_sent"])
        self.assertEqual(self.server.inserted[-1][1]["payload"]["how"], "mid_turn")
        self.assertEqual(set(self.server.lanes), {"records"})              # beside the session's reads, not behind them

    async def test_read_again_from_its_start_it_is_the_same_events(self):
        self.write(self.op("enqueue", "one"), self.op("dequeue"))
        self.follow()
        await self.until(lambda: len(self.server.inserted) == 3)
        before = [e["id"] for _, e in self.server.inserted]
        again = Server()
        files = SessionFiles(again, lambda g, line: None, poll=0.01)                   # a hook server started again
        self.addAsyncCleanup(files.close)
        files.follow("g", SESSION, ClaudeCode(), SESSION, self.cwd, self.config)
        await asyncio.sleep(0.1)
        self.assertEqual([e["id"] for _, e in again.inserted], before)                  # the server stores none twice

    async def test_claude_code_s_name_for_it_recorded_once_however_often_written_or_read(self):
        title = {"type": "ai-title", "aiTitle": "Lighthouse keeper story", "sessionId": SESSION}
        self.write(self.op("enqueue", "one"), title, title)
        self.follow()
        await self.until(lambda: self.server.types() == ["session_file", "message_queued", "name"])
        self.assertEqual(self.server.inserted[-1][1]["payload"], {"at": None, "text": "Lighthouse keeper story", "by": "claude"})
        self.write(title)                                                  # it rewrites its metadata: the same name
        await asyncio.sleep(0.1)
        self.assertEqual(self.server.types().count("name"), 1)
        again = Server()
        files = SessionFiles(again, lambda g, line: None, poll=0.01)                   # a hook server started again
        self.addAsyncCleanup(files.close)
        files.follow("g", SESSION, ClaudeCode(), SESSION, self.cwd, self.config)
        await asyncio.sleep(0.1)
        self.assertEqual([e["id"] for _, e in again.inserted], [e["id"] for _, e in self.server.inserted])

    async def test_quiet_it_is_followed_no_more_until_the_next_call(self):
        self.files.quiet = 0.05
        self.write(self.op("enqueue", "one"))
        self.follow()
        await self.until(lambda: len(self.server.inserted) == 2)
        task = self.files.followed[("g", SESSION)].task
        await self.until(lambda: task.done())
        self.write(self.op("enqueue", "two"))
        await asyncio.sleep(0.1)
        self.assertEqual(len(self.server.inserted), 2)                                  # not followed: not read
        self.follow()                                                                    # the session's next call
        await self.until(lambda: self.server.types()[-1:] == ["message_queued"] and len(self.server.inserted) == 3)
        self.assertEqual(self.server.inserted[-1][1]["payload"]["words"], "two")       # read on from where it was

    async def test_none_yet_it_is_looked_for_a_while_then_with_the_next_call(self):
        os.rmdir(os.path.dirname(self.path))
        self.files.find = 0.02
        self.follow()
        await asyncio.sleep(0.05)
        self.assertEqual(self.server.inserted, [])
        os.makedirs(os.path.dirname(self.path))
        self.write(self.op("enqueue", "one"))
        self.follow()
        await self.until(lambda: self.server.types() == ["session_file", "message_queued"])

    async def test_written_only_after_the_call_it_is_found_still(self):
        os.rmdir(os.path.dirname(self.path))
        self.follow()                                  # `claude -p`: its one call, the record written after it
        await asyncio.sleep(0.05)
        os.makedirs(os.path.dirname(self.path))
        self.write({"type": "assistant", "isApiErrorMessage": True, "apiErrorStatus": 401, "timestamp": stamp(),
                    "message": {"role": "assistant", "content": [{"type": "text", "text": "Invalid API key"}]}})
        await self.until(lambda: self.server.types() == ["session_file", "turn_stopped"])     # no next call needed
        self.assertEqual(self.server.inserted[-1][1]["payload"]["status"], 401)

    async def test_a_running_task_s_output_growing_is_its_activity_until_it_ends(self):
        self.write(self.op("enqueue", "one"))
        self.follow()
        await self.until(lambda: len(self.server.inserted) == 2)
        out = os.path.join(self.tmp.name, "b1.output")
        with open(out, "w") as fh:
            fh.write("...")
        now = time.time()
        os.utime(out, (now - 30, now - 30))
        with unittest.mock.patch.object(session_files, "ACTIVITY_SECONDS", 0.0):
            self.files.task("g", SESSION, "b1", out)                   # the hook saw it start
            await self.until(lambda: self.server.types()[-1:] == ["task_activity"])
            self.assertEqual((self.server.inserted[-1][1]["payload"]["task"], round(self.server.inserted[-1][1]["payload"]["at"])),
                             ("b1", round(now - 30)))
            os.utime(out, (now, now))                                   # written again
            await self.until(lambda: self.server.types().count("task_activity") == 2)
            self.files.task("g", SESSION, "b1", None)                  # it ended
            os.utime(out, (now + 5, now + 5))
            await asyncio.sleep(0.1)
            self.assertEqual(self.server.types().count("task_activity"), 2)

    async def test_written_anew_it_is_read_from_its_start(self):
        self.write(self.op("enqueue", "a long first message"))
        self.follow()
        await self.until(lambda: len(self.server.inserted) == 2)
        with open(self.path, "w") as fh:
            fh.write(json.dumps(self.op("enqueue", "x")) + "\n")
        await self.until(lambda: len(self.server.inserted) == 3)
        self.assertEqual(self.server.inserted[-1][1]["payload"]["words"], "x")

    async def test_codex_s_rollout_by_its_thread(self):
        home = os.path.join(self.tmp.name, "codex")
        d = os.path.join(home, "sessions", "2026", "10", "26")
        os.makedirs(d)
        path = os.path.join(d, f"rollout-2026-10-26T10-00-00-{THREAD}.jsonl")
        with open(path, "w") as fh:
            for p in ({"type": "task_started", "turn_id": "t1"}, {"type": "turn_aborted", "turn_id": "t1"}):
                fh.write(json.dumps({"timestamp": stamp(), "type": "event_msg", "payload": p}) + "\n")
        self.files.follow("g", THREAD, Codex(), THREAD, None, home)
        await self.until(lambda: self.server.types() == ["session_file", "turn_stopped"])
        self.assertEqual(self.server.inserted[-1][1]["payload"]["how"], "interrupted")


class FollowerTest(unittest.TestCase):
    """The harness's own followers (harness_kit), a line at a time."""

    def test_a_line_is_read_once_it_is_whole(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
            fh.write(json.dumps({"type": "queue-operation", "operation": "enqueue", "timestamp": stamp(), "content": "a"}) + "\n")
            fh.write('{"type": "queue-operation", "operation": "enq')
        self.addCleanup(os.remove, fh.name)
        record = claude_rules.Record()
        facts, offset = follow(fh.name, record)
        self.assertEqual(([f.type for f in facts], offset), (["message_queued"], os.path.getsize(fh.name) - 45))
        with open(fh.name, "a") as out:
            out.write(f'ueue", "timestamp": "{stamp()}", "content": "b"}}\n')
        facts, offset = follow(fh.name, record, offset)
        self.assertEqual(([f.data["words"] for f in facts], offset), (["b"], os.path.getsize(fh.name)))

    def test_claude_code_s_question_answered_once_the_turn_goes_on_or_time_passes(self):
        record = claude_rules.Record()
        ask = {"type": "assistant", "timestamp": stamp(), "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_q", "name": "AskUserQuestion", "input": {}}]}}
        answer = {"type": "user", "timestamp": stamp(), "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_q", "content": "Large"}]}}
        self.assertEqual(record.take(json.dumps(ask).encode(), "0") + record.take(json.dumps(answer).encode(), "100"), [])
        self.assertEqual(record.due(time.time()), [])                                   # Esc's note could still come
        [settled] = record.due(time.time() + claude_rules.SETTLE_SECONDS)
        self.assertEqual((settled.type, settled.data["how"], settled.data["result"]), (Facts.ASK_SETTLED, "answered", "Large"))

    def test_claude_code_s_name_for_the_session_each_time_it_changes(self):
        record = ClaudeCode().follower(os.path.join("projects", "-work", f"{SESSION}.jsonl"))
        title = lambda text, session=SESSION: json.dumps(  # noqa: E731 - as Claude Code writes it, with no spaces
            {"type": "ai-title", "aiTitle": text, "sessionId": session}, separators=(",", ":")).encode()
        lines = [title("Lighthouse  keeper story"), title("Lighthouse keeper story"),        # written again, unchanged
                 title("Some other session", "another"), title(""), title("Night watch")]
        self.assertTrue(all(record.wanted(line) for line in lines))
        facts = [f for i, line in enumerate(lines) for f in record.take(line, str(i * 100))]
        self.assertEqual([(f.type, f.key, f.at, f.data) for f in facts],
                         [(Facts.NAMED, "0", None, {"text": "Lighthouse keeper story", "by": "claude"}),
                          (Facts.NAMED, "400", None, {"text": "Night watch", "by": "claude"})])
        self.assertFalse(record.wanted(json.dumps({"type": "custom-title", "customTitle": "Mine"}).encode()))

    def test_codex_s_subagent_report_once_its_own_rollout_has_it(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = os.path.join(tmp.name, "sessions", "2026", "10", "26")
        os.makedirs(d)
        parent = os.path.join(d, f"rollout-x-{THREAD}.jsonl")
        rollout = codex_rules.Rollout(parent)
        line = lambda p: json.dumps({"timestamp": stamp(), "type": "event_msg", "payload": p}).encode()   # noqa: E731
        rollout.take(line({"type": "task_started", "turn_id": "t1"}), "0")
        rollout.take(line({"type": "item_completed", "turn_id": "t1", "item": {
            "type": "SubAgentActivity", "kind": "started", "agent_thread_id": "sub", "agent_path": "/root/a"}}), "10")
        [ended] = rollout.take(line({"type": "item_completed", "turn_id": "t1", "item": {
            "type": "SubAgentActivity", "kind": "completed", "agent_thread_id": "sub"}}), "20")
        self.assertEqual((ended.type, ended.data["report"]), (Facts.TASK_ENDED, None))  # its rollout has none yet
        with open(os.path.join(d, "rollout-y-sub.jsonl"), "w") as fh:
            fh.write(line({"type": "task_complete", "turn_id": "s1", "last_agent_message": "done: 4"}).decode() + "\n")
        [report] = rollout.due(time.time())
        self.assertEqual((report.key, report.data["path"], report.data["report"]), ("20.report", "/root/a", "done: 4"))
        self.assertEqual(rollout.due(time.time()), [])


class URLTest(unittest.TestCase):
    """The launchers name the harness's own folder in the hook server's URL when one is set for the run."""

    def test_claude_code_s_config_folder(self):
        self.assertEqual(base_url("http://127.0.0.1:4113", "g", "/v1", 1000),
                         "http://127.0.0.1:4113/h/g/l/1000/v1")
        self.assertEqual(base_url("http://127.0.0.1:4113", "g", "/v1", 1000, "/x/claude"),
                         f"http://127.0.0.1:4113/h/g{config_part('/x/claude')}/l/1000/v1")
        self.assertEqual(claude_rules.record_dir("/x/claude"), "/x/claude")
        with unittest.mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": "/y/claude"}):
            self.assertEqual(claude_rules.record_dir(), "/y/claude")

    def test_codex_s_home(self):
        p = Plan("openai", "https://api.openai.com", "/v1", [], "/x/codex", run="42")
        self.assertEqual(p.base_url("http://127.0.0.1:4013", "g"), "http://127.0.0.1:4013/h/g/r/42/v1")
        p.home_set = True
        self.assertEqual(p.base_url("http://127.0.0.1:4013", "g"), f"http://127.0.0.1:4013/h/g/r/42{config_part('/x/codex')}/v1")


if __name__ == "__main__":
    unittest.main()
