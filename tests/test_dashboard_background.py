"""What Claude Code still runs in the background for a session -- a command, an agent, a monitor it
started and has not been told have ended -- as the dashboard reads it from the gatherer's events
(data.py's `background`), and the BACKGROUND status of a session whose turn is over while one runs."""
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ag_dashboard import data  # noqa: E402
from ag_dashboard import home as dashboard_home  # noqa: E402

NOTICE = ("[SYSTEM NOTIFICATION - NOT USER INPUT]\nThis is an automated background-task event, NOT a message from the "
          "user.\n\n<task-notification>\n<task-id>{id}</task-id>\n<tool-use-id>toolu_x</tool-use-id>\n{rest}"
          "</task-notification>")


def call(cid, name, inp):
    return ("tool_call", {"role": "assistant", "content": [{"type": "tool_use", "id": cid, "name": name, "input": inp}]}, None)


def result(cid, text):
    words = text if isinstance(text, str) else "\n".join(b["text"] for b in text)     # ag's text: the blocks' words
    return ("tool_output", {"role": "user", "content": [{"type": "tool_result", "tool_use_id": cid, "content": text}]}, words)


def said(text):
    return ("agent_message", {"role": "assistant", "content": [{"type": "text", "text": text}]}, text)


def asked(text):
    return ("user_message", {"role": "user", "content": [{"type": "text", "text": text}]}, text)


def notice(task_id, status=None, event=None, waiting=False):
    rest = (f"<status>{status}</status>\n<summary>done</summary>\n" if status else "") + \
           ("<note>This agent stopped with background work of its own still running. It may resume on its own "
            "when that work completes or reports, and the same task-id notifies again if it does.</note>\n" if waiting else "") + \
           (f"<summary>Monitor event</summary>\n<event>{event}</event>\n" if event else "")
    text = NOTICE.format(id=task_id, rest=rest)
    return ("context", {"role": "user", "content": [{"type": "text", "text": text}]}, text)


def command(cid, task_id, output, description="Run the server"):
    return [call(cid, "Bash", {"command": "python -m http.server", "description": description, "run_in_background": True}),
            result(cid, f"Command running in background with ID: {task_id}. Output is being written to: {output}. "
                        "You will be notified when it completes.")]


def subagent(cid, agent_id, output, description="Draw the animals"):
    return [call(cid, "Agent", {"description": description, "prompt": "Draw them.", "run_in_background": True}),
            result(cid, [{"type": "text", "text": "Async agent launched successfully. (internal)\nagentId: "
                                                  f"{agent_id} (internal ID)\nThe agent is working in the background.\n"
                                                  f"output_file: {output}\nDo NOT Read it."}])]


def monitor(cid, task_id, description="errors in the log"):
    return [call(cid, "Monitor", {"command": "tail -f log | grep ERROR", "description": description, "timeout_ms": 60000}),
            result(cid, f"Monitor started (task {task_id}, expires in 1m unless the source ends first).")]


class BackgroundTest(unittest.TestCase):
    """A gatherer database of the test's own, its events written as Claude Code's reach ag."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.saved, dashboard_home.HOME = dashboard_home.HOME, self.tmp.name
        self.addCleanup(setattr, dashboard_home, "HOME", self.saved)
        os.makedirs(os.path.join(self.tmp.name, "gatherers", "g"))
        self.path = os.path.join(self.tmp.name, "gatherers", "g", "context.db")
        conn = sqlite3.connect(self.path)
        conn.executescript("""CREATE TABLE event_types (event_type_id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL);
            CREATE TABLE events (row_id INTEGER PRIMARY KEY, inserted_at TEXT NOT NULL, event_id TEXT, event_type_id INTEGER NOT NULL,
              payload_json TEXT NOT NULL, tokens INTEGER NOT NULL, text TEXT, counted INTEGER, p_channel);""")
        conn.commit()
        conn.close()
        self.out = os.path.join(self.tmp.name, "tasks")
        os.makedirs(self.out)
        self.add([asked("start the server and draw the animals")])

    def add(self, events, at=None, channel="s1"):
        """`events` stored for `channel`, `at` seconds since the epoch (now)."""
        stamp = datetime.fromtimestamp(time.time() if at is None else at, timezone.utc).isoformat()
        conn = sqlite3.connect(self.path)
        for typ, payload, text in events:
            conn.execute("INSERT OR IGNORE INTO event_types (name, created_at) VALUES (?, ?)", (typ, stamp))
            tid = conn.execute("SELECT event_type_id FROM event_types WHERE name = ?", (typ,)).fetchone()[0]
            conn.execute("INSERT INTO events (inserted_at, event_type_id, payload_json, tokens, text, p_channel) "
                         "VALUES (?, ?, ?, 1, ?, ?)", (stamp, tid, json.dumps(payload), text, channel))
        conn.commit()
        conn.close()

    def output(self, name, age=0.0):
        """A task's output file, last written `age` seconds ago."""
        path = os.path.join(self.out, f"{name}.output")
        with open(path, "w") as fh:
            fh.write("...")
        os.utime(path, (time.time() - age, time.time() - age))
        return path

    def actor(self, started=(), channel="s1"):
        return next(a for g in data.home(list(started))["gatherers"] for a in g["agents"] if a["channel"] == channel)

    def session(self, pid=4242, since=None, **more):
        return {"session_id": "s1", "gatherer": "g", "cwd": "/", "harness": "claude", "permission_mode": "auto",
                "created_at": "2026-01-01T00:00:00+00:00", "turns": 1, "status": "idle", "last_error": None, "kept": 0,
                "queued": [], "terminal": True, "fullscreen": False, "pid": pid, "since": since, **more}

    def test_a_command_runs_until_its_notification_with_a_status(self):
        out = self.output("b1")
        self.add(command("t1", "b1", out) + [said("The server is starting.")])
        a = self.actor([self.session()])
        self.assertEqual((a["status"], a["running"]), (data.BACKGROUND, True))      # its turn over, not its work
        (task,) = a["background"]
        self.assertEqual((task["id"], task["kind"], task["label"], task["output"]), ("b1", "command", "Run the server", out))
        self.add([notice("b1", "completed"), said("It finished.")])
        a = self.actor([self.session()])
        self.assertEqual((a["status"], a["background"]), (data.IDLE, []))

    def test_an_agent_and_a_monitor_and_a_stopped_command(self):
        self.add(subagent("t1", "a7f3", self.output("a7f3")) + monitor("t2", "m1") + command("t3", "b2", self.output("b2"))
                 + [said("Three things run.")])
        a = self.actor([self.session()])
        self.assertEqual([(t["kind"], t["id"], t["label"]) for t in a["background"]],
                         [("agent", "a7f3", "Draw the animals"), ("monitor", "m1", "errors in the log"), ("command", "b2", "Run the server")])
        self.add([notice("m1", event="ERROR: disk full")])                          # a monitor's event: it still runs
        self.add([call("t4", "TaskStop", {"task_id": "b2"}),
                  result("t4", '{"message":"Successfully stopped task: b2 (python -m http.server)","task_id":"b2"}'),
                  said("Stopped it.")])
        a = self.actor([self.session()])
        self.assertEqual([t["id"] for t in a["background"]], ["a7f3", "m1"])
        self.assertEqual(a["background"][1]["event"], "ERROR: disk full")
        self.add([notice("a7f3", "completed"), notice("m1", "completed"), said("All done.")])
        self.assertEqual(self.actor([self.session()])["background"], [])

    def test_an_agent_ends_with_its_report_handed_back_before_its_notification(self):
        self.add(subagent("t1", "a7f3", self.output("a7f3")) + [said("It runs.")])
        self.assertEqual(self.actor([self.session()])["status"], data.BACKGROUND)
        self.add([asked('Another Claude session sent a message:\n<agent-message from="a7f3">\n[Subagent hand-back] The text '
                        'below is the final report of a subagent.\n  Done.\n</agent-message>'), said("It reported.")])
        a = self.actor([self.session()])
        self.assertEqual((a["status"], a["background"]), (data.IDLE, []))
        self.add([notice("a7f3", "completed")])                                    # the notification, later: nothing more
        self.assertEqual(self.actor([self.session()])["background"], [])

    def test_an_agent_resumed_by_a_message_runs_again_until_it_reports(self):
        out = self.output("a7f3")
        self.add(subagent("t1", "a7f3", out) + [said("It runs."),
                 asked('Another Claude session sent a message:\n<agent-message from="a7f3">\n[Subagent hand-back] Done.\n</agent-message>'),
                 said("It reported.")])
        self.assertEqual(self.actor([self.session()])["status"], data.IDLE)
        self.add([asked("ask it to count again"),
                  call("t2", "SendMessage", {"to": "a7f3", "summary": "Count again", "message": "Count to 100."}),
                  result("t2", '{"success":true,"message":"Resuming agent a7f3","resumedAgentId":"a7f3","pin":{"id":"a7f3"}}'),
                  said("Asked it.")])
        a = self.actor([self.session()])
        self.assertEqual(a["status"], data.BACKGROUND)
        self.assertEqual([(t["id"], t["kind"], t["label"], t["output"]) for t in a["background"]], [("a7f3", "agent", "Count again", out)])
        self.add([asked('Another Claude session sent a message:\n<agent-message from="a7f3">\n[Subagent hand-back] Counted.\n</agent-message>'),
                  said("It counted.")])
        self.assertEqual(self.actor([self.session()])["background"], [])

    def test_an_agent_waiting_on_its_own_background_work_has_not_ended(self):
        self.add(subagent("t1", "a7f3", self.output("a7f3")) + [said("It runs.")])
        self.add([notice("a7f3", "completed", waiting=True), said("It waits on its own work.")])
        a = self.actor([self.session()])
        self.assertEqual((a["status"], a["background"][0]["event"]), (data.BACKGROUND, "waiting on its own background work"))
        self.add([notice("a7f3", "completed"), said("It finished.")])               # notified again: now it has
        self.assertEqual(self.actor([self.session()])["background"], [])

    def test_a_monitor_ends_when_it_expires(self):
        self.add(monitor("t1", "m1") + [said("Watching.")])
        self.add([notice("m1", event="tick 1")])
        self.assertEqual(self.actor([self.session()])["background"][0]["event"], "tick 1")
        self.add([notice("m1", event="[Monitor expired after 5m with 1 events delivered. Re-arm it if you still need the watch.]"),
                  said("It expired.")])
        self.assertEqual(self.actor([self.session()])["background"], [])

    def test_words_that_only_quote_a_start_or_an_end_are_neither(self):
        self.add(command("t1", "b1", self.output("b1")))
        self.add([call("t2", "Bash", {"command": "sqlite3 context.db ..."}),
                  result("t2", "853|context|" + NOTICE.format(id="b1", rest="<status>failed</status>\n")),   # a notice, read back
                  call("t3", "Bash", {"command": "grep ..."}),
                  result("t3", "log: Command running in background with ID: b9. Output is being written to: /x/b9.output"),
                  said("Looked.")])
        a = self.actor([self.session()])
        self.assertEqual([t["id"] for t in a["background"]], ["b1"])
        self.add([notice("b1", "completed")], channel="s2")                        # another session's: not this one's
        self.assertEqual([t["id"] for t in self.actor([self.session()])["background"]], ["b1"])

    def test_none_once_the_process_is_gone_or_a_later_one_has_the_session(self):
        self.add(command("t1", "b1", self.output("b1")) + [said("Started.")], at=time.time() - 60)
        self.assertEqual(len(self.actor([self.session(since=time.time() - 120)])["background"]), 1)
        self.assertEqual(self.actor([self.session(since=time.time() - 10)])["background"], [])   # started after it: not its
        self.assertEqual(self.actor([self.session(pid=None, kept=time.time())])["background"], [])   # the dashboard's end took it
        a = {"status": data.IDLE, "alive": False, "background": [{"id": "b1", "started": time.time(), "output": None}]}
        data._settle_background(a, time.time())
        self.assertEqual((a["status"], a["background"]), (data.IDLE, []))

    def test_with_no_process_to_ask_one_with_no_sign_of_life_for_long_is_over(self):
        old = time.time() - data.STALE_SECONDS - 60
        self.add(command("t1", "b1", self.output("b1", age=data.STALE_SECONDS + 60))
                 + command("t2", "b2", self.output("b2", age=5)) + [said("Two started.")], at=old)
        a = self.actor()                                                           # no session the dashboard runs: not known
        self.assertEqual([t["id"] for t in a["background"]], ["b2"])                # its output written 5 s ago
        self.assertGreater(a["background"][0]["active"], time.time() - 30)

    def test_only_the_rows_added_since_are_read_again(self):
        self.add(command("t1", "b1", self.output("b1")))
        self.assertEqual(len(self.actor([self.session()])["background"]), 1)
        cached = data._BACKGROUND[next(p for p in data._BACKGROUND if os.path.basename(self.tmp.name) in p)]
        self.assertGreater(cached["row"], 0)
        self.add([notice("b1", "killed")])
        self.assertEqual(self.actor([self.session()])["background"], [])


if __name__ == "__main__":
    unittest.main()
