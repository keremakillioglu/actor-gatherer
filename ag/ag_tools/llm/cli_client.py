"""An LLM over a coding agent's own login -- a Claude or ChatGPT subscription --
instead of an API key.

The model names the agent and the model it runs:

    claude-code/<model>   claude -p, headless, e.g. claude-code/sonnet
    codex/<model>         Codex, through its Python SDK (openai-codex), e.g. codex/gpt-5.5

claude-code: one process per call, in an empty temporary directory, with
Claude Code's tools and default instructions out of the way:

    claude -p --model <model> --output-format json --tools "" --system-prompt <system>
           --no-session-persistence --strict-mcp-config [--effort <effort>]       (prompt on stdin)

codex: one long-running Codex process (the SDK's app-server), started on the
first call and kept for the rest; each call is an ephemeral thread whose base
instructions are the system prompt -- replacing Codex's own, which are
thousands of tokens -- in a read-only sandbox with every approval denied, in
an empty directory. Codex's config.toml and login apply, as when you run it.

Either CLI gets this process's environment without ag's: no AG_* variable, and
no base URL pointing at one of ag's hook servers, so the Gatherer's own calls
never come back through ag. Every call counts against the subscription's limits.
"""

import atexit
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Dict, Optional, Tuple
from urllib.parse import urlsplit

from ag.ag_interface import LLM

from .calllog import CallLog

CLIS = ("claude-code", "codex")
CLAUDE_EFFORTS = ("low", "medium", "high", "xhigh", "max")
DEFAULT_SYSTEM = "Answer the request directly, in text."
BASE_URLS = ("ANTHROPIC_BASE_URL", "OPENAI_BASE_URL", "CODEX_OSS_BASE_URL")


class CLIClient(LLM):
    def __init__(self, *, claude_command: str = "claude", codex_command: str = "codex",
                 home: Optional[str] = None, log_dir: Optional[str] = None, log_prompts: bool = False):
        """
        Args:
            claude_command, codex_command: the executables ([policies.llm]
                claude_command / codex_command), found on PATH.
            home: ag's home, to know its hook servers (AG_HOME, else ~/.ag).
            log_dir, log_prompts: as LiteLLMClient's -- one JSON file per call.
        """
        self.commands = {"claude-code": claude_command or "claude", "codex": codex_command or "codex"}
        self.home = os.path.expanduser(home or os.environ.get("AG_HOME") or "~/.ag")
        self._calllog = CallLog(log_dir, log_prompts)
        self._codex_client = None                      # the long-running Codex, once a codex/ call starts it
        self._codex_dir = None                         # its empty working directory
        self._codex_lock = threading.Lock()            # one codex call at a time

    @staticmethod
    def split(model: str) -> Tuple[str, str]:
        """("claude-code" | "codex", the CLI's model) of `model`.

        Raises:
            ValueError: the model names neither CLI.
        """
        cli, _, name = (model or "").partition("/")
        if cli not in CLIS or not name:
            raise ValueError(f"CLIClient takes claude-code/<model> or codex/<model>, not {model!r}")
        return cli, name

    def executable(self, cli: str) -> Optional[str]:
        """Where the CLI's executable is, or None."""
        return shutil.which(self.commands[cli])

    def complete(self, prompt: str, *, system: Optional[str] = None, model: str,
                 effort: str, timeout: float, purpose: str) -> str:
        started = time.time()
        usage, error, text = None, None, ""
        try:
            if not model:
                raise ValueError("no model: set [policies.llm] model (or AG_LLM_MODEL), e.g. claude-code/sonnet")
            cli, name = self.split(model)
            path = self.executable(cli)
            if not path:
                raise FileNotFoundError(f"{self.commands[cli]} not found on PATH")
            run = self._claude if cli == "claude-code" else self._codex
            text, usage = run(path, name, system, prompt, effort, timeout)
        except (subprocess.TimeoutExpired, FutureTimeout):
            error = f"TimeoutExpired: no answer within {timeout}s"
        except Exception as exc:  # noqa: BLE001 - never raise to the caller
            error = f"{type(exc).__name__}: {exc}"
        self._calllog.write(purpose, model, effort, usage, time.time() - started, error, text, system, prompt,
                            cli=(model or "").partition("/")[0])
        return text

    # ---- the two CLIs

    def _claude(self, path, model, system, prompt, effort, timeout) -> Tuple[str, Optional[dict]]:
        argv = [path, "-p", "--model", model, "--output-format", "json", "--tools", "",
                "--system-prompt", system or DEFAULT_SYSTEM, "--no-session-persistence", "--strict-mcp-config"]
        if effort in CLAUDE_EFFORTS:
            argv += ["--effort", effort]
        out = self._run(argv, prompt, timeout)
        try:
            result = json.loads(out)
        except ValueError as exc:
            raise RuntimeError(f"claude printed no JSON result: {out[:300]!r}") from exc
        if result.get("is_error") or result.get("subtype") not in (None, "success"):
            raise RuntimeError(f"claude: {str(result.get('result') or result.get('subtype'))[:300]}")
        return str(result.get("result") or ""), result.get("usage")

    def _codex(self, path, model, system, prompt, effort, timeout) -> Tuple[str, Optional[dict]]:
        try:
            from openai_codex import ApprovalMode, Sandbox
        except ImportError as exc:
            raise RuntimeError("codex/ models need the Codex SDK: pip install openai-codex") from exc
        with self._codex_lock:
            codex = self._codex_session(path)
            try:
                thread = codex.thread_start(base_instructions=system or DEFAULT_SYSTEM, ephemeral=True,
                                            sandbox=Sandbox.read_only, approval_mode=ApprovalMode.deny_all,
                                            cwd=self._codex_dir, model=model)
                turn = thread.turn(prompt, effort=_codex_effort(effort))
                pool = ThreadPoolExecutor(max_workers=1)
                try:
                    result = pool.submit(turn.run).result(timeout=timeout)
                except FutureTimeout:
                    try:
                        turn.interrupt()
                    except Exception:  # noqa: BLE001 - the turn is abandoned either way
                        pass
                    raise
                finally:
                    pool.shutdown(wait=False)
            except FutureTimeout:
                raise
            except Exception:
                self._codex_close()                    # a broken session: the next call starts a new one
                raise
        if result.error or str(getattr(result.status, "value", result.status)) not in ("completed", "None"):
            raise RuntimeError(f"codex: {str(result.error or result.status)[:300]}")
        usage = getattr(result.usage, "last", None) if result.usage is not None else None
        return (result.final_response or "").strip(), (usage.model_dump() if usage is not None else None)

    def _codex_session(self, path: str):
        """The long-running Codex (the SDK's app-server), started once, in an
        empty directory, with ag's environment kept out."""
        if self._codex_client is None:
            from openai_codex import Codex, CodexConfig
            self._codex_dir = tempfile.mkdtemp(prefix="ag-codex-")
            self._codex_client = Codex(CodexConfig(codex_bin=path, cwd=self._codex_dir, env=self.environment()))
            atexit.register(self._codex_close)
        return self._codex_client

    def _codex_close(self) -> None:
        client, self._codex_client = self._codex_client, None
        if client is not None:
            try:
                client.close()
            except Exception:  # noqa: BLE001
                pass
        if self._codex_dir:
            shutil.rmtree(self._codex_dir, ignore_errors=True)
            self._codex_dir = None

    def _run(self, argv, stdin: str, timeout: float, cwd: Optional[str] = None) -> str:
        """The command's stdout. Raises on a non-zero exit (with its stderr's
        end) or a timeout (subprocess.TimeoutExpired)."""
        with tempfile.TemporaryDirectory(prefix="ag-cli-") as empty:
            done = subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=timeout,
                                  cwd=cwd or empty, env=self.environment())
        if done.returncode != 0:
            tail = (done.stderr or done.stdout or "").strip()[-300:]
            raise RuntimeError(f"{os.path.basename(argv[0])} exited {done.returncode}: {tail}")
        return done.stdout

    def environment(self) -> Dict[str, str]:
        """This process's environment without ag's: no AG_* variable, and no
        base URL that points at one of ag's hook servers."""
        ports = set()
        folder = os.path.join(self.home, "hook_server")
        for name in os.listdir(folder) if os.path.isdir(folder) else []:
            try:
                with open(os.path.join(folder, name), encoding="utf-8") as fh:
                    ports.add(int(json.load(fh)["port"]))
            except (OSError, ValueError, KeyError, TypeError):
                continue
        env = {k: v for k, v in os.environ.items() if not k.startswith("AG_")}
        for var in BASE_URLS:
            parts = urlsplit(env.get(var, ""))
            if parts.hostname in ("127.0.0.1", "localhost") and parts.port in ports:
                env.pop(var)
        return env


def _codex_effort(effort: str):
    """`effort` as the SDK takes it (its ReasoningEffort), or None to leave codex's."""
    if not effort:
        return None
    try:
        from openai_codex.generated.v2_all import ReasoningEffort
        return ReasoningEffort(effort)
    except (ImportError, ValueError):
        return None
