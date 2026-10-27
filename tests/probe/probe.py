"""The probe: a live session of a harness, each feature harness_kit reads triggered in it, and what came of it written as
that harness version's fixtures (tests/fixtures/harnesses/<harness>/<version>/, fixtures.py), with what the rules now
read of them (expected.json) for a person to look over before committing.

    <ag's venv python> tests/probe/probe.py claude [--model sonnet] [--out DIR] [--force] [--keep] [--only STEP,...]
    <ag's venv python> tests/probe/probe.py codex  [--model gpt-6-luna] ...

(PROBE_SCREEN=1: the terminal's last text logged after each step.)

It runs on this checkout, apart from everything of the user's: a throwaway ag home (BASE/f7*, short for macOS's socket
paths) with ~/.ag/config.toml copied whole, a gatherer of its own, a dashboard on a free port
(4750-4759), a scratch folder to work in. The harness's command is wrap.py, which puts a tap (tap.py) between the
harness and ag's hook server: every call as the harness sent it, headers and all, and its answer. The session is
driven through the dashboard's API as the page drives it (drive.py): its first message, questions answered from the
page and dismissed with Esc, a plan sent back and approved, background tasks, a message written mid-turn and one taken
back, Esc mid-command, an API error (the tap refuses one message's calls), a compaction. Then its calls, its longest conversation
and its own record of the session are written as fixtures, and it says which features the run did not trigger and how
the version's features differ from the newest older version's.

Everything it started is stopped and removed after: the dashboard, the hook servers (`ag stop`), the taps, the scratch
home and folder, Claude Code's record of the session (~/.claude/projects/<folder>) and the plan files it wrote. Codex's
threads stay in ~/.codex/sessions: codex also lists them in its own database. It costs a few dozen model calls, and
takes about five minutes: on macOS it keeps the machine awake while it runs (`caffeinate`)."""

import argparse
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import tomllib
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path[:0] = [HERE, ROOT]

import harness_kit  # noqa: E402
from harness_kit import CallKind  # noqa: E402
from harness_kit.claude import PLAN_FILE  # noqa: E402

import fixtures  # noqa: E402
from drive import Dashboard, Term  # noqa: E402
from reading import features  # noqa: E402

PORTS = range(4750, 4760)
BASE = f"/private/tmp/claude-{os.getuid()}" if os.path.isdir(f"/private/tmp/claude-{os.getuid()}") else "/tmp"
MARK = "PROBE-API-ERROR"
FIXTURES = os.path.join(ROOT, "tests", "fixtures", "harnesses")
T0 = time.time()
#: What a run is meant to trigger, by `reading.features`' names: what it did not is said at the end.
TARGETS = {
    "claude": ["call:turn", "call:subagent", "call:suggestion", "call:other", "call:compaction",
               "part:user", "part:user_command", "part:mid_turn", "part:local_command", "part:command_output",
               "part:interrupt", "part:task_notice", "part:agent_report", "part:compaction_summary",
               "ask:question", "ask:plan", "task:command:started", "task:agent:started", "task:monitor:started",
               "derived:asked:question", "derived:asked:plan", "derived:ask_settled:answered",
               "derived:ask_settled:dismissed", "derived:task_started:command", "derived:task_started:agent",
               "derived:task_started:monitor", "derived:task_ended:stopped", "derived:task_activity",
               "record:message_queued", "record:message_sent:mid_turn", "record:message_sent:prompt",
               "record:message_withdrawn", "record:ask_settled:answered", "record:ask_settled:dismissed",
               "record:turn_stopped:interrupted", "record:turn_stopped:error", "record:task_ended:completed",
               "answer:question", "answer:plan"],
    "codex": ["call:turn", "call:title", "call:compaction", "part:user", "part:command_output", "part:interrupt",
              "record:asked:question", "record:asked:plan", "record:ask_settled:answered",
              "record:turn_stopped:over", "record:turn_stopped:interrupted", "record:turn_stopped:error",
              "answer:question", "answer:question:async", "answer:plan"],
}


def log(*a) -> None:
    print(f"[{time.time() - T0:6.1f}s]", *a, flush=True)


def version_of(harness: str) -> str:
    out = subprocess.run([harness, "--version"], capture_output=True, text=True, timeout=60).stdout
    found = re.search(r"(\d+\.\d+\.\d+)", out)
    if not found:
        raise SystemExit(f"no version from `{harness} --version`: {out!r}")
    return found.group(1)


def child_env(scratch: str, home: str) -> dict:
    """The environment for ag and the dashboard: this checkout's, the scratch home's -- nothing of a session this runs
    under (its hook server's address, its Claude Code's variables, its ag's)."""
    env = {k: v for k, v in os.environ.items()
           if not (k.startswith(("CLAUDE_CODE_", "AG_")) or k in ("CLAUDECODE", "CLAUDE_PID", "ANTHROPIC_BASE_URL"))}
    return {**env, "AG_HOME": home, "PYTHONPATH": ROOT, "AG_COMMAND": f"{sys.executable} {ROOT}/ag/cli/ag",
            "PROBE_DIR": scratch, "PROBE_FAIL": MARK}


def config(harness: str, home: str) -> None:
    """~/.ag/config.toml, whole, its harness's command wrap.py's."""
    with open(os.path.expanduser("~/.ag/config.toml"), encoding="utf-8") as fh:
        text = fh.read()
    command = tomllib.loads(text)["cli"]["harnesses"][harness]["command"]
    section = re.search(rf"(?ms)^\[cli\.harnesses\.{harness}\]\n.*?(?=^\[|\Z)", text)
    if section is None:
        raise SystemExit(f"no [cli.harnesses.{harness}] in ~/.ag/config.toml")
    wrapped = json.dumps([sys.executable, os.path.join(HERE, "wrap.py"), *command])
    body = re.sub(r"(?m)^command\s*=.*$", lambda _: f"command = {wrapped}", section.group(0), count=1)
    os.makedirs(home, exist_ok=True)
    with open(os.path.join(home, "config.toml"), "w", encoding="utf-8") as fh:
        fh.write(text[:section.start()] + body + text[section.end():])


def free_port() -> int:
    for port in PORTS:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise SystemExit(f"no free port in {PORTS.start}-{PORTS.stop - 1}")


def listener(port: int):
    got = subprocess.run(["lsof", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"], capture_output=True, text=True).stdout.split()
    return int(got[0]) if got else None


class Run:
    """One probe run: its scratch home and folder, its dashboard, the session it drives, what it did."""

    def __init__(self, harness: str, model, only):
        self.harness, self.model, self.only = harness, model, only
        self.scratch = f"{BASE}/f7{harness[:2]}{int(time.time()) % 1000000}"
        self.home, self.cwd = os.path.join(self.scratch, "h"), os.path.join(self.scratch, "w")
        self.env = child_env(self.scratch, self.home)
        self.dash, self.proc, self.sid, self.term = None, None, None, None
        self.steps = {}

    # ---- set up and torn down

    def start(self) -> None:
        os.makedirs(self.cwd)
        with open(os.path.join(self.cwd, "notes.txt"), "w") as fh:
            fh.write("The secret number is 4127.\n")
        config(self.harness, self.home)
        subprocess.run([sys.executable, f"{ROOT}/ag/cli/ag", "new", "probe"], env=self.env, cwd=self.scratch,
                       capture_output=True, check=True, timeout=120)
        port = free_port()
        self.proc = subprocess.Popen([sys.executable, "-m", "ag_dashboard", "--home", self.home, "--port", str(port)],
                                     env=self.env, cwd=self.scratch, stdin=subprocess.DEVNULL,
                                     stdout=open(os.path.join(self.scratch, "dash.log"), "w"), stderr=subprocess.STDOUT)
        for _ in range(60):
            if listener(port):
                break
            time.sleep(0.5)
        if listener(port) != self.proc.pid:
            raise SystemExit(f"port {port} is not this probe's dashboard (pid {listener(port)}, not {self.proc.pid})")
        self.dash = Dashboard(f"http://127.0.0.1:{port}", self.home, "probe", log)
        log(f"dashboard {self.dash.url}, home {self.home}, folder {self.cwd}")

    def stop(self) -> None:
        if self.term is not None:
            self.term.close()
        if self.dash is not None and self.sid:
            try:
                self.dash.stop(self.sid)
            except Exception:  # noqa: BLE001
                pass
        if self.proc is not None and self.proc.poll() is None:
            self.proc.send_signal(signal.SIGINT)
            try:
                self.proc.wait(20)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        subprocess.run([sys.executable, f"{ROOT}/ag/cli/ag", "stop"], env=self.env, cwd=self.scratch,
                       capture_output=True, timeout=120)
        taps = os.path.join(self.scratch, "calls.jsonl")             # each tap's command line names its file
        subprocess.run(["pkill", "-f", taps], capture_output=True)
        time.sleep(3)
        subprocess.run(["pkill", "-9", "-f", taps], capture_output=True)

    def clean(self) -> None:
        if self.harness == "claude":
            shutil.rmtree(os.path.expanduser("~/.claude/projects/" + re.sub(r"[^A-Za-z0-9]", "-", self.cwd)),
                          ignore_errors=True)
            for path in self.plan_files():
                os.remove(path)
                log("removed the plan file", path)
        shutil.rmtree(self.scratch, ignore_errors=True)

    def plan_files(self) -> list:
        """The plan files the session wrote (~/.claude/plans/), as its calls name them."""
        found = set()
        calls = os.path.join(self.scratch, "calls.jsonl")
        if os.path.exists(calls):
            with open(calls, encoding="utf-8") as fh:
                for path in re.findall(r'"(/[^"\\]+/\.claude/plans/[^"/\\]+\.md)"', fh.read()):
                    if PLAN_FILE.search(path) and os.path.exists(path) and os.path.getmtime(path) >= T0 - 5:
                        found.add(path)
        return sorted(found)

    # ---- the steps

    def step(self, name: str, fn) -> None:
        if self.only and name not in self.only:
            return
        log(f"-- {name}")
        try:
            got = fn()
            self.steps[name] = "done" if got is None or got else "not seen"
        except Exception as exc:  # noqa: BLE001 - one step's failure is said, the run goes on
            traceback.print_exc()
            self.steps[name] = f"failed: {exc!r}"
        log(f"   {name}: {self.steps[name]}")
        if os.environ.get("PROBE_SCREEN") and self.term is not None:
            log("   screen: " + self.term.text(1500).replace("\n", " | "))

    def first(self, text: str) -> None:
        d = self.dash
        self.sid = d.create(self.cwd, self.harness, "plan" if self.harness == "claude" else "auto", self.model)
        d.send(self.sid, text)
        self.term = Term(d, self.sid)
        if self.term.wait(r"(?i)trustthisfolder|doyoutrust|allowcodex", 30):
            time.sleep(1)
            if self.harness == "claude":
                self.term.key("\x1b[B", 0.5)
            else:
                self.term.key("1", 0.5)
            self.term.key("\r", 1)
            log("trusted the folder")
        if self.harness == "codex":
            renamed = d.until(lambda: next((s["session_id"] for s in d.sessions()
                                            if s.get("cwd") == self.cwd and s["session_id"] != self.sid), None), 60, 1)
            if renamed:
                log("renamed to its thread", renamed)
                self.term.close()
                self.sid, self.term = renamed, Term(d, renamed)
        d.wait_turn(self.sid, self.term, 180)

    def ask(self, text: str, choose, kind: str = "question") -> bool:
        d = self.dash
        d.send(self.sid, text)
        ask = d.wait_asking(self.sid, kind)
        if not ask:
            return False
        time.sleep(1.5)
        d.answer(self.sid, ask["call"], choose(ask))
        d.wait_turn(self.sid, self.term, 120, 5)
        return True

    def dismiss(self, text: str) -> bool:
        d = self.dash
        d.send(self.sid, text)
        if not d.wait_asking(self.sid, "question"):
            return False
        time.sleep(1.5)
        self.term.key("\x1b", 0.2)
        return d.wait_status(self.sid, ("idle",), 30) == "idle"

    def plan(self, text: str, change: str, approve: str) -> bool:
        d, offer = self.dash, self.harness == "codex"
        d.send(self.sid, text)
        ask = d.wait_asking(self.sid, "plan", 240, offer=offer)
        if not ask:
            return False
        time.sleep(2)
        d.answer(self.sid, ask["call"], {"plan": "change", "text": change})
        again = d.wait_asking(self.sid, "plan", 240, not_call=ask["call"], offer=offer)
        if not again:
            return False
        time.sleep(2)
        d.answer(self.sid, again["call"], {"plan": approve})
        d.wait_turn(self.sid, self.term, 240, 20)
        return True

    def task(self, text: str, kind: str, stop: str = None, timeout: float = 150) -> bool:
        d = self.dash
        before = d.last_row(self.sid)
        d.send(self.sid, text)
        started = d.wait_event(self.sid, "task_started", lambda p: p.get("kind") == kind, 150, before)
        if not started:
            return False
        if stop:
            time.sleep(10)
            d.wait_status(self.sid, ("background", "idle"), 60)
            d.send(self.sid, stop)
        d.wait_event(self.sid, "task_ended", lambda p: p.get("task") == started["task"], timeout, before)
        d.wait_turn(self.sid, self.term, 120, 3)
        return d.wait_status(self.sid, ("idle",), 120, quiet=3) == "idle"

    def mid_turn(self, text: str, then: str) -> bool:
        d = self.dash
        d.send(self.sid, text)
        if d.wait_status(self.sid, ("running",), 60) != "running":
            return False
        time.sleep(4)
        d.send(self.sid, then)
        d.wait_turn(self.sid, self.term, 120, 3)
        return True

    def withdraw(self, text: str) -> bool:
        d = self.dash
        before = d.last_row(self.sid)
        d.send(self.sid, text)
        if d.wait_status(self.sid, ("running",), 60) != "running":
            return False
        time.sleep(3)
        self.term.type("Never mind this one", enter=True)
        time.sleep(2)
        self.term.key("\x1b[A", 1)                       # Up: queued messages back in the prompt
        d.wait_turn(self.sid, self.term, 120, 1)
        self.term.key("\x03", 1)                         # Ctrl+C: the prompt cleared
        return bool(d.wait_event(self.sid, "message_withdrawn", timeout=10, after=before))

    def interrupt(self, text: str, command: str) -> bool:
        """`text` sent, Esc once its answer has called `command` -- not before: Esc before an answer takes the message
        back, and nothing of the turn is recorded."""
        d = self.dash
        before = d.last_row(self.sid)
        d.send(self.sid, text)
        if not d.wait_event(self.sid, "reply_part", lambda p: command in json.dumps(p), 120, before):
            return False
        time.sleep(4)
        self.term.key("\x1b", 0.2)
        return d.wait_status(self.sid, ("idle",), 30) == "idle"

    def error(self) -> bool:
        """A message whose calls the tap refuses (MARK): the harness gives up, and records the error."""
        d = self.dash
        before = d.last_row(self.sid)
        d.send(self.sid, f"{MARK}: reply with just: ok")
        got = d.wait_event(self.sid, "turn_stopped", lambda p: p.get("how") == "error", 180, before)
        d.wait_turn(self.sid, self.term, 60, 2)
        self.command("Reply with just: ok")             # the user's last message no longer the refused one's
        return bool(got)

    def command(self, text: str, wait: float = 8) -> bool:
        self.dash.send(self.sid, text)
        time.sleep(wait)
        if self.harness == "claude" and text.startswith("/"):
            self.term.key("\x1b", 1)                   # its dialog closed (/cost's holds the prompt until Esc)
        self.dash.wait_turn(self.sid, self.term, 60, 2)
        return True

    def compact(self) -> bool:
        """`/compact`: a compaction call seen -- one the rules read as one, or a POST to a compaction endpoint (codex's
        remote compaction) -- and its turn over."""
        self.dash.send(self.sid, "/compact")
        found = self.dash.until(lambda: any(c["call"] is not None and c["call"].kind == CallKind.COMPACTION
                                            or "compact" in c["path"] for c in self.calls()), 180, 2)
        self.dash.wait_turn(self.sid, self.term, 120, 2)
        return bool(found)

    def calls(self) -> list:
        """The calls the tap has written since last asked, each with what the rules read it as (`call`)."""
        path = os.path.join(self.scratch, "calls.jsonl")
        if not os.path.exists(path):
            return []
        h, out = harness_kit.get(self.harness), []
        with open(path, "rb") as fh:
            fh.seek(getattr(self, "read_to", 0))
            for line in fh:
                if not line.endswith(b"\n"):
                    break
                self.read_to = getattr(self, "read_to", 0) + len(line)
                try:
                    c = json.loads(line)
                except ValueError:
                    continue
                got = h.call(c["method"], c["path"], c["headers"], c["body"]) if isinstance(c["body"], dict) else None
                out.append({**c, "call": got})
        return out

    def claude(self) -> None:
        pick = lambda labels: lambda ask: {"answers": [  # noqa: E731
            {"options": [i for i, o in enumerate(q["options"]) if o["label"] in labels] or [0]} for q in ask["questions"]]}
        self.step("first", lambda: self.first("Read notes.txt and tell me the secret number, in one sentence."))
        self.step("questions", lambda: self.ask(
            "Use the AskUserQuestion tool once, with two questions: 'Which fruit?' (single choice: Apple, Mango) and "
            "'Which pets?' (multiSelect: Cat, Dog, Fish). Then reply with exactly what I answered.", pick({"Mango", "Cat", "Fish"})))
        self.step("dismissed", lambda: self.dismiss(
            "Use the AskUserQuestion tool to ask me one question: 'Tea or coffee?' with options Tea and Coffee. "
            "Then reply with just my answer."))
        self.step("plan", lambda: self.plan(
            "Plan creating a file plan.txt holding the word hi. Keep the plan to two lines, write it, then ask me to "
            "approve it.", "Use the word hello instead", "auto"))
        self.step("command", lambda: self.task(
            "Start `for i in $(seq 1 60); do echo tick $i; sleep 1; done` with Bash using run_in_background: true, "
            "then reply 'started' and end your turn.", "command",
            stop="Stop the background command you started, with the tool for stopping background tasks, then reply 'stopped'."))
        self.step("agent", lambda: self.task(
            "Use the Agent tool with run_in_background: true (subagent_type general-purpose, description 'sleepy "
            "helper'): the subagent runs `sleep 15` with Bash, then answers with the word done. Reply 'launched' right "
            "away and end your turn; don't wait for it.", "agent"))
        self.step("monitor", lambda: self.task(
            "Use the Monitor tool to watch the output of `for i in 1 2 3; do echo line $i; sleep 4; done`. Reply "
            "'watching' and end your turn.", "monitor"))
        self.step("mid-turn", lambda: self.mid_turn("Run `sleep 12` with Bash (not in the background), then reply 'slept'.",
                                                    "Also tell me what 6 times 7 is."))
        self.step("withdrawn", lambda: self.withdraw("Run `sleep 10` with Bash (not in the background), then reply 'done'."))
        self.step("interrupt", lambda: self.interrupt("Run `sleep 40` with Bash (not in the background), then reply 'done'.",
                                                      "sleep 40"))
        self.step("commands", lambda: self.command("!echo bang") and self.command("/context", 4) and
                  self.command("Reply with just: ok"))
        self.step("error", self.error)
        self.step("compact", lambda: self.compact() and self.command("Reply with just: ok"))

    def codex(self) -> None:
        pick = lambda n: lambda ask: {"answers": [{"options": [min(n, len(q["options"]) - 1)]}  # noqa: E731
                                                  for q in ask["questions"]]}
        self.step("first", lambda: self.first("Read notes.txt and tell me the secret number, in one sentence."))

        def plan_mode():
            self.term.type("/plan")
            time.sleep(2)
            return True
        self.step("plan-mode", plan_mode)
        self.step("question-and-plan", lambda: self.ask(
            "Use the request_user_input tool to ask me exactly one question: which colour I prefer, with options Red "
            "and Blue, and wait for my answer. Then propose a short two-step plan to create colour.txt holding that "
            "colour.", pick(1)) and self.plan_after("Name the file colours.txt instead"))
        self.step("async-question", lambda: self.ask(
            "Use the request_user_input_async tool to ask me one question: which number I like, with options One and "
            "Two. Don't wait for the answer: right after asking, run `sleep 20` in the shell, then reply 'asked'. When "
            "my answer comes, repeat it back in one word.", pick(1)))     # its turn goes on: answered while it runs
        self.step("interrupt", lambda: self.interrupt("Run `sleep 40` in the shell, then reply 'done'.", "sleep 40"))
        self.step("commands", lambda: self.command("!echo bang"))
        self.step("subagent", lambda: self.command(
            "Spawn one subagent with your agent tool to run `echo hi` and report back; wait for it, then reply 'done'.", 20))
        self.step("error", self.error)
        self.step("compact", self.compact)

    def plan_after(self, change: str) -> bool:
        """The plan a turn proposed after its question: sent back with `change`, then implemented."""
        d = self.dash
        ask = d.wait_asking(self.sid, "plan", 240, offer=True)
        if not ask:
            return False
        time.sleep(2)
        d.answer(self.sid, ask["call"], {"plan": "change", "text": change})
        again = d.wait_asking(self.sid, "plan", 240, not_call=ask["call"], offer=True)
        if not again:
            return False
        time.sleep(2)
        d.answer(self.sid, again["call"], {"plan": "implement"})
        d.wait_turn(self.sid, self.term, 240, 20)
        return True

    # ---- what came of it

    def record(self):
        h = harness_kit.get(self.harness)
        return h.record_path(self.sid, self.cwd) if self.sid else None


def previous(harness: str, version: str):
    """The newest version's folder of the harness's fixtures older than `version`, if any."""
    key = lambda v: tuple(int(x) for x in re.findall(r"\d+", v))  # noqa: E731
    folder = os.path.join(FIXTURES, harness)
    older = [v for v in os.listdir(folder) if key(v) < key(version)] if os.path.isdir(folder) else []
    return os.path.join(folder, max(older, key=key)) if older else None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("harness", choices=("claude", "codex"))
    ap.add_argument("--model")
    ap.add_argument("--out", help="where the fixtures go (default: tests/fixtures/harnesses/<harness>/<version>)")
    ap.add_argument("--force", action="store_true", help="write over fixtures already there")
    ap.add_argument("--keep", action="store_true", help="keep the scratch home and the harness's record after")
    ap.add_argument("--only", help="only these steps (comma separated), after 'first'")
    a = ap.parse_args()
    version = version_of(a.harness)
    out = a.out or os.path.join(FIXTURES, a.harness, version)
    if os.path.exists(os.path.join(out, "expected.json")) and not a.force:
        raise SystemExit(f"{out} has fixtures already: --force to write over them")
    model = a.model or ("sonnet" if a.harness == "claude" else None)
    run = Run(a.harness, model, set(["first", *a.only.split(",")]) if a.only else None)
    log(f"{a.harness} {version}, model {model or 'its default'}")
    if shutil.which("caffeinate"):             # macOS: kept awake while it runs (asleep, it only runs every ~15 min)
        subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        run.start()
        getattr(run, a.harness)()
        record = run.record()
        if run.term is not None:
            run.term.close()
        run.dash.stop(run.sid)
        time.sleep(3)
        captured = os.path.join(run.scratch, "calls.jsonl")
        if not os.path.exists(captured):
            raise SystemExit("the tap saw no calls: is wrap.py the harness's command?")
        calls, longest = fixtures.pick(a.harness, fixtures.captured_calls(captured), run.sid)
        got = fixtures.write(out, a.harness, calls, longest, record if record and os.path.exists(record) else None,
                             {"harness": a.harness, "version": version, "model": model,
                              "made": time.strftime("%Y-%m-%d"), "steps": run.steps})
    finally:
        run.stop()
        if not a.keep:
            run.clean()
        else:
            log(f"kept {run.scratch}")
    have = features(got)
    log(f"wrote {out}: {len(calls)} calls, {len(got['parts'])} parts, {len(got['record'])} record facts, "
        f"{sum(len(w['answer']) + len(w['call']) for w in got['derived'])} derived")
    log("steps:", json.dumps(run.steps))
    missing = [f for f in TARGETS[a.harness] if f not in have]
    log("not triggered:", ", ".join(missing) or "none")
    older = previous(a.harness, version)
    if older and os.path.exists(os.path.join(older, "probe.json")):
        with open(os.path.join(older, "probe.json")) as fh:
            was = set(json.load(fh).get("features") or [])
        log(f"against {os.path.basename(older)}: new {sorted(set(have) - was) or 'none'}; "
            f"gone {sorted(was - set(have)) or 'none'}")
    log("look over expected.json before committing it: an odd reading is a rule to fix, not a fixture to keep")


if __name__ == "__main__":
    main()
