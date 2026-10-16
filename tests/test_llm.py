"""The LLM the policies call (`ag.ag_tools.llm.LiteLLMClient`), and how the
home builds it from [policies.llm]. litellm is replaced by a fake: no call
leaves the machine."""

import json
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import contextlib  # noqa: E402
import io  # noqa: E402
import tomllib  # noqa: E402

from ag.ag_harness.home import ConfigError, Home, set_keys  # noqa: E402
from ag.ag_harness.home.__main__ import main as home_cli  # noqa: E402
from ag.ag_tools.llm import CLIClient, LiteLLMClient  # noqa: E402

ENV = ("AG_LLM_URL", "AG_LLM_KEY", "AG_LLM_MODEL", "LITELLM_KEY", "MY_KEY")


def fake_litellm(answer="hi", error=None):
    """A stand-in for the litellm module; `.calls` holds each completion's kwargs."""
    calls = []

    def completion(**kwargs):
        calls.append(kwargs)
        if error:
            raise error
        message = types.SimpleNamespace(content=answer)
        usage = types.SimpleNamespace(model_dump=lambda: {"total_tokens": 7})
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)], usage=usage)

    return types.SimpleNamespace(completion=completion, calls=calls)


class ClientTest(unittest.TestCase):
    def call(self, client, lite, **kw):
        with mock.patch.dict(sys.modules, {"litellm": lite}):
            return client.complete("p", system="s", model=kw.get("model", "gemini/gemini-3.8-flash"),
                                   effort=kw.get("effort", "low"), timeout=5, purpose="rank")

    def test_a_call_names_the_provider_by_the_model(self):
        lite = fake_litellm("answer")
        self.assertEqual(self.call(LiteLLMClient(), lite), "answer")
        sent = lite.calls[0]
        self.assertEqual(sent["model"], "gemini/gemini-3.8-flash")
        self.assertEqual(sent["messages"], [{"role": "system", "content": "s"}, {"role": "user", "content": "p"}])
        self.assertEqual((sent["reasoning_effort"], sent["timeout"], sent["drop_params"]), ("low", 5, True))
        self.assertNotIn("api_base", sent)
        self.assertNotIn("api_key", sent)                     # litellm reads GEMINI_API_KEY itself

    def test_a_server_of_our_own_takes_a_bare_model_as_openai_compatible(self):
        lite = fake_litellm()
        self.call(LiteLLMClient(api_base="http://127.0.0.1:4011/v1", api_key="k"), lite, model="gemini-3.8-flash")
        sent = lite.calls[0]
        self.assertEqual((sent["model"], sent["api_base"], sent["api_key"]),
                         ("openai/gemini-3.8-flash", "http://127.0.0.1:4011/v1", "k"))

    def test_no_effort_sends_none(self):
        lite = fake_litellm()
        self.call(LiteLLMClient(), lite, effort="")
        self.assertNotIn("reasoning_effort", lite.calls[0])

    def test_a_failure_is_an_empty_answer_and_logged(self):
        with tempfile.TemporaryDirectory() as d:
            text = self.call(LiteLLMClient(log_dir=d), fake_litellm(error=RuntimeError("down")))
            self.assertEqual(text, "")
            [name] = os.listdir(d)
            with open(os.path.join(d, name)) as fh:
                record = json.load(fh)
            self.assertEqual((record["purpose"], record["error"]), ("rank", "RuntimeError: down"))

    def test_no_model_calls_nothing_and_says_why(self):
        lite = fake_litellm()
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self.call(LiteLLMClient(log_dir=d), lite, model=""), "")
            [name] = os.listdir(d)
            with open(os.path.join(d, name)) as fh:
                self.assertIn("no model", json.load(fh)["error"])
        self.assertEqual(lite.calls, [])

    def test_usage_is_logged(self):
        with tempfile.TemporaryDirectory() as d:
            self.call(LiteLLMClient(log_dir=d), fake_litellm())
            [name] = os.listdir(d)
            with open(os.path.join(d, name)) as fh:
                self.assertEqual(json.load(fh)["usage"], {"total_tokens": 7})


class HomeLLMTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.env = mock.patch.dict(os.environ, {})
        self.env.start()
        for k in ENV:
            os.environ.pop(k, None)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def home(self, llm: str) -> Home:
        with open(os.path.join(self.root, "config.toml"), "w") as fh:
            fh.write("[policies.llm]\n" + llm)
        return Home(self.root)

    def test_there_is_no_default_model(self):
        c = self.home("").llm()
        self.assertEqual((c.model, c.api_base, c.api_key), ("", None, None))

    def test_a_model_on_the_provider_s_own_api(self):
        c = self.home('model = "gemini/gemini-3.8-flash"\n').llm()
        self.assertEqual((c.model, c.api_base, c.api_key), ("gemini/gemini-3.8-flash", None, None))

    def test_a_model_and_its_key_variable(self):
        os.environ["MY_KEY"] = "secret"
        c = self.home('model = "anthropic/claude-sonnet-5-5"\nkey_env = "MY_KEY"\n').llm()
        self.assertEqual((c.model, c.api_base, c.api_key), ("anthropic/claude-sonnet-5-5", None, "secret"))

    def test_an_api_base_without_a_key_gets_a_placeholder(self):
        c = self.home('model = "gemini-3.8-flash"\napi_base = "http://127.0.0.1:4011/v1"\n').llm()
        self.assertEqual((c.api_base, c.api_key, c.route(c.model)),
                         ("http://127.0.0.1:4011/v1", "sk-local", "openai/gemini-3.8-flash"))

    def test_an_older_config_s_url_still_reaches_its_proxy(self):
        os.environ["LITELLM_KEY"] = "lk"
        c = self.home('url = "http://127.0.0.1:4011/v1/responses"\nkey_env = "LITELLM_KEY"\n'
                      'model = "gemini-3.8-flash"\n').llm()
        self.assertEqual((c.api_base, c.api_key, c.route(c.model)),
                         ("http://127.0.0.1:4011/v1", "lk", "openai/gemini-3.8-flash"))

    def test_the_environment_overrides(self):
        os.environ.update(AG_LLM_URL="http://x/v1/", AG_LLM_KEY="k", AG_LLM_MODEL="openai/gpt-5")
        c = self.home('model = "gemini/gemini-3.8-flash"\n').llm()
        self.assertEqual((c.model, c.api_base, c.api_key), ("openai/gpt-5", "http://x/v1", "k"))


class SetKeysTest(unittest.TestCase):
    def test_a_key_is_replaced_and_keeps_its_comment(self):
        out = set_keys(["[policies.llm]", 'model = "a"      # the model', "", "[pollers]"], "policies.llm",
                       {"model": "b/c"})
        self.assertEqual(out[1], 'model = "b/c"    # the model')

    def test_a_new_key_goes_after_the_table_s_last_key(self):
        out = set_keys(["[policies.llm]", 'model = "a"', "# api_base = \"x\"", "", "[pollers]"], "policies.llm",
                       {"api_base": "http://h/v1"})
        self.assertEqual(out[:3], ["[policies.llm]", 'model = "a"', 'api_base = "http://h/v1"'])
        self.assertIn("[pollers]", out)

    def test_empty_removes_and_none_leaves(self):
        out = set_keys(["[t]", 'a = "1"', 'b = "2"'], "t", {"a": "", "b": None})
        self.assertEqual(out, ["[t]", 'b = "2"'])

    def test_a_missing_table_goes_after_its_parent_s_keys(self):
        out = set_keys(["[policies]", 'default = "x"', "", "[policies.available.x]", 'class = "a:B"'],
                       "policies.llm", {"model": "m/n"})
        self.assertEqual(out[:5], ["[policies]", 'default = "x"', "", "[policies.llm]", 'model = "m/n"'])

    def test_other_tables_keys_of_the_same_name_are_untouched(self):
        out = set_keys(["[a]", 'model = "x"', "[policies.llm]", 'model = "y"'], "policies.llm", {"model": "z"})
        self.assertEqual(out, ["[a]", 'model = "x"', "[policies.llm]", 'model = "z"'])


class ModelCommandTest(unittest.TestCase):
    setUp, tearDown, home = HomeLLMTest.setUp, HomeLLMTest.tearDown, HomeLLMTest.home   # a home of its own

    def run_cli(self, *args) -> str:
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"AG_HOME": self.root}), contextlib.redirect_stdout(out):
            with mock.patch("ag.ag_harness.home.__main__.home", lambda: Home(self.root)):
                self.assertEqual(home_cli(["model", *args]), 0)
        return out.getvalue()

    def section(self) -> dict:
        with open(os.path.join(self.root, "config.toml"), "rb") as fh:
            return tomllib.load(fh)["policies"]["llm"]

    def test_set_then_shown(self):
        self.home("")
        self.assertIn("none set", self.run_cli())
        out = self.run_cli("gemini/gemini-3.8-flash")
        self.assertIn("model:     gemini/gemini-3.8-flash", out)
        self.assertEqual(self.section(), {"model": "gemini/gemini-3.8-flash"})
        self.assertEqual(Home(self.root).llm().model, "gemini/gemini-3.8-flash")

    def test_flags_left_out_stay_and_empty_clears(self):
        self.home("")
        self.run_cli("gemini-3.8-flash", "--api-base", "http://127.0.0.1:4011/v1", "--key-env", "LITELLM_KEY")
        self.run_cli("gemini-3.8-pro")
        self.assertEqual(self.section(), {"model": "gemini-3.8-pro", "api_base": "http://127.0.0.1:4011/v1",
                                          "key_env": "LITELLM_KEY"})
        self.run_cli("--api-base", "", "--key-env", "")
        self.assertEqual(self.section(), {"model": "gemini-3.8-pro"})

    def test_an_older_url_becomes_api_base(self):
        self.home('url = "http://127.0.0.1:4011/v1/responses"\nkey_env = "LITELLM_KEY"\nmodel = "gemini-3.8-flash"\n')
        self.run_cli("gemini-3.8-pro")
        self.assertEqual(self.section(), {"model": "gemini-3.8-pro", "api_base": "http://127.0.0.1:4011/v1",
                                          "key_env": "LITELLM_KEY"})

    def test_the_template_s_comments_stay(self):
        os.remove(os.path.join(self.root, "config.toml")) if os.path.exists(os.path.join(self.root, "config.toml")) else None
        Home(self.root).ensure()
        with open(os.path.join(self.root, "config.toml")) as fh:
            before = fh.read().splitlines()
        self.run_cli("anthropic/claude-sonnet-5-5")
        with open(os.path.join(self.root, "config.toml")) as fh:
            after = fh.read().splitlines()
        changed = [(a, b) for a, b in zip(before, after) if a != b]
        self.assertEqual(len(before), len(after))
        self.assertEqual(len(changed), 1)
        self.assertTrue(changed[0][1].startswith('model = "anthropic/claude-sonnet-5-5"'))
        self.assertIn("# required", changed[0][1])

    def test_a_file_that_would_not_parse_is_not_written(self):
        path = os.path.join(self.root, "config.toml")
        with open(path, "w") as fh:
            fh.write("[policies.llm]\nmodel = \"a\"\n[policies.llm]\n")      # a duplicate table: already broken
        with self.assertRaises(ConfigError):
            Home(self.root).set_llm("b/c")


FAKE_CLAUDE = """#!/usr/bin/env python3
import json, os, sys
rec = {"argv": sys.argv[1:], "stdin": sys.stdin.read(), "cwd": os.getcwd(),
       "env": {k: os.environ.get(k) for k in ("AG_HOME", "ANTHROPIC_BASE_URL", "KEEP_ME")}}
open(os.environ["FAKE_RECORD"], "w").write(json.dumps(rec))
if os.environ.get("FAKE_FAIL"):
    print(json.dumps({"type": "result", "subtype": "success", "is_error": True, "result": "rate limited"}))
else:
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "claude says hi",
                      "usage": {"input_tokens": 12, "output_tokens": 3}}))
"""

class FakeCodexSDK:
    """A stand-in for the openai_codex module: records the session and each thread and turn."""

    def __init__(self, answer="codex says hi", status="completed", error=None):
        sdk = self
        self.started, self.threads, self.turns, self.closed = [], [], [], 0

        class Codex:
            def __init__(self, config):
                sdk.started.append(config)

            def thread_start(self, **kw):
                sdk.threads.append(kw)
                return Thread()

            def close(self):
                sdk.closed += 1

        class Thread:
            def turn(self, prompt, **kw):
                sdk.turns.append((prompt, kw))
                return Turn()

        class Turn:
            def run(self):
                last = types.SimpleNamespace(model_dump=lambda: {"input_tokens": 20, "output_tokens": 4})
                return types.SimpleNamespace(final_response=answer, status=status, error=error,
                                             usage=types.SimpleNamespace(last=last))

            def interrupt(self):
                pass

        self.module = types.SimpleNamespace(
            Codex=Codex, CodexConfig=lambda **kw: kw,
            ApprovalMode=types.SimpleNamespace(deny_all="deny_all"),
            Sandbox=types.SimpleNamespace(read_only="read-only"))


class CLIClientTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bin = os.path.join(self.tmp.name, "bin")
        os.makedirs(self.bin)
        for name, body in (("claude", FAKE_CLAUDE), ("codex", "#!/bin/sh\nexit 0\n")):
            path = os.path.join(self.bin, name)
            with open(path, "w") as fh:
                fh.write(body)
            os.chmod(path, 0o755)
        self.record = os.path.join(self.tmp.name, "record.json")
        self.home = os.path.join(self.tmp.name, "home")
        self.logs = os.path.join(self.tmp.name, "logs")
        self.env = mock.patch.dict(os.environ, {"PATH": self.bin + os.pathsep + os.environ["PATH"],
                                                "FAKE_RECORD": self.record, "KEEP_ME": "yes"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def client(self) -> CLIClient:
        return CLIClient(home=self.home, log_dir=self.logs)

    def sent(self) -> dict:
        with open(self.record) as fh:
            return json.load(fh)

    def log(self) -> dict:
        [name] = os.listdir(self.logs)
        with open(os.path.join(self.logs, name)) as fh:
            return json.load(fh)

    def test_claude_code_runs_claude_headless_without_tools(self):
        text = self.client().complete("the prompt", system="the system", model="claude-code/sonnet",
                                      effort="low", timeout=30, purpose="rank")
        self.assertEqual(text, "claude says hi")
        argv = self.sent()["argv"]
        self.assertEqual(argv[:4], ["-p", "--model", "sonnet", "--output-format"])
        for flag, value in (("--tools", ""), ("--system-prompt", "the system"), ("--effort", "low")):
            self.assertEqual(argv[argv.index(flag) + 1], value)
        self.assertIn("--no-session-persistence", argv)
        self.assertEqual(self.sent()["stdin"], "the prompt")
        self.assertEqual(self.log()["usage"], {"input_tokens": 12, "output_tokens": 3})
        self.assertEqual(self.log()["cli"], "claude-code")

    def test_codex_runs_one_codex_through_its_sdk(self):
        sdk = FakeCodexSDK()
        c = self.client()
        with mock.patch.dict(sys.modules, {"openai_codex": sdk.module}):
            for _ in range(2):
                text = c.complete("the prompt", system="the system", model="codex/gpt-5.5",
                                  effort="", timeout=30, purpose="segment")
            self.assertEqual(text, "codex says hi")
            self.assertEqual(len(sdk.started), 1)                                   # one Codex, kept
            self.assertEqual(sdk.started[0]["codex_bin"], os.path.join(self.bin, "codex"))
            self.assertNotIn("AG_HOME", sdk.started[0]["env"])
            thread = sdk.threads[0]
            self.assertEqual((thread["base_instructions"], thread["model"], thread["ephemeral"],
                              thread["sandbox"], thread["approval_mode"]),
                             ("the system", "gpt-5.5", True, "read-only", "deny_all"))
            self.assertEqual(sdk.turns[0][0], "the prompt")                       # the prompt alone
            c._codex_close()
        self.assertEqual(sdk.closed, 1)
        with open(os.path.join(self.logs, sorted(os.listdir(self.logs))[-1])) as fh:
            self.assertEqual(json.load(fh)["usage"], {"input_tokens": 20, "output_tokens": 4})

    def test_a_failed_codex_turn_is_an_empty_answer_and_a_new_session(self):
        sdk = FakeCodexSDK(answer="", status="failed", error="quota")
        c = self.client()
        with mock.patch.dict(sys.modules, {"openai_codex": sdk.module}):
            self.assertEqual(c.complete("p", model="codex/gpt-5.5", effort="", timeout=30, purpose="a"), "")
        self.assertIn("quota", self.log()["error"])

    def test_codex_without_the_sdk_says_so(self):
        with mock.patch.dict(sys.modules, {"openai_codex": None}):
            self.assertEqual(self.client().complete("p", model="codex/gpt-5.5", effort="", timeout=30,
                                                    purpose="a"), "")
        self.assertIn("pip install openai-codex", self.log()["error"])

    def test_ag_s_environment_does_not_reach_the_cli(self):
        os.makedirs(os.path.join(self.home, "hook_server"))
        with open(os.path.join(self.home, "hook_server", "4113.json"), "w") as fh:
            json.dump({"port": 4113, "pid": 1, "upstream": "https://api.anthropic.com"}, fh)
        with mock.patch.dict(os.environ, {"AG_HOME": self.home, "ANTHROPIC_BASE_URL": "http://127.0.0.1:4113/h/x"}):
            self.client().complete("p", model="claude-code/sonnet", effort="", timeout=30, purpose="rank")
        self.assertEqual(self.sent()["env"], {"AG_HOME": None, "ANTHROPIC_BASE_URL": None, "KEEP_ME": "yes"})
        with mock.patch.dict(os.environ, {"ANTHROPIC_BASE_URL": "https://gateway.example/v1"}):    # not ag's: kept
            self.assertEqual(self.client().environment()["ANTHROPIC_BASE_URL"], "https://gateway.example/v1")

    def test_failures_are_an_empty_answer_and_logged(self):
        with mock.patch.dict(os.environ, {"FAKE_FAIL": "1"}):
            self.assertEqual(self.client().complete("p", model="claude-code/sonnet", effort="", timeout=30,
                                                    purpose="rank"), "")
        self.assertIn("rate limited", self.log()["error"])

    def test_a_missing_cli_or_a_model_of_neither_says_why(self):
        c = CLIClient(claude_command="no-such-claude", home=self.home, log_dir=self.logs)
        self.assertEqual(c.complete("p", model="claude-code/sonnet", effort="", timeout=30, purpose="a"), "")
        self.assertIn("no-such-claude not found on PATH", self.log()["error"])
        with self.assertRaises(ValueError):
            CLIClient.split("gemini/gemini-3.8-flash")

    def test_the_home_builds_it_for_a_cli_model(self):
        with open(os.path.join(self.tmp.name, "config.toml"), "w") as fh:
            fh.write('[policies.llm]\nmodel = "codex/gpt-5.5"\ncodex_command = "my-codex"\n')
        c = Home(self.tmp.name).llm()
        self.assertIsInstance(c, CLIClient)
        self.assertEqual((c.model, c.commands["codex"], c.home), ("codex/gpt-5.5", "my-codex", self.tmp.name))

    def test_policies_llm_may_name_any_implementation(self):
        with open(os.path.join(self.tmp.name, "config.toml"), "w") as fh:
            fh.write('[policies.llm]\nmodel = "m"\nclass = "ag.ag_tools.llm:CLIClient"\n')
        self.assertIsInstance(Home(self.tmp.name).llm(), CLIClient)
        with open(os.path.join(self.tmp.name, "config.toml"), "w") as fh:
            fh.write('[policies.llm]\nmodel = "m"\nclass = "ag.ag_tools.llm:NoSuchClient"\n')
        with self.assertRaises(ConfigError):
            Home(self.tmp.name).llm()


if __name__ == "__main__":
    unittest.main()
