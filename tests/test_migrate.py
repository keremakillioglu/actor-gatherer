"""An older gatherer's tables -- what ag kept before its hooks recorded it as events -- copied into records once
(ag/integrations/tools/ag_orchestrator/migrate.py, through ag's server's `old_tables`, `insert` and `migrated`), and the
dashboard then reading the records as it read the tables (ag_dashboard/migrating.py starts the copy)."""
import asyncio
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ag.ag_harness import home as ag_home  # noqa: E402
from ag.ag_harness.server import serve  # noqa: E402
from ag.ag_harness.server.__main__ import server_for  # noqa: E402
from ag.ag_harness.store import paths  # noqa: E402
from ag.integrations.harnesses.claude.adaptor.adaptor import ClaudeAdaptor  # noqa: E402
from ag.integrations.tools.ag_orchestrator import migrate  # noqa: E402
from ag_dashboard import data, files, migrating  # noqa: E402
from ag_dashboard import home as dashboard_home  # noqa: E402

CALL = {"type": "tool_use", "id": "toolu_1", "name": "Read", "input": {"file_path": "/w/rows.csv"}}
RESULT = {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "1\ta,b\n2\t1,2"}]}
SAID = {"role": "assistant", "content": [{"type": "text", "text": "There are 42 rows."}]}
# The old tables, as an older ag made them (store/schema.py before step 6)
OLD = """CREATE TABLE _pending (pending_id INTEGER PRIMARY KEY, received_at TEXT NOT NULL, answer TEXT, stop TEXT,
           type TEXT NOT NULL, payload_json TEXT NOT NULL, text TEXT, p_channel, p_cwd);
         CREATE TABLE _recaps (recap_id INTEGER PRIMARY KEY, session TEXT NOT NULL, made_at TEXT NOT NULL, text TEXT NOT NULL);
         CREATE TABLE _names (session TEXT NOT NULL, by TEXT NOT NULL, named_at TEXT NOT NULL, text TEXT NOT NULL,
           PRIMARY KEY (session, by));
         CREATE TABLE _touches (touch_id INTEGER PRIMARY KEY, session TEXT NOT NULL, call_id TEXT NOT NULL, at TEXT NOT NULL,
           path TEXT, how TEXT, checked INTEGER, named INTEGER, detail_json TEXT);"""


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


class MigrateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.saved = paths.TRACE_DIR, paths.AG_HOME, dashboard_home.HOME
        paths.AG_HOME = dashboard_home.HOME = os.path.join(self.tmp.name, "ag")
        paths.TRACE_DIR = os.path.join(paths.AG_HOME, "gatherers")
        ag_home._HOMES.clear()
        self.addCleanup(self.restore)
        # a session's turn as an older hook server stored it: its conversation and a read, no model_call
        got, = self.ask({"op": "rewrite", "gatherer": "g", "properties": {"channel": "s"}, "cwd": "/w",
                         "events": ClaudeAdaptor().to_events([{"role": "user", "content": "count the rows"},
                                                               {"role": "assistant", "content": [CALL]}, RESULT])})
        self.read_id = got["read_id"]
        self.ask({"op": "insert", "gatherer": "g", "properties": {"channel": "x"}, "events": [   # a codex thread's
            {"type": "user_message", "payload": {"type": "message", "role": "user", "content": [
                {"type": "input_text", "text": "hi"}]}, "text": "hi"}]})
        self.t = 1_790_000_000.0                                    # what the old tables kept, and when
        conn = sqlite3.connect(paths.db_path("g"))
        conn.executescript(OLD)
        conn.execute("INSERT INTO _recaps (session, made_at, text) VALUES ('s', ?, 'Counting rows; next, the columns.')",
                     (iso(self.t),))
        conn.execute("INSERT INTO _names (session, by, named_at, text) VALUES ('x', 'codex', ?, 'Say hi')", (iso(self.t + 1),))
        conn.execute("INSERT INTO _touches (session, call_id, at, path, how, checked, named, detail_json) VALUES "
                     "('s', 'toolu_1', ?, '/w/rows.csv', 'read', 1, 1, '{}')", (iso(self.t + 2),))
        conn.execute("INSERT INTO _pending (received_at, answer, stop, type, payload_json, text, p_channel, p_cwd) VALUES "
                     "(?, 'msg_9', 'end_turn', 'agent_message', ?, 'There are 42 rows.', 's', '/w')",
                     (iso(self.t + 3), json.dumps(SAID)))
        conn.execute("UPDATE _reads SET read_at = ?, error_status = 529, error = 'overloaded_error: Overloaded', "
                     "answered_at = ? WHERE read_id = ?", (iso(self.t + 3), iso(self.t + 4), self.read_id))
        conn.commit()
        conn.close()

    def restore(self):
        paths.TRACE_DIR, paths.AG_HOME, dashboard_home.HOME = self.saved
        ag_home._HOMES.clear()

    def ask(self, *requests):
        out = io.StringIO()
        serve(server_for(), [json.dumps(dict(r, id=i)) for i, r in enumerate(requests, 1)], out)
        return [json.loads(line) for line in out.getvalue().splitlines()]

    def migrate(self):
        test = self

        class Client:                                         # ag's server, as the harness side's AgClient asks it
            async def request(self, op, body):
                got, = test.ask({"op": op, **body})
                return {k: v for k, v in got.items() if k != "id"}
        return asyncio.run(migrate.migrate(Client(), "g"))

    def records(self, kind):
        conn = sqlite3.connect(paths.db_path("g"))
        try:
            return [(ch, at, json.loads(p)) for ch, at, p in conn.execute(
                "SELECT e.p_channel, e.inserted_at, e.payload_json FROM events e JOIN event_types t USING (event_type_id) "
                "WHERE t.name = ? ORDER BY e.row_id", (kind,))]
        finally:
            conn.close()

    def agents(self):
        return {a["channel"]: a for g in data.home([])["gatherers"] for a in g["agents"]}

    def test_each_old_table_copied_once_at_the_time_it_kept(self):
        self.assertTrue(migrating.due("g"))
        self.assertEqual(self.migrate(), {"recap": 1, "name": 1, "file_touched": 1, "reply_part": 1, "reply_end": 2,
                                          "call_failed": 1, "harness": 2})
        self.assertEqual(self.records("recap"), [("s", iso(self.t), {"text": "Counting rows; next, the columns."})])
        self.assertEqual([(ch, p) for ch, _, p in self.records("harness")],
                         [("s", {"harness": "claude"}), ("x", {"harness": "codex"})])       # as their pieces' shapes tell
        (_, at, failed), = self.records("call_failed")
        self.assertEqual((at, failed["status"]), (self.read_at(), 529))                     # at its read's time
        self.assertIsNone(self.migrate())                                                    # copied once
        self.assertFalse(migrating.due("g"))
        self.assertEqual(len(self.records("recap")), 1)

    def read_at(self):
        conn = sqlite3.connect(paths.db_path("g"))
        try:
            return conn.execute("SELECT read_at FROM _reads WHERE read_id = ?", (self.read_id,)).fetchone()[0]
        finally:
            conn.close()

    def test_the_dashboard_reads_them_as_it_read_the_tables(self):
        self.migrate()
        s, x = self.agents()["s"], self.agents()["x"]
        self.assertEqual((s["harness"], x["harness"]), ("claude", "codex"))
        self.assertEqual((s["recap"]["text"], s["recap"]["at"]), ("Counting rows; next, the columns.", self.t))
        self.assertEqual(x["name"], {"text": "Say hi", "by": "codex"})
        self.assertEqual(s["last"], self.t + 4)                                  # when its answer came, as its read kept it
        self.assertEqual([i["text"] for i in data.agent("g", "s", [])["pending"]], ["There are 42 rows."])
        self.assertEqual(s["turn_over"], True)                                   # its last answer, ended (end_turn)
        conn = data._connect("g")
        try:
            (newest,) = data._newest_reads(conn, "s", 1)
        finally:
            conn.close()
        self.assertEqual((newest["error_status"], newest["error"]), (529, "overloaded_error: Overloaded"))
        got = files.files("g", "s", None, "/w")
        self.assertEqual([(f["path"], f["kinds"]) for f in got["files"]], [("/w/rows.csv", ["read"])])
        self.assertTrue(got["files"][0]["sources"][0]["checked"])                # as the hook found it on disk

    def test_a_channel_s_own_records_win(self):
        self.ask({"op": "insert", "gatherer": "g", "properties": {"channel": "s"}, "events": [
            {"type": "recap", "id": "recap:new", "payload": {"text": "A newer recap."}},
            {"type": "model_call", "id": "call:1", "payload": {"kind": "turn", "harness": "claude", "version": "2.1.311"}}]})
        got = self.migrate()
        self.assertNotIn("recap", got)                                            # it has one: the table's is older
        self.assertEqual(got["harness"], 1)                                       # x's only: s's calls say
        self.assertEqual(self.agents()["s"]["recap"]["text"], "A newer recap.")

    def test_a_gatherer_with_no_old_tables_is_not_due(self):
        self.ask({"op": "insert", "gatherer": "new", "properties": {"channel": "c"}, "events": [
            {"type": "user_message", "payload": {"role": "user", "content": "hi"}, "text": "hi"}]})
        self.assertFalse(migrating.due("new"))
        self.assertFalse(migrating.due("nowhere"))


if __name__ == "__main__":
    unittest.main()
