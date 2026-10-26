"""harness_kit: each harness's rules, apart from ag -- what its calls are, what each piece of its conversation is,
what its tools do."""
import ast
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import harness_kit  # noqa: E402
from harness_kit import Action, CallKind, Kind  # noqa: E402
from harness_kit.claude import RETRY_NOTES  # noqa: E402

CLAUDE, CODEX = harness_kit.get("claude"), harness_kit.get("codex")


def user(text):
    return {"role": "user", "content": [{"type": "text", "text": text}]}


def said(text):
    return {"role": "assistant", "content": [{"type": "text", "text": text}]}


def item(role, text):
    return {"type": "message", "role": role, "content": [
        {"type": "input_text" if role == "user" else "output_text", "text": text}]}


class SeparateTest(unittest.TestCase):
    def test_it_imports_nothing_but_the_standard_library_and_itself(self):
        root = os.path.dirname(harness_kit.__file__)
        for name in os.listdir(root):
            if not name.endswith(".py"):
                continue
            with open(os.path.join(root, name)) as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                mods = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                    [node.module or ""] if isinstance(node, ast.ImportFrom) and not node.level else []
                for m in mods:
                    self.assertNotIn(m.split(".")[0], ("ag", "ag_dashboard"), f"{name} imports {m}")
                    self.assertIn(m.split(".")[0], sys.stdlib_module_names, f"{name} imports {m}")


class ClaudeCodeTest(unittest.TestCase):
    def kinds(self, *messages):
        return [(p.kind, p.words) for p in CLAUDE.read(CLAUDE.items(list(messages)))]

    def test_the_user_s_words_as_they_typed_them(self):
        wrapped = ("The user sent a new message while you were working:\nalso b\n\nThis is how Claude Code surfaces "
                   "messages the user sends mid-turn — within the running turn.")
        self.assertEqual(self.kinds(user("hi"), user("<bash-input>ls -la</bash-input>"), user(wrapped),
                                    user('a <pasted_content id="5">long</pasted_content id="5"> b')),
                         [(Kind.USER, "hi"), (Kind.USER_COMMAND, "! ls -la"), (Kind.MID_TURN, "also b"),
                          (Kind.USER, "a\n\nlong\n\nb")])

    def test_a_typed_command_is_the_user_s_and_its_prompt_claude_code_s(self):
        typed = user("<command-message>greet</command-message>\n<command-name>/greet</command-name>\n"
                     "<command-args>Bob</command-args>")
        self.assertEqual(self.kinds(typed, user("Say hi to Bob."), said("Hi Bob")),
                         [(Kind.USER_COMMAND, "/greet Bob"), (Kind.COMMAND_PROMPT, None), (Kind.AGENT, None)])

    def test_its_own_notes_each_of_its_kind(self):
        notes = {"<system-reminder>x</system-reminder>": Kind.ENVIRONMENT,
                 "[Request interrupted by user]": Kind.INTERRUPT,
                 "Base directory for this skill: /s/greet\n\nSay hi.": Kind.SKILL,
                 "<bash-stdout>a\n</bash-stdout><bash-stderr></bash-stderr>": Kind.COMMAND_OUTPUT,
                 "<command-name>/context</command-name>\n<command-message>context</command-message>": Kind.LOCAL_COMMAND,
                 "[Image: original 1400x2400, displayed at 1167x2000.]": Kind.ATTACHMENT_NOTE,
                 "Stop hook feedback:\nnot yet": Kind.HOOK_FEEDBACK,
                 "Tool loaded.": Kind.TOOL_NOTICE, RETRY_NOTES[0]: Kind.RETRY_NOTE}
        for text, kind in notes.items():
            self.assertEqual(self.kinds(user(text)), [(kind, None)], text)
        report = user('Another Claude session sent a message:\n<agent-message from="a1b2">\n[Subagent hand-back] The '
                      'report follows:\n  Done.\n</agent-message>')
        peer = user('Another Claude session sent a message:\n<cross-session-message from="uds:/s" from-name="other">\n'
                    'hello\n</cross-session-message>')
        got = CLAUDE.read(CLAUDE.items([report, peer]))
        self.assertEqual([(p.kind, p.detail.get("from") or p.detail.get("name"), p.detail["text"]) for p in got],
                         [(Kind.AGENT_REPORT, "a1b2", "Done."), (Kind.PEER_MESSAGE, "other", "hello")])
        skill, = CLAUDE.read(CLAUDE.items([user("Base directory for this skill: /s/greet\n\nSay hi.\n\nARGUMENTS: Bob")]))
        self.assertEqual((skill.detail["name"], skill.detail["args"], skill.detail["instructions"]), ("greet", "Bob", "Say hi."))
        system, = CLAUDE.read(CLAUDE.items([{"role": "system", "content": "<task-notification><task-id>t1</task-id>"
                                                                          "<status>completed</status></task-notification>"}]))
        self.assertEqual((system.kind, system.detail["notices"][0]["id"], system.detail["notices"][0]["ended"]),
                         (Kind.TASK_NOTICE, "t1", True))

    def test_a_compacted_history_s_summary_and_what_it_sends_again(self):
        summary = user("This session is being continued from a previous conversation that ran out of context. ...")
        got = CLAUDE.read(CLAUDE.items([summary, user("<system-reminder>env</system-reminder>"), user("go on"),
                                        user("<system-reminder>late</system-reminder>"), said("ok")]))
        self.assertEqual([p.kind for p in got], [Kind.COMPACTION_SUMMARY, Kind.COMPACTION_REPEAT, Kind.USER,
                                                 Kind.COMPACTION_REPEAT, Kind.AGENT])
        self.assertTrue(got[0].detail["opens"])

    def test_tool_calls_say_what_they_do_and_results_the_tasks_they_start(self):
        call = {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": "/a.py", "old_string": "x"}},
            {"type": "tool_use", "id": "t2", "name": "AskUserQuestion", "input": {"questions": [
                {"question": "Which?", "header": "Pick", "options": [{"label": "A"}, {"label": "B"}]}]}},
            {"type": "tool_use", "id": "t3", "name": "ExitPlanMode", "input": {}}]}
        result = {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t4", "content": "Command running in background with ID: b77. "
                                                                     "Output is being written to: /tmp/b77.output"},
            {"type": "tool_result", "tool_use_id": "t5", "content": "Successfully stopped task: b77"}]}
        edit, ask, plan, started, stopped = CLAUDE.read(CLAUDE.items([call, result]))
        self.assertEqual((edit.tool.action, edit.tool.paths, edit.tool.ask), (Action.EDIT, ["/a.py"], None))
        self.assertEqual((ask.tool.action, ask.tool.ask["kind"], [o["label"] for o in ask.tool.ask["questions"][0]["options"]]),
                         (Action.ASK, "question", ["A", "B"]))
        self.assertEqual(plan.tool.ask, {"kind": "plan", "plan": None})          # the plan is in its file, not the call
        self.assertEqual((started.result.task["kind"], started.result.task["how"], started.result.task["output"]),
                         ("command", "started", "/tmp/b77.output"))
        self.assertEqual((stopped.result.task["id"], stopped.result.task["how"]), ("b77", "stopped"))

    def test_what_each_call_is(self):
        tools = [{"name": "Read"}]
        turn = {"messages": [user("hi")], "tools": tools}
        call = CLAUDE.call("POST", "/v1/messages", {"X-Claude-Code-Session-Id": "s1", "User-Agent": "claude-cli/2.1.310 (x)"}, turn)
        self.assertEqual((call.kind, call.session, call.version), (CallKind.TURN, "s1", "2.1.310"))
        recap = {"messages": [user("hi"), said("ok"), user("The user stepped away and is coming back. Recap.")], "tools": tools}
        call = CLAUDE.call("POST", "/v1/messages", {}, recap)
        self.assertEqual((call.kind, len(call.history), len(call.own)), (CallKind.RECAP, 2, 1))
        compact = {"messages": [user("hi"), said("ok"), user("CRITICAL: Respond with TEXT ONLY. Summarize.")], "tools": tools}
        self.assertEqual(CLAUDE.call("POST", "/v1/messages", {}, compact).kind, CallKind.COMPACTION)
        self.assertEqual(CLAUDE.call("POST", "/v1/messages", {"X-Claude-Code-Agent-Id": "a"}, turn).kind, CallKind.SUBAGENT)
        self.assertEqual(CLAUDE.call("POST", "/v1/messages", {}, {"messages": [user("title?")]}).kind, CallKind.OTHER)
        self.assertIsNone(CLAUDE.call("GET", "/v1/models", {}, None))


class CodexTest(unittest.TestCase):
    def test_its_own_context_its_replies_and_its_agents_messages(self):
        reply = item("user", '<send_user_message_question_reply>\n[{"answer":"mango","question":"Which fruit?",'
                             '"questionItemId":"[\\"request_user_input_async\\",\\"c1\\",0]"}]\n</send_user_message_question_reply>')
        report = {"type": "agent_message", "author": "/root/a", "content": [{"type": "input_text", "text":
                  "Message Type: FINAL_ANSWER\nTask name: a\nSender: /root/a\nPayload:\nDone."}]}
        got = CODEX.read([item("user", "<environment_context><cwd>/w</cwd></environment_context>"), item("user", "hi"),
                          reply, report, item("user", "<turn_aborted>x</turn_aborted>")])
        self.assertEqual([(p.kind, p.words) for p in got],
                         [(Kind.ENVIRONMENT, None), (Kind.USER, "hi"), (Kind.ASK_REPLY, "Which fruit? → mango"),
                          (Kind.AGENT_REPORT, None), (Kind.INTERRUPT, None)])
        self.assertEqual((got[0].cwd, got[3].detail["from"], got[3].detail["text"]), ("/w", "/root/a", "Done."))

    def test_after_a_compaction_what_came_before_is_sent_again(self):
        got = CODEX.read([item("user", "kept"), {"type": "compaction", "encrypted_content": "x"}, item("user", "new")])
        self.assertEqual([p.kind for p in got], [Kind.COMPACTION_REPEAT, Kind.COMPACTION_SUMMARY, Kind.USER])

    def test_its_calls_and_side_calls(self):
        ask = {"type": "function_call", "call_id": "c1", "name": "request_user_input",
               "arguments": '{"questions": [{"id": "q", "question": "Which?", "options": [{"label": "A"}]}]}'}
        call, = CODEX.read([ask])
        self.assertEqual((call.tool.id, call.tool.action, call.tool.ask["questions"][0]["question"]), ("c1", Action.ASK, "Which?"))
        body = {"input": [item("user", "hi")]}
        title = CODEX.call("POST", "/v1/responses", {"x-codex-turn-metadata": '{"thread_source": "thread_title"}',
                                                     "thread-id": "t1", "user-agent": "codex_cli_rs/0.164.0"}, body)
        self.assertEqual((title.kind, title.session, title.version), (CallKind.TITLE, "t1", "0.164.0"))
        self.assertEqual(CODEX.title(CODEX.read([item("assistant", '{"title": "Fix  the tests"}')])), "Fix the tests")
        self.assertEqual(CODEX.recap(CODEX.read([item("assistant", '{"summary": "Did x.", "next_action": "Do y."}')])),
                         "Did x.\n\nNext: Do y.")
        turn = CODEX.call("POST", "/v1/responses", {"x-codex-turn-metadata": '{"thread_source": "user"}'}, body)
        self.assertEqual(turn.kind, CallKind.TURN)


class OwnerTest(unittest.TestCase):
    def test_a_stored_piece_s_harness_by_its_shape(self):
        self.assertIs(harness_kit.owner(user("hi")), CLAUDE)
        self.assertIs(harness_kit.owner(item("user", "hi")), CODEX)
        self.assertIsNone(harness_kit.owner({"info": {}, "parts": []}))
        self.assertEqual(harness_kit.words("<bash-input>ls</bash-input>"), (Kind.USER_COMMAND, "! ls"))


if __name__ == "__main__":
    unittest.main()
