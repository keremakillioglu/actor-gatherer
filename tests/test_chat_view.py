"""Chat's view (ag_dashboard/chat_view.py) where no recorded run reaches: a turn opening that a key typed into the
terminal stopped before the harness recorded anything of it -- a codex session's first message, stopped before the call
that makes its thread -- as the terminal's message box shows it after; a session whose process ended (its `ended`),
before a turn, as it worked, or after it was over; whether a hang-up took its message back, recorded by a hook
before it said (`_took`), or kept as the harness's record says (data.py's `on_esc`); Esc before any of the answer
with a message queued (tests/esc_runs); and a long message, which Claude Code keeps in the tags of what was pasted."""
import copy
import json
import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import chat_replay  # noqa: E402
from ag_dashboard import chat_view, data  # noqa: E402

SENT = {"cid": "p1", "text": "Hello", "at": 100.0}
#: A long message as Claude Code keeps and sends it: in the tags of what was pasted.
PASTED = '<pasted_content id="ab12">\n{0}\n</pasted_content id="ab12">'


def session(stopped_at=None, box=None, sent=(SENT,)):
    return {"sent": list(sent), "queued": [], "ended": 0, "stopped_at": stopped_at, "box": box}


class StoppedOpeningTest(unittest.TestCase):
    def test_a_stop_key_and_an_empty_box_stop_the_turn_it_opens(self):
        got = chat_view.unstored(session(100.4, "empty"), now=101.0)
        self.assertEqual((got["current"]["state"], got["current"]["turn"]), ("stopped", "opening"))
        self.assertEqual((got["opening"]["text"], got["opening"]["stopped"]["kind"]), ("Hello", "interrupted"))
        self.assertIsNone(got["taken_back"])

    def test_a_stop_key_and_the_message_back_in_its_box_take_it_back(self):
        got = chat_view.unstored(session(100.4, "holds"), now=101.0)
        self.assertIsNone(got["opening"])
        self.assertEqual(got["current"]["state"], "idle")
        self.assertEqual((got["taken_back"]["text"], got["taken_back"]["cid"], got["taken_back"]["since"]),
                         ("Hello", "p1", 100.0))

    def test_no_stop_key_after_it_or_a_box_not_known_leave_it_opening(self):
        for s in (session(), session(99.0, "empty"), session(100.4, None), session(100.4, "away")):
            with self.subTest(s):
                got = chat_view.unstored(s, now=101.0)
                self.assertEqual((got["current"]["state"], got["opening"].get("stopped")), ("opening", None))

    def test_one_the_harness_has_is_not_stopped_by_the_box(self):
        opening = {"text": "Hello", "cid": "p1", "began": 100.0, "seen": True, "unseen": False}
        self.assertEqual(chat_view._stop_on(opening, session(100.4, "empty")), (opening, None))


class EndedSessionTest(unittest.TestCase):
    """A session's `ended` stays once its process has ended, as it is run again (a terminal opened again): only the
    turn that was at work as it ended is closed."""

    def views(self, ended_after):
        """The run's last turn at each moment it was at work, and at its end, made with the session ended
        `ended_after` seconds after that turn began: [(state without the end, state with it)]."""
        run = chat_replay.load("claude-tool-call")
        out, end = [], None
        for m in chat_replay.moments(run):                  # each moment's gatherer: valid until the next
            base = (m.session or {}).get("session") or session(sent=())
            plain = chat_view.view(m.conn, run["channel"], base, m.at)
            turns = plain["turns"]
            if len(turns) < 2:
                continue
            ended = dict(base, ended=turns[-1]["began"] + ended_after)
            got = chat_view.view(m.conn, run["channel"], ended, m.at)["current"]
            end = (plain["current"]["state"], got["state"], (got["stopped"] or {}).get("kind"))
            if end[0] == "working":
                out.append(end)
        out.append(end)
        self.assertIn("working", [p for p, _, _ in out])
        self.assertEqual(out[-1][0], "done")
        return out

    def test_an_end_before_the_turn_began_leaves_it_as_it_is(self):
        for plain, state, kind in self.views(-5.0):
            self.assertEqual((state, kind), (plain, None))

    def test_an_end_as_the_turn_worked_closes_it(self):
        for plain, state, kind in self.views(0.01):
            self.assertEqual((state, kind), ("stopped", "closed") if plain == "working" else ("done", None))

    def test_an_end_after_the_turn_was_over_leaves_it_done(self):
        self.assertEqual(self.views(60.0)[-1][1:], ("done", None))


class AskedBeforeTest(unittest.TestCase):
    """A question an earlier turn asked that its record never settled -- its session closed as it asked, and resumed
    without it -- is not what the newest turn waits on."""

    def state(self, asked_after: float) -> dict:
        """The run at its end, with a question asked `asked_after` seconds after its last turn began, never settled."""
        run = chat_replay.load("claude-tool-call")
        conn = chat_replay.at_end(run)
        conn.execute("INSERT OR IGNORE INTO event_types (name, created_at) VALUES ('asked', '')")
        began = chat_view.view(conn, run["channel"], None)["turns"][-1]["began"]
        payload = {"at": began + asked_after, "call": "toolu_q", "kind": "question", "async": False, "turn": None,
                   "questions": [{"question": "Which one?", "options": [{"label": "A"}, {"label": "B"}]}]}
        conn.execute("INSERT INTO events (inserted_at, event_id, event_type_id, payload_json, tokens, p_channel) "
                     "SELECT '', 'asked:toolu_q', event_type_id, ?, 0, ? FROM event_types WHERE name = 'asked'",
                     (json.dumps(payload), run["channel"]))
        return chat_view.view(conn, run["channel"], None)["current"]

    def test_one_asked_before_the_newest_turn_opened_is_left_behind(self):
        got = self.state(-1.0)
        self.assertEqual((got["state"], got["asking"]), ("done", None))

    def test_one_the_newest_turn_asked_is_waited_on(self):
        got = self.state(1.0)
        self.assertEqual((got["state"], got["asking"]["call"]), ("asking", "toolu_q"))


class LostSendTest(unittest.TestCase):
    """A message the harness's record has as queued and never as sent held no turn open once it was stored -- the hook
    could not store its `message_sent` (the database locked): the harness had sent it -- nor once the harness's process
    ended after it was queued: Claude Code's queue lives in its process (`queue_ends_with_process`), so it never sends
    it, nor does a process resumed after; a guess its record makes later that one was sent is no message waiting."""

    def view(self, text: str, queued_after: float, ended_after: float = 0.0, guessed_after: float = 0.0,
             pasted: bool = False) -> dict:
        """The run at its end (its last turn over), with `text` queued `queued_after` seconds after its last turn's
        message was stored, and nothing after saying it was sent -- the session's process ended `ended_after` seconds
        after that message (0: never), and its record guessing it was sent `guessed_after` seconds after (0: none).
        `pasted`: long, as Claude Code keeps it, in the tags of what was pasted -- its words without them."""
        run = chat_replay.load("claude-tool-call")
        conn = chat_replay.at_end(run)
        at = chat_view.view(conn, run["channel"], None)["turns"][-1]["at"]
        kept = PASTED.format(text) if pasted else text
        payload = {"at": at + queued_after, "queued": "8.0a0b0c0d", "text": kept, "words": text,
                   "joins_after": at + queued_after + 1.0}
        facts = [("message_queued", "message_queued:x.jsonl:8.0a0b0c0d", payload)]
        if guessed_after:
            facts.append(("message_sent", "message_sent:x.jsonl:9.0a0b0c0d", {
                "at": at + guessed_after, "queued": "8.0a0b0c0d", "text": kept, "words": text, "how": "next",
                "joins": True, "written": at + queued_after}))
        for kind, event_id, p in facts:
            conn.execute("INSERT OR IGNORE INTO event_types (name, created_at) VALUES (?, '')", (kind,))
            conn.execute("INSERT INTO events (inserted_at, event_id, event_type_id, payload_json, tokens, p_channel) "
                         "SELECT '', ?, event_type_id, ?, 0, ? FROM event_types WHERE name = ?",
                         (event_id, json.dumps(p), run["channel"], kind))
        session = {"sent": [], "queued": [], "ended": at + ended_after} if ended_after else None
        return chat_view.view(conn, run["channel"], session)

    def test_stored_since_it_was_queued_the_turn_is_over(self):
        got = self.view("Run the shell command ls -la and tell me how many entries it lists.", -0.5)
        self.assertEqual((got["current"]["state"], got["waiting"]), ("done", []))

    def test_not_stored_the_harness_holds_it_and_goes_on(self):
        got = self.view("also count hidden files", 1.0)
        self.assertEqual(got["current"]["state"], "working")
        self.assertEqual(got["waiting"], [{"text": "also count hidden files", "cid": None, "how": "queued"}])

    def test_pasted_it_goes_by_its_words(self):
        got = self.view("Run the shell command ls -la and tell me how many entries it lists.", -0.5, pasted=True)
        self.assertEqual((got["current"]["state"], got["waiting"]), ("done", []))
        got = self.view("also count hidden files", 1.0, pasted=True)
        self.assertEqual((got["current"]["state"], got["waiting"]),
                         ("working", [{"text": "also count hidden files", "cid": None, "how": "queued"}]))

    def test_queued_before_its_process_ended_it_went_with_it(self):
        got = self.view("also count hidden files", 1.0, ended_after=2.0)
        self.assertEqual((got["current"]["state"], got["waiting"]), ("done", []))

    def test_queued_by_a_process_started_since_it_is_held_still(self):
        got = self.view("also count hidden files", 1.0, ended_after=-5.0)    # before this turn
        self.assertEqual((got["current"]["state"], [w["how"] for w in got["waiting"]]), ("working", ["queued"]))

    def test_a_guess_that_one_gone_with_its_process_was_sent_is_no_message_waiting(self):
        got = self.view("also count hidden files", 1.0, ended_after=2.0, guessed_after=600.0)
        self.assertEqual((got["current"]["state"], got["waiting"]), ("done", []))


class PastedHeldTest(unittest.TestCase):
    """A message held for its turn's end (tests/chat_runs/claude-held-message) that was long: Claude Code keeps it, and
    sends it, in the tags of what was pasted -- its record has its words without them, as ag stores them."""

    WORDS = "and say done at the end"

    def run_pasted(self) -> dict:
        run = copy.deepcopy(chat_replay.load("claude-held-message"))
        types = {t["event_type_id"]: t["name"] for t in run["event_types"]}
        kept = PASTED.format(self.WORDS)
        for e in run["events"]:
            kind = types[e["event_type_id"]]
            if kind in ("message_queued", "message_sent"):
                f = json.loads(e["payload_json"])
                if f.get("text") == self.WORDS:
                    e["payload_json"] = json.dumps(dict(f, text=kept))
            elif kind == "user_message" and e.get("text") == self.WORDS:
                f = json.loads(e["payload_json"])
                f["content"] = [dict(b, text=kept) for b in f["content"]]
                e.update(text=kept, payload_json=json.dumps(f))
        return run

    def test_once_sent_it_is_part_of_its_turn_and_waits_no_more(self):
        run = self.run_pasted()
        got = None
        for m in chat_replay.moments(run):
            got = chat_view.view(m.conn, run["channel"], (m.session or {}).get("session"), m.at)
            self.assertLessEqual(len(got["waiting"]), 1)        # one message waits: shown once, as sent or held
            for w in got["waiting"]:
                self.assertNotIn("pasted_content", w["text"])
        self.assertEqual((got["current"]["state"], got["waiting"]), ("done", []))
        self.assertEqual([x["text"] for x in got["turns"][-1]["more"]], [self.WORDS])


class TookBackTest(unittest.TestCase):
    """`_took`: a hang-up (Esc) at 10.0 on the call of row 5, "Hello", stored at 9.0."""

    SHOWN = [(5, "Hello", 9.0)]

    def took(self, takes_back=True, shown=SHOWN, prompts=(), words="Hello", **b):
        hang_up = dict({"read": 1, "row": 5, "reached": "nothing", "withdrawn": None, "at": 10.0}, **b)
        return chat_view._took(hang_up, words, list(shown), list(prompts), takes_back)

    def test_as_the_hook_says(self):
        self.assertTrue(self.took(withdrawn=True))
        self.assertFalse(self.took(withdrawn=False))
        self.assertFalse(self.took(withdrawn=True, reached="text"))     # its words had come: the harness keeps it
        self.assertFalse(self.took(withdrawn=True, words=None))         # no user's message of its own

    def test_an_older_hook_hid_what_it_withdrew(self):
        for takes_back in (True, False):
            self.assertTrue(self.took(takes_back=takes_back, shown=[]))
            self.assertFalse(self.took(takes_back=takes_back, shown=[], reached="text"))

    def test_shown_by_an_older_hook_it_goes_by_the_harness_sending_it_again(self):
        again = [{"text": "Hello", "sent": 9.0}, {"text": "Hello", "sent": 12.0}]
        for reached in ("nothing", None):
            self.assertTrue(self.took(reached=reached, prompts=again))   # ag kept its row for the message sent again
            self.assertFalse(self.took(reached=reached, prompts=again[:1]))   # a later call of its turn, a side call
            self.assertFalse(self.took(reached=reached, prompts=again, shown=self.SHOWN + [(8, "Hello", 12.1)]))
            self.assertFalse(self.took(reached=reached, prompts=[{"text": "Bye", "sent": 12.0}]))
        self.assertFalse(self.took(reached="text", prompts=again))       # its words had come: the harness keeps it

    def test_shown_by_an_older_hook_of_a_harness_that_keeps_it_it_is_not_taken_back(self):
        self.assertFalse(self.took(takes_back=False, prompts=[{"text": "Hello", "sent": 12.0}]))

    def test_not_one_the_harness_s_record_says_it_kept(self):
        self.assertFalse(self.took(withdrawn=True, kept=True))
        self.assertTrue(self.took(withdrawn=True, kept=False))


class OnEscTest(unittest.TestCase):
    """data.py's `on_esc`: Claude Code's record of a call hung up on, its message "Hello" sent as a turn's first at 10.0,
    the hang-up stored at 20.0."""

    def esc(self, facts=(), stops=(), said="Hello", after=None, until=float("inf")):
        sent = [("message_sent", {"how": "prompt", "at": 10.0, "words": "Hello", "text": "Hello"})]
        return data.on_esc(sent + list(facts), list(stops), said, 20.0, after, until)

    def test_nothing_in_its_record_since_its_send_it_took_it_back(self):
        self.assertEqual(self.esc(), (False, False))

    def test_an_interrupt_since_its_send_keeps_it_though_ag_read_the_call_after(self):
        self.assertEqual(self.esc(stops=[12.0], after=15.0), (True, False))
        self.assertEqual(self.esc(stops=[9.0]), (False, False))                  # the turn before's
        self.assertEqual(self.esc(stops=[12.0], until=11.0), (False, False))     # after ag read the next call
        self.assertEqual(self.esc([("message_sent", {"how": "prompt", "at": 11.0, "words": "Bye"})], stops=[12.0]),
                         (False, False))                                         # another turn's

    def test_from_its_newest_send_one_taken_back_and_sent_again(self):
        again = [("message_sent", {"how": "prompt", "at": 15.0, "words": "Hello"})]
        self.assertEqual(self.esc(again, stops=[12.0]), (False, False))
        self.assertEqual(self.esc(again, stops=[16.0]), (True, False))

    def test_a_message_queued_since_and_waiting_keeps_it(self):
        queued = [("message_queued", {"at": 12.0, "queued": "q1"})]
        self.assertEqual(self.esc(queued), (False, True))
        self.assertEqual(self.esc(queued + [("message_sent", {"how": "next", "at": 19.0, "queued": "q1"})]),
                         (False, True))                                          # sent at once on the Esc
        self.assertEqual(self.esc(queued + [("message_withdrawn", {"at": 13.0, "queued": "q1"})]), (False, False))
        self.assertEqual(self.esc([("message_queued", {"at": 9.0, "queued": "q0"})]), (False, False))   # before it

    def test_a_send_not_in_its_record_from_ag_s_read(self):
        self.assertEqual(self.esc(stops=[12.0], said="Other"), (False, False))
        self.assertEqual(self.esc(stops=[16.0], said="Other", after=15.0), (True, False))


ESC_RUNS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "esc_runs")


def esc_run(name: str) -> dict:
    with open(os.path.join(ESC_RUNS, name + ".json")) as fh:
        return json.load(fh)


def sent_unchanged(run: dict) -> dict:
    """The run as where Claude Code sends the message again unchanged, as it also does (seen live): ag withdraws the
    hung-up call's events once it has read the call, then restores the message as it stores the call that sends it
    again -- the same row, no new one."""
    run = copy.deepcopy(run)
    types = {t["event_type_id"]: t["name"] for t in run["event_types"]}
    first, again = [e for e in run["events"] if types[e["event_type_id"]] == "user_message"][:2]
    assert again["text"] == first["text"] + "\n"           # as recorded: joined with the next, Claude Code's newline
    run["events"].remove(again)
    read = next(r["_at"] for r in run["_reads"] if r["row_id"] == first["row_id"])
    stamp = datetime.fromtimestamp(read + 0.01, timezone.utc).isoformat()
    rows = [dict(r, withdrawn_at=stamp) for r in run["sampled"]["_withdrawn"][-1]["rows"]]
    run["sampled"]["_withdrawn"] = [{"at": read - 1.0, "rows": []}, {"at": read + 0.01, "rows": rows},
                                    {"at": read + 0.02, "rows": [r for r in rows if r["row_id"] != first["row_id"]]}]
    return run


class EscWithQueuedTest(unittest.TestCase):
    """Esc before any of the answer with a message queued (tests/esc_runs/claude-esc-with-queued.json, recorded live on
    a scratch home: a session's first message held by ag, a second written meanwhile -- queued --, then Esc). Claude Code
    stops the turn, keeps its message and sends the queued one at once; the hook still says none of the answer came and
    withdraws what the call stored. Kept apart from tests/chat_runs: as ag records the hang-up seconds late, behind the
    next call's read, Chat's view shows the message twice for a while there (ag_dashboard/TODO.md)."""

    def views(self, run: dict):
        return [(m.at, m.conn, chat_view.view(m.conn, run["channel"], (m.session or {}).get("session"), m.at))
                for m in chat_replay.moments(run)]

    def check_end(self, run: dict):
        views = self.views(run)
        _, conn, v = views[-1]
        self.assertEqual([(t["text"].strip(), [m["text"] for m in t["more"]]) for t in v["turns"]],
                         [("Write a haiku about autumn leaves.", ["Make it rhyme."])])
        self.assertEqual((v["current"]["state"], v["opening"], v["waiting"], v["taken_back"]), ("done", None, [], None))
        failed = next(e["_at"] for e in run["events"]
                      if {t["event_type_id"]: t["name"] for t in run["event_types"]}[e["event_type_id"]] == "call_failed")
        for at, conn, v in views:                           # from the hang-up on: the message never taken back
            if at >= failed:
                self.assertIn("Write a haiku about autumn leaves.",
                              [t["text"].strip() for t in v["turns"]], at)
                self.assertIsNone(v["taken_back"], at)

    def test_sent_again_unchanged_its_turn_stays_with_the_queued_message(self):
        self.check_end(sent_unchanged(esc_run("claude-esc-with-queued")))

    def test_sent_again_with_claude_code_s_newline_it_shows_once(self):
        """As recorded: the message sent again joined with the queued one, with Claude Code's newline -- stored as a new
        row, the old one left withdrawn (data.py's `sent_again`)."""
        self.check_end(esc_run("claude-esc-with-queued"))


if __name__ == "__main__":
    unittest.main()
