"""What the dashboard shows, read from the context manager's home -- every gatherer's
database, opened read-only, and ag's own logs -- as plain JSON-ready dicts.

    home()                        every gatherer and its agents (channels), with their
                                  status; the hook servers ag started
    agent(gatherer, channel)      one agent over time: each read's size (ag's own count,
                                  the provider's, the harness's limit), its rebuilds, its
                                  tasks and how many had begun by each read, its builds,
                                  and the Gatherer's model calls made for it; and
                                  every token it was sent across its calls, by kind; and
                                  what the user wrote to it as it worked (queued.py's `typed`)
    read(gatherer, read_id)       what one read put in the agent's context, by kind
    context(gatherer, read_id)    every item of it, in order, with its text
    history(gatherer, channel, a, b)  the agent's own events from row a to b: a task's messages
    transcript(gatherer, channel, ...)  its conversation, each event as harness-free parts

An agent is a channel of a gatherer: one harness session (codex's thread, Claude Code's
session, ...), some of them started from the page (sessions.py); which harness, its events' shape tells (`harness_of`). Its STATUS (`status_of`):
CLOSED when the harness's process that made its last call no longer runs; else IDLE when its turn
is over -- its last answer ended without a tool call -- and RUNNING when it is not (waiting on a
tool, or on the model). Where the process is not known (a call from before ag recorded it, not
Linux), a turn left unfinished for more than STALE_SECONDS counts as over. A session the dashboard
started whose process its own end took, or it put away (saved.py's `Rest`) -- sessions.py's `kept` --
is IDLE, not CLOSED; one whose process the dashboard saw end otherwise (closed from the list, exited:
sessions.py's `ended`) is CLOSED where
the process cannot be told, unless something happened for it since. An IDLE agent whose BACKGROUND
tasks still run (`background`) is BACKGROUND: its turn is over, but Claude Code is not done. A RUNNING
agent whose turn waits on the user (`asking`) is ASKING: its newest answer, not yet carried back by a
call, calls a tool of Claude Code's that asks the user in its terminal (ASKS) -- a question, a plan to
approve -- and nothing comes until they answer. Until, that is, Claude Code's own record of the session
says the call has its result (`settled`): answered there, the turn goes on and ag hears of it with the next
call; dismissed there (Esc), no call comes, so ag's record would go on asking -- IDLE instead, its turn over.
Answered from the page (sessions.py's `answer`), its `answer`
says whether Claude Code's result for the call holds what was picked (`recorded`; None: no result yet).
A RUNNING agent may also have stopped where ag does not see it. A model call that FAILED is kept on its
read (`_reads.error`, by ag's hook server): `failing` is the run of them at the newest event the agent's
calls answered -- the harness tries again, each try a read -- and whether a try is under way. Claude Code's
own record of the session (CLAUDE_TAIL's note) says how its turn STOPPED, when its last message there came
after ag last heard of the session (`stopped`): Claude Code's API error -- it gave up on the model call, its
tries spent, or the error not one to try again -- is ERROR; the user's interruption (Esc), which makes no
call, IDLE. A failed call with no try since for GIVE_UP_SECONDS counts as given up too -- with no record to
read (codex; a session of another machine), or one that says nothing: Esc while Claude Code waits to try again
stops it without a word -- ERROR; GIVE_UP_LONG where the record could still say, the endpoint having answered
an error that may ask for a longer wait (Retry-After). `running` is RUNNING or BACKGROUND, or a build running for it. Its `last` is its latest activity: a call (its read), or an
answer to one -- pending (the reply that ends a turn, which no call stores until the user writes again), or
kept on its read (`answered_at`) once a call stored it -- what the page compares with when the reader last
looked at it, to show it FINISHED. Not the events stored: a side call of Claude Code's (a recap, a prompt
suggestion) stores the conversation's -- the reply that ended the turn among them, minutes after it came --
which is no activity of the agent's; only an agent with no reads (a history loaded whole) goes by its newest
event. A REBUILD is a
read whose context comes from another build than the agent's read before it: the condensed
history was replaced.

A BACKGROUND TASK is one Claude Code started and went on without (`background`): a command run in the
background, an agent, a monitor, a workflow. Its tool's result says it started (STARTS) -- an agent that ended
starts again when SendMessage resumes it (RESUMED); Claude Code tells the
model it ended in a `<task-notification>` with a `<status>`, which reaches the gatherer with the next
call -- an agent's end, as soon as it ends, by its report, handed back as a message from it (HANDBACK),
its notification perhaps much later; an agent that stopped while background work of its own runs is
notified too, but WAITING, not ended; a monitor's end may come as its last event, that it expired
(MONITOR_END) -- or TaskStop's result says it was stopped; or Claude Code's own record of the session has its
notification already, written after it started (`_ends`): one the user stopped from Claude Code's list of
them waits there for their next message, and no call carries it till then. One with none still runs, while its
session's process does: none when that process is known gone, or started after the task (a process
the dashboard runs, `session.since`; else the reads that named it). Where the process is not known,
one with no sign of life (its start, its output file changing -- a workflow's, any file in its transcript
folder -- a monitor's event) for STALE_SECONDS
counts as over.

Each read has these sizes: `sent_tokens`, ag's own count of everything it sent (what the
read returned, `_read_items`, added up, by the sizes stored now -- what read() breaks down);
`preamble_tokens`, its count of what the harness sent besides (None: not recorded);
`recorded_tokens`, ag's count of all the call sent, preamble included, as the read log kept it
at the call (`_reads.sent_tokens`, less what the harness left out; None: not kept) -- what ag
believed then, which a size set since (a provider's count, a thinking block no longer sent and
set to 0) does not change; `est_tokens`, the
policy's count of it against its budget (which leaves out the agent's preamble and the
sections' fixed overview); and `real_tokens`, the provider's count. A database written
before a column existed reads as None there. Nothing here writes anything.
"""

import glob
import json
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import home as paths
from . import seen as looked                    # `seen` names a file's stat here
from . import answers, avatars, hiding, live, queued, rollout, saved, sessions
import harness_kit
from harness_kit import Kind, claude as claude_rules, codex as codex_rules
from harness_kit.base import output_of as _output  # noqa: F401 - a tool result's words, as files.py reads them
from harness_kit.shell import CODE_MODE, script_calls

RUNNING_SECONDS = 120          # (no longer decides anything; kept for the page's older copies)
STALE_SECONDS = 1800           # an unfinished turn with no process to ask: over, after this long
RUNNING, IDLE, CLOSED, BACKGROUND, ASKING, ERROR = "running", "idle", "closed", "background", "asking", "error"
#: Claude Code's tools that wait for the user in its terminal before the turn goes on: a question, with
#: options to pick from; a plan, to approve. What each asks, `asking` returns (harness_kit.claude's).
ASKS = claude_rules.ASKS
#: Codex's tool that asks the user in its terminal, its turn waiting on the answer (Plan mode's): a question, with
#: options to pick from -- codex adds "None of the above" to each, with a note in the user's own words.
CODEX_ASKS = {codex_rules.ASK: "question"}
ASK_CHARS = 4000               # the most of a question's words `asking` returns
PLAN_CHARS = 20000             # the most of a plan it returns
#: Claude Code's own record of a session, a line per message as it is made: <its config dir>/projects/<the session's
#: directory, each character but a letter or a digit made '-'>/<session>.jsonl. A question's result is in it the moment
#: it is answered or dismissed; dismissed (Esc), Claude Code's note that the user interrupted it follows.
CLAUDE_TAIL = 1 << 20          # how much of its end is read: what came since the question
INTERRUPTED = "[Request interrupted by user"
STOP_TAIL = 1 << 16            # how much of its end `stopped` reads: its last few lines
GIVE_UP_SECONDS = 90           # a failed call with no try since: given up (Claude Code waits at most ~40 s
                               # between its tries)
GIVE_UP_LONG = 600             # the same for an error answered, where the record could still say (Retry-After)
FAILED_READS = 50              # how many of its newest reads `failing` looks at
ERROR_CHARS = 2000             # the most of an error's words it returns
#: Claude Code's words for a background task's start and end, and where it writes its plans (harness_kit.claude's)
PLAN_FILE, STARTS, SUMMARY, RESUMED = claude_rules.PLAN_FILE, claude_rules.STARTS, claude_rules.SUMMARY, claude_rules.RESUMED
HANDBACK, NOTIFICATION, TASK_ID, TASK_STATUS = (claude_rules.HANDBACK, claude_rules.NOTIFICATION, claude_rules.TASK_ID,
                                                claude_rules.TASK_STATUS)
TASK_EVENT, WAITING, MONITOR_END, STOPPED = (claude_rules.TASK_EVENT, claude_rules.WAITING, claude_rules.MONITOR_END,
                                             claude_rules.STOPPED)
OUTPUT_FILE = claude_rules.OUTPUT_FILE
#: An answer's stop reason, as the provider gives it: the turn goes on (a tool to run, a paused
#: turn, or ag's "streaming": the parts of an answer complete while the rest still streams), or is
#: over. Any other (Codex's `completed` on every answer, none) tells nothing: its last event does.
GOES_ON = {"tool_use", "pause_turn", "streaming"}
OVER = {"end_turn", "stop_sequence", "max_tokens", "refusal"}
CHANNEL = "p_channel"          # the channel property's column (ag.ag_policies.tools.channel)
# A channel's events and reads are found by ifnull(CHANNEL, '') = ?, as ag's indexes on them have it (schema.index):
# by the bare column, SQLite cannot use them and reads every event of the gatherer.


def _connect(gatherer: str) -> Optional[sqlite3.Connection]:
    path = paths.db_path(gatherer)
    if not os.path.exists(path):
        return None
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=8)
    conn.row_factory = sqlite3.Row
    return conn


def _columns(conn, table: str) -> set:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


#: What an actor's views answer before its gatherer has stored anything: ag adds the channel's column
#: with the first event, so a gatherer made (`ag new`) whose first session has sent nothing has none.
NOTHING_YET = {"error": "Nothing stored yet: the session has sent no message through ag."}


def _channels_kept(conn) -> bool:
    return CHANNEL in _columns(conn, "events")


def _tables(conn) -> set:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _seconds(value) -> Optional[float]:
    """Seconds since the epoch, from an ISO time or a number; None if neither."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.timestamp()


def gatherer_names() -> List[str]:
    root = paths.gatherers_dir()
    if not os.path.isdir(root):
        return []
    return sorted(n for n in os.listdir(root)                 # a database, or a config: made, no session yet
                  if any(os.path.exists(os.path.join(root, n, f)) for f in ("context.db", "gatherer.toml")))


def _made(gatherer: str) -> Optional[float]:
    """When the gatherer's config was written: when it was made, for one no session has run in yet."""
    try:
        return os.path.getmtime(os.path.join(paths.gatherer_dir(gatherer), "gatherer.toml"))
    except OSError:
        return None


def _policy(gatherer: str) -> Optional[str]:
    try:
        with open(os.path.join(paths.gatherer_dir(gatherer), "gatherer.toml"), encoding="utf-8") as fh:
            for line in fh:
                if line.strip().startswith("policy"):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return None


def _running_builds(conn) -> set:
    if "_builds" not in _tables(conn):
        return set()
    return {r[0] for r in conn.execute("SELECT channel_key FROM _builds WHERE status = 'running'")}


def _hook_servers() -> List[dict]:
    try:
        return paths.hook_servers()
    except Exception:  # noqa: BLE001 - the dashboard shows what it can
        return []


def home(started: Optional[List[dict]] = None) -> dict:
    """Every gatherer and its agents, each newest created first (`created`: its first event), and
    the hook servers ag started, which gatherers the reader hid or kept (`hiding`, hiding.py), which
    actors they saved for later (`saved`, saved.py), and when they last looked at each (`seen`, seen.py:
    None, never kept).
    `started` is the sessions started from the page (sessions.py's `list`; else its table, read):
    each one's agent carries it as `session`, and one with no events yet -- its gatherer perhaps
    not made yet -- is listed all the same."""
    now = time.time()
    gatherers = []
    for name in gatherer_names():
        conn = _connect(name)
        if conn is None:                 # made (`ag new`), no session has run in it yet
            gatherers.append({"name": name, "policy": _policy(name), "agents": [], "last": None})
            continue
        try:
            agents = _agents(conn, now)
        except sqlite3.Error as exc:
            gatherers.append({"name": name, "policy": _policy(name), "error": str(exc), "agents": [], "last": None})
            continue
        finally:
            conn.close()
        gatherers.append({"name": name, "policy": _policy(name), "agents": agents,
                          "last": max((a["last"] or 0 for a in agents), default=0) or None})
    _with_started(gatherers, sessions.stored() if started is None else started, now)
    records, wakes = {}, {}              # the records of the sessions waiting on the user, on background work, or running:
                                         # watched from now on
    for g in gatherers:
        for a in g["agents"]:
            record, wake = a.pop("record", None), a.pop("wake", None)
            if record:
                records[record[0]] = (g["name"], a["channel"], record[1])
            if wake:
                wakes[(g["name"], a["channel"])] = wake
    live.watch_records(records)
    live.wake_at(wakes)
    for g in gatherers:                  # when it was made: its first event, else its config's time
        g["created"] = min((a["created"] for a in g["agents"] if a.get("created")), default=None) or _made(g["name"])
    gatherers.sort(key=lambda g: g.get("created") or 0, reverse=True)
    return {"home": paths.HOME, "now": now, "running_seconds": RUNNING_SECONDS, "gatherers": gatherers,
            "hook_servers": _hook_servers(), "hiding": hiding.stored(), "saved": saved.stored(),
            "seen": looked.stored()}


def actors(gatherer: str, channels: set, started: List[dict]) -> List[dict]:
    """The agents `channels` of `gatherer`, each as home() has it, with `started`'s sessions of them (sessions.py's
    `list`) -- read for them alone, so at a small part of its cost; nothing is watched from it from now on (home()'s
    records and wakes stay as they were). sqlite3.Error: the gatherer's database could not be read."""
    now = time.time()
    conn = _connect(gatherer)
    try:
        agents = _agents(conn, now, set(channels)) if conn is not None else []
    finally:
        if conn is not None:
            conn.close()
    g = [{"name": gatherer, "agents": agents, "last": None}]
    _with_started(g, [s for s in started if s["gatherer"] == gatherer and s["session_id"] in channels], now)
    for a in g[0]["agents"]:                     # what home() would watch: not from here
        a.pop("record", None)
        a.pop("wake", None)
    return g[0]["agents"]


def _with_started(gatherers: List[dict], started: List[dict], now: Optional[float] = None) -> None:
    by_name = {g["name"]: g for g in gatherers}
    for s in started:
        g = by_name.get(s["gatherer"])
        if g is None:                    # a new gatherer: ag makes it on the session's first call
            g = by_name[s["gatherer"]] = {"name": s["gatherer"], "policy": None, "agents": [], "last": None}
            gatherers.append(g)
        a = next((x for x in g["agents"] if x["channel"] == s["session_id"]), None)
        if a is None:
            a = {"channel": s["session_id"], "events": 0, "last_event": None, "reads": 0, "last_read": None,
                 "cwd": s["cwd"], "tasks": 0, "est_tokens": None, "real_tokens": None, "limit_tokens": None,
                 "sent_tokens": None, "harness": s["harness"], "last_user_message": None, "recap": None, "name": None,
                 "created": None, "last": _seconds(s["created_at"]), "building": False, "running": False,
                 "turn_over": True, "status": IDLE}
            g["agents"].append(a)
        a["session"] = s
        offer = a.pop("offer", None)             # a codex plan: asked about where its terminal is the dashboard's, not
        if offer and s.get("terminal") and a["status"] == IDLE and (s.get("since") or 0) <= offer["at"] \
                and not (s.get("typed") and s["typed"] >= offer["at"]):     # restarted since, nor anything typed there
            a["asking"], a["status"] = offer, ASKING
        if s.get("answer"):                      # the last answer typed from the page: what the harness made of it
            result = rollout.result(rollout.read(rollout.record(a["channel"])), s["answer"]["call"]) \
                if a.get("harness") == "codex" else _result(s["gatherer"], a["channel"], s["answer"]["call"])
            a["answer"] = {**s["answer"], "result": _clip(result, ASK_CHARS) if result else None,
                           "recorded": answers.recorded(result, s["answer"]["expect"])}
        if a.get("holder") and paths.runs_under(a["holder"]["pid"], s.get("pid")):
            a["holder"]["dashboard"] = True          # the dashboard's own agent or terminal (or a process under it)
        a["created"] = min((x for x in (a["created"], _seconds(s["created_at"])) if x), default=None)
        if s["status"] in ("starting", "running") or s.get("queued"):   # its agent works, or a message waits for it
            a["status"], a["running"] = RUNNING, True
        elif s.get("kept") and a["status"] == CLOSED and (a["last"] or 0) <= s["kept"]:
            a["status"] = IDLE                   # ended by the dashboard's own end, not closed, nor used since
        elif s.get("ended") and not s.get("kept") and not s.get("pid") and a.get("alive") is None and not a.get("holder") \
                and (a["last"] or 0) <= s["ended"]:
            a["status"], a["running"] = CLOSED, bool(a.get("building"))   # its process gone, seen ending here, not used since
        g["last"] = max(g["last"] or 0, a["last"] or 0) or None
    for g in gatherers:                  # newest created first, as `_agents` has them
        for a in g["agents"]:
            a.pop("offer", None)
            a["chattable"] = chattable(a)
            _settle_background(a, time.time() if now is None else now)
        g["agents"].sort(key=lambda a: a.get("created") or 0, reverse=True)


def chattable(a: dict) -> bool:
    """Whether the page may message the agent: a Claude Code or codex session (the harnesses the dashboard
    runs), with a directory to resume it in, that no other process has open (its `holder`, else the
    process its last call named) -- the dashboard's own agent or terminal aside, and any process under it
    (codex's real codex, under its wrapper)."""
    if a.get("harness") not in (*sessions.HARNESSES, None) or not (a.get("cwd") or a.get("session")):
        return False
    held = a.get("holder")
    if held:
        return bool(held.get("dashboard"))
    return a.get("alive") is not True or bool(a.get("session") and paths.runs_under(a.get("pid"), a["session"].get("pid")))


def _agents(conn, now: float, only: Optional[set] = None) -> List[dict]:
    """The gatherer's agents (`only`: those channels of them alone)."""
    if CHANNEL not in _columns(conn, "events"):
        return []
    sizes = [c for c in ("est_tokens", "real_tokens", "limit_tokens") if c in _columns(conn, "_reads")]
    out: Dict[str, dict] = {}
    which = "" if only is None else f" AND {CHANNEL} IN ({', '.join('?' * len(only))})"
    for r in conn.execute(f"SELECT {CHANNEL} AS ch, count(*) AS n, min(inserted_at) AS first, max(inserted_at) AS last FROM events "
                          f"WHERE {CHANNEL} IS NOT NULL{which} GROUP BY {CHANNEL}", tuple(only or ())):
        out[r["ch"]] = {"channel": r["ch"], "events": r["n"], "created": _seconds(r["first"]), "last_event": _seconds(r["last"]), "reads": 0,
                        "last_read": None, "cwd": None, "tasks": 0, "est_tokens": None, "real_tokens": None,
                        "limit_tokens": None, "sent_tokens": None, "pid": None, "alive": None}
    if CHANNEL in _columns(conn, "_reads"):
        cols = _columns(conn, "_reads")
        answer = "max(answered_at)" if "answered_at" in cols else "NULL"
        for r in conn.execute(f"SELECT {CHANNEL} AS ch, count(*) AS n, max(read_at) AS last, {answer} AS answered "
                              f"FROM _reads GROUP BY {CHANNEL}"):
            if r["ch"] in out:
                out[r["ch"]].update(reads=r["n"], last_read=_seconds(r["last"]), last_answer=_seconds(r["answered"]))
        cwd = "p_cwd" in cols
        process = [c for c in ("pid", "pid_started") if c in cols]
        for ch, a in out.items():
            last = conn.execute(f"SELECT {', '.join(['read_id'] + sizes + (['p_cwd'] if cwd else []))} FROM _reads "
                                f"WHERE ifnull({CHANNEL}, '') = ? ORDER BY read_id DESC LIMIT 1", (ch,)).fetchone()
            if last is not None:
                a.update({k: last[k] for k in sizes}, cwd=last["p_cwd"] if cwd else None,
                         sent_tokens=_sent(conn, last["read_id"]))
            if len(process) == 2:                    # the newest call that named its process
                p = conn.execute(f"SELECT pid, pid_started FROM _reads WHERE ifnull({CHANNEL}, '') = ? AND pid IS NOT NULL "
                                 f"ORDER BY read_id DESC LIMIT 1", (ch,)).fetchone()
                if p is not None:
                    a["pid"], a["alive"] = p["pid"], paths.process_alive(p["pid"], p["pid_started"])
                    a["since"] = _seconds(conn.execute(f"SELECT min(read_at) FROM _reads WHERE ifnull({CHANNEL}, '') = ? AND pid = ? "
                                                       "AND pid_started = ?", (ch, p["pid"], p["pid_started"])).fetchone()[0])
    if "_open" in _tables(conn):                     # which process has each session open (ag's launcher, its calls)
        for ch, pid, started, by, opened in conn.execute("SELECT session, pid, pid_started, opened_by, opened_at FROM _open"):
            if ch in out and paths.process_alive(pid, started) is not False:
                out[ch]["holder"] = {"pid": pid, "by": by}
                out[ch]["pid"], out[ch]["alive"], out[ch]["since"] = pid, True, _seconds(opened)
    if "tasks" in _tables(conn):
        for r in conn.execute("SELECT channel_key AS ch, count(*) AS n FROM tasks GROUP BY channel_key"):
            if r["ch"] in out:
                out[r["ch"]]["tasks"] = r["n"]
    answered = {}                                    # each agent's newest pending answer: one no call has carried yet
    if "_pending" in _tables(conn) and CHANNEL in _columns(conn, "_pending"):
        answered = {ch: _seconds(t) for ch, t in conn.execute(
            f"SELECT {CHANNEL}, max(received_at) FROM _pending WHERE {CHANNEL} IS NOT NULL GROUP BY {CHANNEL}")}
    building = _running_builds(conn)
    background = _background(conn)
    last_user = {}                                   # each agent's newest user message: what it was last asked --
    for ch, text, payload in conn.execute(           # not a background agent's report, which comes as one (HANDBACK)
            f"SELECT e.{CHANNEL}, e.text, e.payload_json FROM events e JOIN event_types t ON t.event_type_id = e.event_type_id "
            f"WHERE t.name = 'user_message' AND e.row_id IN (SELECT max(e2.row_id) FROM events e2 "
            f"JOIN event_types t2 ON t2.event_type_id = e2.event_type_id WHERE t2.name = 'user_message' "
            f"AND ifnull(e2.text, '') NOT LIKE '%[Subagent hand-back]%' GROUP BY e2.{CHANNEL})"):
        last_user[ch] = (text if text else readable(payload)) or ""
    tables = _tables(conn)
    recaps = {}                                      # each agent's newest recap (Claude Code's, while the user was away)
    if "_recaps" in tables:
        for ch, made, text in conn.execute("SELECT session, made_at, text FROM _recaps WHERE recap_id IN "
                                           "(SELECT max(recap_id) FROM _recaps GROUP BY session)"):
            recaps[ch] = {"text": " ".join((text or "").split())[:600], "at": _seconds(made)}
    names = {}                                       # each agent's name: the user's, else the newest another gave
    if "_names" in tables:                           # (codex's title for its thread)
        for ch, by, text in conn.execute("SELECT session, by, text FROM _names ORDER BY by = 'user', named_at"):
            names[ch] = {"text": " ".join((text or "").split())[:120], "by": by}
    for ch, a in out.items():
        a["harness"] = _harness(conn, ch)
        said = harness_kit.words(last_user.get(ch, ""), a["harness"])[1]          # as the user typed it
        a["last_user_message"] = " ".join(said.split())[:600] or None
        a["recap"] = recaps.get(ch)
        a["name"] = names.get(ch)
        a["last"] = max(a["last_read"] or 0, a.get("last_answer") or 0, answered.get(ch) or 0,   # its latest activity:
                        0 if a["reads"] else a["last_event"] or 0) or None                     # not a side call's events
        a["building"] = ch in building
        a["turn_over"] = turn_over(conn, ch, tables)[0]
        a["status"] = status_of(a.get("alive"), a["turn_over"], a["last"], now)
        if a["harness"] == "codex":
            _codex_status(conn, ch, a, tables, now)
        else:
            _claude_status(conn, ch, a, tables, now)
        a["running"] = a["building"] or a["status"] == RUNNING
        a["background"] = background.get(ch, []) + a.pop("codex_background", [])
    return sorted(out.values(), key=lambda a: a["created"] or 0, reverse=True)   # in place: newest created first


def _claude_status(conn, ch: str, a: dict, tables: set, now: float) -> None:
    """The agent's status as Claude Code's own record of the session tells it (module doc): what it asks the user,
    whether it was answered or dismissed there, and whether its turn stopped on an error or was interrupted."""
    a["asking"] = asking(conn, ch, tables) if a["status"] == RUNNING else None
    record = queued.record(ch, a.get("cwd")) if a["asking"] and a["harness"] in ("claude", None) else None
    seen = live._stat(record) if record else None   # before it is read: a change after it is noticed
    how = settled(ch, a.get("cwd"), a["asking"]["call"], record) if record else None
    if a["asking"] and not how and record:
        a["record"] = (record, seen)                 # watched (live.py) while it asks
    if how:
        a["asking"] = None
        if how == "dismissed":
            a["status"], a["turn_over"] = IDLE, True
    if a["asking"]:
        a["status"] = ASKING
    a["failing"] = failing(conn, ch) if a["status"] == RUNNING else None
    claude = a["harness"] in ("claude", None)
    record = (record or queued.record(ch, a.get("cwd"))) if a["status"] == RUNNING and claude else None
    seen = live._stat(record) if record else None   # before it is read: a change after it is noticed
    a["stopped"] = stopped(record, a["last"]) if record else None
    if a["stopped"] and a["stopped"]["kind"] == "interrupted":
        a["status"], a["turn_over"], a["failing"] = IDLE, True, None
    elif a["stopped"] or (a["failing"] and given_up(a["failing"], bool(record), now)):
        a["status"], a["turn_over"] = ERROR, True
    elif a["failing"] and not a["failing"]["retrying"]:
        a["wake"] = a["failing"]["at"] + give_up_after(a["failing"], bool(record)) + 1   # when it would be given up
    if a["status"] == RUNNING and record and not a.get("record"):
        a["record"] = (record, seen)                 # watched (live.py) while it runs: it may stop unseen


def _codex_status(conn, ch: str, a: dict, tables: set, now: float) -> None:
    """The agent's status as codex's own record of the thread tells it (rollout.py; module doc): its turn over,
    interrupted (Esc) or stopped on an error where ag heard nothing of it; what it asks the user (`codex_asking`) --
    a plan it proposed kept as `offer`, for `_with_started` to show only where the dashboard's terminal shows codex
    asking whether to implement it; and the subagents and commands it left running, as `codex_background`."""
    path = rollout.record(ch) if a["status"] in (RUNNING, IDLE) else None
    seen = live._stat(path) if path else None       # before it is read: a change after it is noticed
    rec = rollout.read(path)
    a["stopped"] = None
    a["failing"] = failing(conn, ch) if a["status"] == RUNNING else None
    got = rollout.stopped(rec, a["last"]) if a["status"] == RUNNING else None
    if got and got["kind"] == "error":
        a["stopped"], a["status"], a["turn_over"] = got, ERROR, True
    elif got:                                        # over, or interrupted: its turn ended with no call ag saw
        a["stopped"] = got if got["kind"] == "interrupted" else None
        a["status"], a["turn_over"], a["failing"] = IDLE, True, None
    elif a["failing"] and given_up(a["failing"], bool(rec), now):
        a["status"], a["turn_over"] = ERROR, True
    elif a["failing"] and not a["failing"]["retrying"]:
        a["wake"] = a["failing"]["at"] + give_up_after(a["failing"], bool(rec)) + 1
    ask = codex_asking(conn, ch, tables, a["status"], rec) if a["status"] in (RUNNING, IDLE) else None
    offer = bool(ask) and ask["kind"] == "plan" and ask["call"].startswith("plan:")   # its proposed plan, not a call
    a["asking"] = None if offer else ask
    if offer:
        a["offer"] = ask
    elif ask and not ask.get("async"):               # its turn waits on the answer; an async one's goes on
        a["status"] = ASKING
    a["codex_background"] = [{"id": t["id"], "kind": "agent", "label": t["path"], "started": t["started"], "output": None,
                              "event": None, "event_at": None} for t in rollout.agents(rec)] + \
                            [{"id": t["id"], "kind": "command", "label": t["label"], "started": t["started"], "output": None,
                              "event": None, "event_at": None} for t in rollout.commands(rec)]
    if path and (a["status"] in (RUNNING, ASKING) or ask or a["codex_background"]):
        a["record"] = (path, seen)                   # watched (live.py): it may stop, be answered, end, unseen


def turn_over(conn, channel: str, tables: set):
    """(whether the channel's turn is over, the time of what says so): from its pending answer --
    its stop reason (GOES_ON / OVER), else its last event: an assistant message ends a turn, a tool
    call does not -- else, with none pending, from its newest stored event: an assistant message
    (a turn stored whole), or else not (a user message or a tool's output: the model is answering)."""
    if "_pending" in tables and CHANNEL in _columns(conn, "_pending"):
        stop = "stop" in _columns(conn, "_pending")
        last = conn.execute(f"SELECT type, received_at{', stop' if stop else ''} FROM _pending WHERE {CHANNEL} = ? "
                            "ORDER BY pending_id DESC LIMIT 1", (channel,)).fetchone()
        if last is not None:
            why = last["stop"] if stop else None
            over = False if why in GOES_ON else True if why in OVER else last["type"] == "agent_message"
            return over, _seconds(last["received_at"])
    last = conn.execute(f"SELECT t.name, e.inserted_at FROM events e JOIN event_types t ON t.event_type_id = e.event_type_id "
                        f"WHERE ifnull(e.{CHANNEL}, '') = ? AND t.name NOT IN ('environment_update', 'context_stream') "
                        "ORDER BY e.row_id DESC LIMIT 1", (channel,)).fetchone()
    if last is None:
        return True, None
    return last[0] == "agent_message", _seconds(last[1])


def asking(conn, channel: str, tables: set) -> Optional[dict]:
    """What the agent waits on the user for (module doc), None if nothing: from its newest pending answer,
    its calls to a tool of ASKS -- {kind: "question" or "plan", at: when it was answered, call: the call's
    id, questions: [{header, question, multiSelect, options: [{label, description}]}] or plan: its text}."""
    if "_pending" not in tables or CHANNEL not in _columns(conn, "_pending"):
        return None
    rows = conn.execute(f"SELECT answer, received_at, type, payload_json FROM _pending WHERE {CHANNEL} = ? "
                        "ORDER BY pending_id DESC", (channel,)).fetchall()
    for r in rows:
        if r["answer"] != rows[0]["answer"]:
            break                                    # an earlier answer's
        if r["type"] != "tool_call":
            continue
        try:
            payload = json.loads(r["payload_json"])
            content = payload.get("content")
        except (ValueError, AttributeError):
            continue
        if payload.get("type") == "function_call" and payload.get("name") in CODEX_ASKS:
            try:                                     # codex's: its arguments a JSON string
                got = json.loads(payload.get("arguments") or "{}")
            except ValueError:
                got = {}
            return {"kind": CODEX_ASKS[payload["name"]], "harness": "codex", "at": _seconds(r["received_at"]),
                    "call": payload.get("call_id"), "questions": codex_questions(got.get("questions") if isinstance(got, dict) else None)}
        for b in content if isinstance(content, list) else []:
            if not isinstance(b, dict) or b.get("type") != "tool_use" or b.get("name") not in ASKS:
                continue
            got = b.get("input") if isinstance(b.get("input"), dict) else {}
            out = {"kind": ASKS[b["name"]], "at": _seconds(r["received_at"]), "call": b.get("id")}
            if out["kind"] == "plan":
                out["plan"] = _clip(got["plan"], PLAN_CHARS) if isinstance(got.get("plan"), str) else _plan(conn, channel, [x["payload_json"] for x in rows])
            else:
                out["questions"] = [{"header": q.get("header"), "question": _clip(q.get("question"), ASK_CHARS),
                                     "multiSelect": bool(q.get("multiSelect")),
                                     "options": [{"label": o.get("label"), "description": _clip(o.get("description"), ASK_CHARS)}
                                                 for o in q.get("options") or [] if isinstance(o, dict)]}
                                    for q in got.get("questions") or [] if isinstance(q, dict)]
            return out
    return None


def codex_questions(given) -> List[dict]:
    """Codex's questions (request_user_input's: {id, header, question, options: [{label, description}]}; the
    async one's: {title, options: [label]}) as `asking` returns them, each with its `id` (None: the async one's)."""
    out = []
    for q in given if isinstance(given, list) else []:
        if not isinstance(q, dict):
            continue
        options = [o if isinstance(o, dict) else {"label": str(o)} for o in q.get("options") or [] if isinstance(o, (dict, str))]
        out.append({"id": q.get("id"), "header": q.get("header"), "question": _clip(q.get("question") or q.get("title"), ASK_CHARS),
                    "multiSelect": False, "options": [{"label": o.get("label"), "description": _clip(o.get("description"), ASK_CHARS)}
                                                      for o in options]})
    return out


def codex_asking(conn, channel: str, tables: set, status: str, record) -> Optional[dict]:
    """What a codex agent waits on the user for (module doc), None if nothing: RUNNING, a question it asked in its
    terminal (`asking`) while codex's record (`record`, rollout.py's) does not say it was answered or dismissed, else
    one it asked as its turn goes on (async: True); its turn over (IDLE), the plan it proposed, which its terminal
    asks whether to implement -- {kind: "plan", call: "plan:<its turn>", at: when the turn ended, plan}."""
    if status == RUNNING:
        ask = asking(conn, channel, tables)
        if ask is not None and not rollout.settled(record, ask["call"]):
            return ask
        got = rollout.open_question(record)
        return {"kind": "question", "harness": "codex", "async": True, "at": got["at"], "call": got["call"],
                "questions": codex_questions(got["questions"])} if got else None
    got = rollout.offer(record) if status == IDLE else None
    return {"kind": "plan", "harness": "codex", "at": got["at"], "call": f"plan:{got['turn']}",
            "plan": _clip(got["text"], PLAN_CHARS)} if got else None


def asking_of(gatherer: str, channel: str, cwd: Optional[str] = None) -> Optional[dict]:
    """What the agent waits on the user for now (`asking`, less what Claude Code's record says is `settled`; a codex
    agent's, `codex_asking`), None if nothing; `cwd`, where the session runs."""
    conn = _connect(gatherer)
    if conn is None:
        return None
    try:
        if not _channels_kept(conn):
            return None
        tables = _tables(conn)
        if _harness(conn, channel) == "codex":
            over = turn_over(conn, channel, tables)[0]
            return codex_asking(conn, channel, tables, IDLE if over else RUNNING, rollout.read(rollout.record(channel)))
        ask = asking(conn, channel, tables)
    finally:
        conn.close()
    return None if ask is None or settled(channel, cwd, ask["call"]) else ask


def failing(conn, channel: str) -> Optional[dict]:
    """The agent's model calls failing now (module doc), None if they are not: the run of failed calls at its
    newest read -- or at the one before, the newest a try under way (no error, no count yet) at the same event
    -- that answered the same event. {at: when the newest began, first: the run's first, attempts: how many
    failed, status: the newest's HTTP status (None: no answer came), error: why, retrying: a try under way}."""
    cols = _columns(conn, "_reads")
    if "error" not in cols or CHANNEL not in cols:
        return None                                   # a file from before ag kept failures
    counted = "real_tokens" if "real_tokens" in cols else "NULL AS real_tokens"
    rows = conn.execute(f"SELECT read_at, row_id, {counted}, error_status, error FROM _reads WHERE ifnull({CHANNEL}, '') = ? "
                        "ORDER BY read_id DESC LIMIT ?", (channel, FAILED_READS)).fetchall()
    retrying = bool(rows) and rows[0]["error"] is None
    if retrying:                                      # a try under way, after a failure at the same event
        if rows[0]["real_tokens"] is not None or len(rows) < 2 or rows[1]["error"] is None \
                or rows[1]["row_id"] != rows[0]["row_id"]:
            return None
        rows = rows[1:]
    run = []
    for r in rows:
        if r["error"] is None or r["row_id"] != rows[0]["row_id"]:
            break
        run.append(r)
    if not run:
        return None
    return {"at": _seconds(run[0]["read_at"]), "first": _seconds(run[-1]["read_at"]), "attempts": len(run),
            "status": run[0]["error_status"], "error": _clip(run[0]["error"], ERROR_CHARS), "retrying": retrying}


def give_up_after(failure: dict, record: bool) -> float:
    """How long after a failed call (`failing`) with no try since the harness counts as having given up:
    GIVE_UP_LONG where its endpoint answered an error (it may have asked for a long wait) and Claude Code's
    record could still say; else GIVE_UP_SECONDS."""
    return GIVE_UP_LONG if record and failure["status"] is not None else GIVE_UP_SECONDS


def given_up(failure: dict, record: bool, now: float) -> bool:
    """Whether the harness has given up on a failed call (`failing`), as far as time tells: no try under way, and
    none for `give_up_after`."""
    return not failure["retrying"] and now - (failure["at"] or now) > give_up_after(failure, record)


def stopped(path: str, since: Optional[float]) -> Optional[dict]:
    """How Claude Code's record of the session (`path`) says its turn stopped, after `since` -- when ag last heard
    of it -- where ag does not see it: its last message (not a subagent's), if it came after `since`, is Claude
    Code's API error -- {kind: "error", at, text: its words, status: the HTTP status it names} -- or the user's
    interruption -- {kind: "interrupted", at}. None: its last message is neither, or is older, or can't be read."""
    try:
        with open(path, "rb") as fh:
            size = os.path.getsize(path)
            fh.seek(max(0, size - STOP_TAIL))
            lines = fh.read().split(b"\n")
    except OSError:
        return None
    if size > STOP_TAIL:
        lines = lines[1:]                             # begun before what was read
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            m = json.loads(line)
        except ValueError:
            return None                               # a line being written, or cut: can't tell
        if not isinstance(m, dict) or m.get("type") not in ("user", "assistant") or m.get("isSidechain"):
            continue                                  # Claude Code's own notes (a turn's length, a title, ...)
        at = _seconds(m.get("timestamp"))
        if at is None or (since is not None and at < since):
            return None
        if m["type"] == "assistant" and m.get("isApiErrorMessage"):
            text = " ".join(str(b.get("text") or "") for b in _blocks(line) if b.get("type") == "text").strip()
            return {"kind": "error", "at": at, "text": _clip(text, ERROR_CHARS) or None,
                    "status": m.get("apiErrorStatus") if isinstance(m.get("apiErrorStatus"), int) else None}
        if m["type"] == "user" and any(b.get("type") == "text" and str(b.get("text", "")).startswith(INTERRUPTED)
                                       for b in _blocks(line, role="user")):
            return {"kind": "interrupted", "at": at}
        return None
    return None


def settled(session: str, cwd: Optional[str], call: Optional[str], path: Optional[str] = None) -> Optional[str]:
    """How Claude Code's own record of the session (`path`, else found) says the call ended: "answered", "dismissed"
    (its result, then Claude Code's note that the user interrupted it: Esc), or None -- no result yet, or no record."""
    path = (path or queued.record(session, cwd)) if call else None
    if path is None:
        return None
    try:
        with open(path, "rb") as fh:
            fh.seek(max(0, os.path.getsize(path) - CLAUDE_TAIL))
            lines = fh.read().split(b"\n")
    except OSError:
        return None
    key = call.encode()
    for i, line in enumerate(lines):
        if key not in line:
            continue
        blocks = _blocks(line)
        if not any(b.get("type") == "tool_result" and b.get("tool_use_id") == call for b in blocks):
            continue
        for after in lines[i + 1:i + 6]:                  # what Claude Code wrote right after it
            got = _blocks(after, role="user")
            if any(b.get("type") == "text" and str(b.get("text", "")).startswith(INTERRUPTED) for b in got):
                return "dismissed"
            if _blocks(after, role="assistant"):
                break
        return "answered"
    return None


def _blocks(line: bytes, role: Optional[str] = None) -> List[dict]:
    """The content blocks of a line of Claude Code's record, if it is a message (of `role`); else none."""
    try:
        m = json.loads(line)
    except ValueError:
        return []
    msg = m.get("message") if isinstance(m, dict) else None
    if not isinstance(msg, dict) or (role and msg.get("role") != role):
        return []
    content = msg.get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def _result(gatherer: str, channel: str, call: Optional[str]) -> Optional[str]:
    """The words of the tool's result for `call` once a call has carried it, None before."""
    conn = _connect(gatherer) if call else None
    if conn is None:
        return None
    try:
        if not _channels_kept(conn):
            return None
        r = conn.execute(f"SELECT e.text, e.payload_json FROM events e JOIN event_types t ON t.event_type_id = e.event_type_id "
                         f"WHERE t.name = 'tool_output' AND ifnull(e.{CHANNEL}, '') = ? AND instr(e.payload_json, ?) > 0 "
                         "ORDER BY e.row_id DESC LIMIT 1", (channel, json.dumps(call))).fetchone()
        return (r["text"] or readable(r["payload_json"]) or "") if r else None
    finally:
        conn.close()


def _plan(conn, channel: str, pending: List[str]) -> Optional[str]:
    """The plan the agent asks to have approved, where its call does not carry it: the file of Claude Code's
    plans (PLAN_FILE) it last wrote to -- in the answer that asks (`pending`, its events' payloads, newest
    first), else before it -- as it is now, else as that write had it. None: none written."""
    stored = (p for (p,) in conn.execute(
        f"SELECT payload_json FROM events WHERE ifnull({CHANNEL}, '') = ? AND payload_json LIKE '%/.claude/plans/%' "
        "ORDER BY row_id DESC LIMIT 20", (channel,)))
    for payload in [*pending, *stored]:
        try:
            content = json.loads(payload).get("content")
        except (ValueError, AttributeError):
            continue
        for b in reversed(content if isinstance(content, list) else []):
            got = b.get("input") if isinstance(b, dict) and b.get("type") == "tool_use" else None
            path = got.get("file_path") if isinstance(got, dict) else None
            if not isinstance(path, str) or not PLAN_FILE.search(path):
                continue
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    return _clip(fh.read(PLAN_CHARS + 1), PLAN_CHARS)
            except OSError:
                return _clip(got["content"], PLAN_CHARS) if isinstance(got.get("content"), str) else None
    return None


def status_of(alive: Optional[bool], over: bool, last: Optional[float], now: float) -> str:
    """CLOSED, IDLE or RUNNING (module doc): `alive`, whether the harness's process runs (None:
    not known); `over`, whether the turn is; `last`, when anything last happened for it."""
    if alive is False:
        return CLOSED
    if over:
        return IDLE
    if alive is None and (last is None or now - last > STALE_SECONDS):
        return IDLE
    return RUNNING


_BACKGROUND: Dict[str, dict] = {}   # database -> {row: the last row read, tasks: {channel: {id: task}}}, ended ones
                                    # kept (`open` False): an agent resumed is the same task, its file the same
_BACKGROUND_LOCK = threading.Lock()
BACKGROUND_SCAN = ("SELECT e.row_id, e.{ch} AS ch, t.name AS type, e.text, e.payload_json, e.inserted_at FROM events e "
                   "JOIN event_types t ON t.event_type_id = e.event_type_id WHERE e.row_id > ? AND e.row_id <= ? "
                   "AND e.{ch} IS NOT NULL AND ((t.name = 'tool_output' AND (e.text LIKE 'Command running in background%' "
                   "OR e.text LIKE 'Async agent launched%' OR e.text LIKE 'Monitor started (task %' "
                   "OR e.text LIKE 'Workflow launched in background%' "
                   "OR e.text LIKE '%Successfully stopped task: %' OR e.text LIKE '{{%\"resumedAgentId\"%')) "
                   "OR (t.name IN ('context', 'user_message') AND (e.text LIKE '%<task-notification>%' "
                   "OR e.text LIKE '%[Subagent hand-back]%'))) ORDER BY e.row_id")


def _background(conn) -> Dict[str, List[dict]]:
    """Each channel's background tasks that started and have not ended (module doc), oldest first:
    {id, kind, label, started, output (its file, None: none named), event (a monitor's last), event_at}.
    The database's events are read once: kept, each time only the rows added since are."""
    path = next((r[2] for r in conn.execute("PRAGMA database_list") if r[1] == "main"), "")
    top = conn.execute("SELECT max(row_id) FROM events").fetchone()[0] or 0
    with _BACKGROUND_LOCK:
        seen = _BACKGROUND.get(path)
        if seen is None or top < seen["row"]:           # new, or not the database it was
            seen = _BACKGROUND[path] = {"row": 0, "tasks": {}}
        if top > seen["row"]:
            for r in conn.execute(BACKGROUND_SCAN.format(ch=CHANNEL), (seen["row"], top)):
                _background_event(conn, seen["tasks"].setdefault(r["ch"], {}), r)
            seen["row"] = top
        out = {ch: [{k: v for k, v in t.items() if k != "open"} for t in tasks.values() if t["open"]]
               for ch, tasks in seen["tasks"].items()}
        return {ch: open_ for ch, open_ in out.items() if open_}


def _background_event(conn, tasks: Dict[str, dict], r) -> None:
    """One event of the scan, on its channel's `tasks`: a start, an end, or a monitor's event."""
    text = r["text"] or ""
    if r["type"] == "tool_output":
        stopped = STOPPED.match(text)
        if stopped:
            _end(tasks, stopped.group(1))
            return
        resumed = RESUMED.match(text)
        if resumed:                                  # an agent sent a message after it ended: it runs again
            before = tasks.get(resumed.group(1)) or {"id": resumed.group(1), "kind": "agent", "output": None, "label": None}
            tasks[before["id"]] = {**before, "open": True, "started": _seconds(r["inserted_at"]), "event": None, "event_at": None,
                                   "label": _task_label(conn, r["ch"], r["row_id"], r["payload_json"]) or before["label"]}
            return
        for pattern, kind in STARTS:
            m = pattern.match(text)
            if m:
                out, summary = OUTPUT_FILE.search(text), SUMMARY.search(text)
                tasks[m.group(1)] = {"id": m.group(1), "kind": kind, "started": _seconds(r["inserted_at"]),
                                     "output": (out.group(1) or out.group(2)) if out else None, "event": None, "event_at": None,
                                     "label": summary.group(1).strip()[:160] if summary
                                     else _task_label(conn, r["ch"], r["row_id"], r["payload_json"]), "open": True}
                return
        return
    for back in HANDBACK.finditer(text):             # an agent's report: it has ended
        _end(tasks, back.group(1))
    for note in NOTIFICATION.finditer(text):
        found = TASK_ID.search(note.group(1))
        task = tasks.get(found.group(1)) if found else None
        if task is None or not task["open"]:
            continue
        event = TASK_EVENT.search(note.group(1))
        if WAITING.search(note.group(1)):            # an agent stopped, its own background work running: not ended
            task["event"], task["event_at"] = "waiting on its own background work", _seconds(r["inserted_at"])
        elif _ending(note.group(1)):
            _end(tasks, task["id"])                  # it ended: completed, failed, killed; a monitor expired
        else:                                        # a monitor's event: it lives
            task["event"] = " ".join(event.group(1).split())[:200] if event else None
            task["event_at"] = _seconds(r["inserted_at"])


def _ending(note: str) -> bool:
    """Whether a task's notification says it ended: a status (completed, failed, killed, stopped), or a monitor's
    expiry -- not an agent waiting on its own background work."""
    event = TASK_EVENT.search(note)
    return not WAITING.search(note) and bool(TASK_STATUS.search(note) or (event and MONITOR_END.match(event.group(1))))


def _end(tasks: Dict[str, dict], task_id: str) -> None:
    if task_id in tasks:
        tasks[task_id]["open"] = False


_ENDS: Dict[str, tuple] = {}     # Claude Code's record -> (its `_stat` when read, what `_ends` found in it)
_ENDS_LOCK = threading.Lock()


def _ends(path: str):
    """(the record's `_stat` before it was read, {task id: when Claude Code wrote its latest end}): the background
    tasks Claude Code's record of a session (CLAUDE_TAIL's end of it) says ended -- a notification `_ending` them,
    written the moment it is made, whether or not a call has carried it yet. Read again only once it changed."""
    seen = live._stat(path)
    with _ENDS_LOCK:
        kept = _ENDS.get(path)
        if kept and kept[0] == seen:
            return kept
    ends: Dict[str, float] = {}
    try:
        with open(path, "rb") as fh:
            fh.seek(max(0, os.path.getsize(path) - CLAUDE_TAIL))
            lines = fh.read().split(b"\n")
    except OSError:
        return seen, ends
    for line in lines:
        if b"<task-notification>" not in line:
            continue
        try:
            m = json.loads(line)
        except ValueError:
            continue
        at = _seconds(m.get("timestamp")) if isinstance(m, dict) else None
        if at is None:                                   # when, unknown: perhaps before an agent was resumed
            continue
        for text in _strings(m):
            for note in NOTIFICATION.finditer(text):
                found = TASK_ID.search(note.group(1))
                if found and _ending(note.group(1)):
                    ends[found.group(1)] = max(at, ends.get(found.group(1), 0))
    with _ENDS_LOCK:
        _ENDS[path] = (seen, ends)
    return seen, ends


def _strings(value):
    """Every string in a JSON value, at any depth."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def _task_label(conn, channel: str, row_id: int, payload_json: Optional[str]) -> Optional[str]:
    """What the tool call that started a task said it was for: its `description` (Bash, Agent, Monitor
    take one; SendMessage, its `summary`), else the start of its command or prompt. None when the call
    is not found."""
    try:
        blocks = (json.loads(payload_json) or {}).get("content") or []
        call_id = next(b.get("tool_use_id") for b in blocks if isinstance(b, dict) and b.get("tool_use_id"))
    except (ValueError, AttributeError, StopIteration):
        return None
    for (raw,) in conn.execute(f"SELECT e.payload_json FROM events e JOIN event_types t ON t.event_type_id = e.event_type_id "
                               f"WHERE ifnull(e.{CHANNEL}, '') = ? AND t.name = 'tool_call' AND e.row_id < ? AND e.row_id >= ? "
                               "ORDER BY e.row_id DESC", (channel, row_id, row_id - 400)):
        try:
            for b in (json.loads(raw) or {}).get("content") or []:
                if isinstance(b, dict) and b.get("id") == call_id and isinstance(b.get("input"), dict):
                    given = b["input"]
                    for k in ("description", "summary", "command", "prompt", "message"):
                        if isinstance(given.get(k), str) and given[k].strip():
                            return " ".join(given[k].split())[:160]
                    return b.get("name")
        except (ValueError, AttributeError):
            continue
    return None


def _written(path: Optional[str]) -> Optional[float]:
    """When a task's output was last written: its file's time, or a folder's (a workflow's transcripts) newest file's."""
    try:
        if not path:
            return None
        if not os.path.isdir(path):
            return os.stat(path).st_mtime
        with os.scandir(path) as found:
            return max((e.stat().st_mtime for e in found if e.is_file()), default=None)
    except OSError:
        return None


def _settle_background(a: dict, now: float) -> None:
    """The agent's background tasks that still run (module doc), each with `active`, its last sign of
    life; an IDLE agent with any is BACKGROUND, and running."""
    s = a.get("session") or {}
    tasks = a.get("background") or []
    if a.get("alive") is False or a.get("status") == CLOSED or (s.get("kept") and not s.get("pid")):
        tasks = []                                   # its process is gone (or seen ending: `ended`), and they with it
    since = s.get("since") if s.get("pid") else a.get("since")     # when the process that has it now started
    known = bool(s.get("pid")) or a.get("alive") is True
    out = []
    for t in tasks:
        if since and t["started"] and t["started"] < since:
            continue                                 # an earlier process's
        wrote = _written(t.get("output"))
        active = max((x for x in (t["started"], t.get("event_at"), wrote) if x), default=None)
        if not known and (active is None or now - active > STALE_SECONDS):
            continue
        out.append({**t, "active": active})
    record = queued.record(a["channel"], a.get("cwd") or s.get("cwd")) \
        if out and a.get("channel") and a.get("harness") in ("claude", None) else None
    if record:                                       # ended since it started, as Claude Code's record says (`_ends`)
        seen, ends = _ends(record)
        out = [t for t in out if ends.get(t["id"], 0) <= (t["started"] or 0)]
        if out and a.get("status") == IDLE:
            a.setdefault("record", (record, seen))   # watched (live.py) while it is BACKGROUND
    a["background"] = out
    if out and a.get("status") == IDLE:
        a["status"], a["running"] = BACKGROUND, True


CODEX_TYPES = codex_rules.SHAPES
harness_of = harness_kit.harness_of


def _harness(conn, channel: str) -> Optional[str]:
    rows = conn.execute(f"SELECT payload_json FROM events WHERE ifnull({CHANNEL}, '') = ? ORDER BY row_id LIMIT 60", (channel,))
    payloads = []
    for (raw,) in rows:
        try:
            payloads.append(json.loads(raw))
        except ValueError:
            continue
    return harness_of(payloads)


_USAGE: Dict[tuple, dict] = {}      # (database, channel) -> (its last read, its usage): reads only add up


def _usage(conn, channel: str, tables: set) -> dict:
    """Every item every read of the channel sent, added up by kind and name -- each message
    counted once per call it went in -- with the harness's preamble of each call (PREAMBLE):
    {tokens, entries: [{group, name, items, tokens}], not_counted}, the groups as read() names
    them (an event before its read's cut is KEPT, after it RECENT); `not_counted` is what the
    provider counted beyond them, over the calls it counted. Kept until the channel's next read:
    a long agent's sum is a scan of every read."""
    path = next((r[2] for r in conn.execute("PRAGMA database_list") if r[1] == "main"), "")
    last = conn.execute(f"SELECT max(read_id) FROM _reads WHERE ifnull({CHANNEL}, '') = ?", (channel,)).fetchone()[0]
    kept = _USAGE.get((path, channel))
    if kept and kept[0] == last:
        return dict(kept[1])
    cut = ("LEFT JOIN _builds b ON b.build_id = CAST(r.basis AS INTEGER) " if "_builds" in tables else "")
    since = "b.open_from_row IS NULL OR i.row_id >= b.open_from_row" if cut else "1"
    rows = conn.execute(
        f"SELECT CASE WHEN i.row_id IS NULL THEN 'made' WHEN {since} THEN 'recent' ELSE 'kept' END AS kind, "
        "coalesce(t.name, m.name, '?') AS item, count(*) AS n, sum(coalesce(e.tokens, m.tokens, 0)) AS tok "
        f"FROM _read_items i JOIN _reads r ON r.read_id = i.read_id AND ifnull(r.{CHANNEL}, '') = ? {cut}"
        "LEFT JOIN events e ON e.row_id = i.row_id LEFT JOIN event_types t ON t.event_type_id = e.event_type_id "
        "LEFT JOIN _made_items m ON m.made_id = i.made_id GROUP BY 1, 2", (channel,)).fetchall()
    entries = [{"group": RECENT if r["kind"] == "recent" else KEPT if r["kind"] == "kept"
                else AG_KINDS.get(r["item"], "ag's sections"), "name": r["item"], "items": r["n"], "tokens": r["tok"] or 0}
               for r in rows]
    cols = _columns(conn, "_reads")
    pre = "preamble_json" if "preamble_json" in cols else "NULL"
    real = "real_tokens" if "real_tokens" in cols else "NULL"
    per_read = conn.execute(f"SELECT read_id, {pre}, {real} FROM _reads WHERE ifnull({CHANNEL}, '') = ?", (channel,)).fetchall()
    ids = {r[0]: _preamble_ids(r[1]) for r in per_read}
    known = _preambles(conn, [i for v in ids.values() for i in v])
    by_name: Dict[str, dict] = {}
    for v in ids.values():
        for i in v:
            if i in known:
                e = by_name.setdefault(known[i]["name"], {"group": PREAMBLE, "name": known[i]["name"], "items": 0, "tokens": 0})
                e["items"] += 1
                e["tokens"] += known[i]["tokens"]
    entries += list(by_name.values())
    sent = dict(conn.execute(
        "SELECT i.read_id, coalesce(sum(e.tokens), 0) + coalesce(sum(m.tokens), 0) FROM _read_items i "
        f"JOIN _reads r ON r.read_id = i.read_id AND ifnull(r.{CHANNEL}, '') = ? LEFT JOIN events e ON e.row_id = i.row_id "
        "LEFT JOIN _made_items m ON m.made_id = i.made_id GROUP BY i.read_id", (channel,)))
    not_counted = sum(max(0, r[2] - sent.get(r[0], 0) - sum(known[i]["tokens"] for i in ids[r[0]] if i in known))
                      for r in per_read if r[2])
    usage = {"tokens": sum(e["tokens"] for e in entries), "entries": entries, "not_counted": not_counted}
    _USAGE[(path, channel)] = (last, usage)
    return dict(usage)


def _sent(conn, read_id: int) -> int:
    """ag's count of all read `read_id` sent: what it returned, added up."""
    return conn.execute("SELECT coalesce(sum(e.tokens), 0) + coalesce(sum(m.tokens), 0) FROM _read_items i "
                        "LEFT JOIN events e ON e.row_id = i.row_id LEFT JOIN _made_items m ON m.made_id = i.made_id "
                        "WHERE i.read_id = ?", (read_id,)).fetchone()[0]


# ---------------------------------------------------------------- one agent over time

def agent(gatherer: str, channel: str, llm: Optional[List[dict]] = None) -> dict:
    """One agent over time, as the module says. `llm` is the Gatherer's model calls
    (`llm_calls()`), when the caller has them already."""
    conn = _connect(gatherer)
    if conn is None:
        return {"error": f"no database for gatherer {gatherer!r}"}
    try:
        if not _channels_kept(conn):
            return dict(NOTHING_YET)
        return _agent(conn, gatherer, channel, llm if llm is not None else llm_calls())
    finally:
        conn.close()


def _agent(conn, gatherer: str, channel: str, llm: List[dict]) -> dict:
    tables, read_cols = _tables(conn), _columns(conn, "_reads")
    sizes = [c for c in ("est_tokens", "real_tokens", "limit_tokens") if c in read_cols]
    recorded = "sent_tokens" if "sent_tokens" in read_cols else "NULL"
    reads = []
    for r in conn.execute(f"SELECT read_id, read_at, row_id, basis{''.join(', ' + c for c in sizes)}, "
                          f"{recorded} AS recorded FROM _reads WHERE ifnull({CHANNEL}, '') = ? ORDER BY read_id", (channel,)):
        reads.append({"read_id": r["read_id"], "at": _seconds(r["read_at"]), "row_id": r["row_id"],
                      "basis": r["basis"], "recorded_tokens": r["recorded"],
                      **{k: (r[k] if k in sizes else None) for k in ("est_tokens", "real_tokens", "limit_tokens")}})
    tasks = []
    if "tasks" in tables:
        times = dict(conn.execute(f"SELECT row_id, inserted_at FROM events WHERE ifnull({CHANNEL}, '') = ?", (channel,)))
        for r in conn.execute("SELECT task_index, name, description, first_row, last_row, tokens FROM tasks "
                              "WHERE channel_key = ? ORDER BY task_index", (channel,)):
            tasks.append({"index": r["task_index"], "name": r["name"], "description": r["description"],
                          "first_row": r["first_row"], "last_row": r["last_row"], "tokens": r["tokens"],
                          "started": _seconds(times.get(r["first_row"])), "ended": _seconds(times.get(r["last_row"]))})
    sent = dict(conn.execute(                # ag's count of all it sent: what each read returned, added up
        "SELECT i.read_id, coalesce(sum(e.tokens), 0) + coalesce(sum(m.tokens), 0) FROM _read_items i "
        f"JOIN _reads r ON r.read_id = i.read_id AND ifnull(r.{CHANNEL}, '') = ? "
        "LEFT JOIN events e ON e.row_id = i.row_id LEFT JOIN _made_items m ON m.made_id = i.made_id "
        "GROUP BY i.read_id", (channel,)))
    pre = dict(conn.execute(f"SELECT read_id, preamble_json FROM _reads WHERE ifnull({CHANNEL}, '') = ?", (channel,))) \
        if "preamble_json" in read_cols else {}
    known = _preambles(conn, [i for raw in pre.values() for i in _preamble_ids(raw)])
    for r in reads:
        r["sent_tokens"] = sent.get(r["read_id"])
        ids = _preamble_ids(pre.get(r["read_id"]))
        # the harness's preamble the call stated (None: none recorded -- a call from before ag kept it)
        r["preamble_tokens"] = sum(known[i]["tokens"] for i in ids if i in known) if ids else None
    starts = sorted(t["started"] for t in tasks if t["started"] is not None)
    for i, r in enumerate(reads):          # the tasks begun by then (a read may answer an older event)
        r["tasks"] = sum(1 for s in starts if r["at"] is not None and s <= r["at"])
        r["rebuild"] = i > 0 and r["basis"] != reads[i - 1]["basis"]
    builds = []
    if "_builds" in tables:
        cols = _columns(conn, "_builds")
        for r in conn.execute(f"SELECT build_id, status, started_at, finished_at, through_row, error"
                              f"{', reason' if 'reason' in cols else ''} FROM _builds WHERE channel_key = ? "
                              f"ORDER BY build_id", (channel,)):
            builds.append({"build_id": r["build_id"], "status": r["status"], "started": _seconds(r["started_at"]),
                           "finished": _seconds(r["finished_at"]), "through_row": r["through_row"],
                           "error": r["error"], "reason": r["reason"] if "reason" in cols else None})
    checks = []
    if "_boundaries" in tables:
        for r in conn.execute("SELECT row_id, asked_at, decided_at, new_task, why FROM _boundaries "
                              "WHERE channel_key = ? ORDER BY row_id", (channel,)):
            checks.append({"row_id": r["row_id"], "asked": _seconds(r["asked_at"]), "decided": _seconds(r["decided_at"]),
                           "new_task": bool(r["new_task"]) if r["new_task"] is not None else None, "why": r["why"]})
    mine = [c for c in llm if _belongs(c, gatherer, channel, builds, checks)]
    usage = _usage(conn, channel, tables)
    usage.update(calls=len(reads), real_tokens=sum(r["real_tokens"] or 0 for r in reads),
                 real_calls=sum(1 for r in reads if r["real_tokens"]))
    harness = _harness(conn, channel)
    return {"gatherer": gatherer, "channel": channel, "harness": harness, "reads": reads,
            "pending": _pending(conn, channel, tables),
            "typed": queued.typed(channel) if harness in ("claude", None) else [],
            "after_read": _after_read(conn, channel, tables, reads[-1]["row_id"] if reads else None),
            "tasks": tasks, "builds": builds,
            "checks": checks, "rebuilds": sum(1 for r in reads if r["rebuild"]), "llm": _llm_summary(mine), "usage": usage,
            "llm_attributed_by_time": sum(1 for c in mine if not c.get("job"))}


#: What the model answered that no call has carried back yet (the store's `_pending`): the latest context's tail.
PENDING = "Pending"
#: An event stored after the one the latest read responded to: in no read's context yet.
AFTER_READ = "Stored since the latest call"
_tokenizer = None


def _count(text: str) -> int:
    """ag's own count of a pending event's text (pending rows keep none): tiktoken's o200k_base, as
    the store's default; characters / 4 without tiktoken."""
    global _tokenizer
    if not text:
        return 0
    if _tokenizer is None:
        try:
            import tiktoken
            _tokenizer = tiktoken.get_encoding("o200k_base")
        except Exception:  # noqa: BLE001 - no tiktoken, or no encoding file
            _tokenizer = False
    if _tokenizer:
        try:
            return len(_tokenizer.encode(text, disallowed_special=()))
        except Exception:  # noqa: BLE001
            pass
    return max(1, len(text) // 4)


def _pending(conn, channel: str, tables: set) -> List[dict]:
    """The channel's pending events, oldest first, as `context` lists items (group PENDING): each one's
    type, size by ag's own count, time and text (at most TEXT_CHARS; `clipped` says how much more).
    [] in a file from before `_pending`, or when the channel has none: its last call carried them all."""
    if "_pending" not in tables or CHANNEL not in _columns(conn, "_pending"):
        return []
    items = []
    for r in conn.execute(f"SELECT pending_id, received_at, type, payload_json, text FROM _pending "
                          f"WHERE ifnull({CHANNEL}, '') = ? ORDER BY pending_id", (channel,)):
        text = r["text"] if r["text"] else readable(r["payload_json"])
        items.append({"position": None, "group": PENDING, "name": r["type"], "tokens": _count(r["text"] or ""),
                      "row_id": None, "made_id": None, "at": _seconds(r["received_at"]),
                      "clipped": max(0, len(text or "") - TEXT_CHARS), "text": (text or "")[:TEXT_CHARS]})
    return items


def _after_read(conn, channel: str, tables: set, row_id: Optional[int]) -> List[dict]:
    """What the channel has that its latest read's context does not, oldest first: the events stored
    after the one that read responded to (`row_id`) -- by a call that logged no read, such as a
    harness's read-only side call, which stores the turn's final answer and clears it from pending --
    merged by time (`inserted_at`, `received_at`) with the pending events. Just the pending ones
    before any read (`row_id` None)."""
    items = []
    if row_id is not None:
        for r in conn.execute(
                "SELECT e.row_id, t.name AS type, e.tokens, e.text, e.payload_json, e.inserted_at FROM events e "
                f"LEFT JOIN event_types t ON t.event_type_id = e.event_type_id WHERE ifnull(e.{CHANNEL}, '') = ? AND e.row_id > ? "
                "ORDER BY e.row_id LIMIT ?", (channel, row_id, HISTORY_ITEMS)):
            text = r["text"] if r["text"] else readable(r["payload_json"])
            items.append({"position": None, "group": AFTER_READ, "name": r["type"] or "?", "tokens": r["tokens"] or 0,
                          "row_id": r["row_id"], "made_id": None, "at": _seconds(r["inserted_at"]),
                          "clipped": max(0, len(text or "") - TEXT_CHARS), "text": (text or "")[:TEXT_CHARS]})
    stored = len(items)
    items += _pending(conn, channel, tables)
    order = sorted(range(len(items)), key=lambda i: (items[i]["at"] or 0, i >= stored, i))   # a tie: stored first
    return [items[i] for i in order]


# ---------------------------------------------------------------- what a read held

#: The agent's own events, verbatim: since the cut of the build the read was made from (all of
#: them before any build), and those kept from before it (its preamble, the pinned rows).
RECENT, KEPT = "Recent history", "Kept from before the cut"
#: What the harness sent besides its messages (its system prompt, its tools), as it stated them.
PREAMBLE = "Harness preamble"


def _preamble_ids(raw) -> List[int]:
    try:
        ids = json.loads(raw) if raw else []
    except ValueError:
        return []
    return [i for i in ids if isinstance(i, int)] if isinstance(ids, list) else []


def _preambles(conn, ids) -> Dict[int, dict]:
    """The _preambles with these ids: {id: {name, text, tokens}}; {} in a file from before them."""
    ids = sorted(set(ids))
    if not ids or "_preambles" not in _tables(conn):
        return {}
    rows = conn.execute(f"SELECT preamble_id, name, text, tokens FROM _preambles WHERE preamble_id IN ({', '.join('?' * len(ids))})", ids)
    return {r[0]: {"name": r[1], "text": r[2], "tokens": r[3] or 0} for r in rows}
#: ag's own messages by name, as the read's breakdown groups them; any other name is a section of its own.
AG_KINDS = {"environment_update": "File-change notices", "parallel_request": "Other agents' requests",
            "context_stream": "Stream messages", "gatherer_guide": "Gatherer guide"}


def readable(payload_json: Optional[str]) -> str:
    """The words in an event's payload, for one ag stores no text for (reasoning, an empty
    message): the text and thinking of its content blocks (pi's, Claude Code's), a codex
    item's summary or content; the payload itself when there are none; "" for none at all."""
    try:
        p = json.loads(payload_json) if payload_json else None
    except ValueError:
        return payload_json or ""
    if not isinstance(p, dict):
        return payload_json or ""
    words = []
    for key in ("content", "summary", "parts"):
        for block in p.get(key) or [] if isinstance(p.get(key), list) else []:
            if isinstance(block, dict):
                words += [block[k] for k in ("text", "thinking") if isinstance(block.get(k), str) and block[k].strip()]
    if words:
        return "\n\n".join(words)
    has_blocks = any(isinstance(p.get(k), list) for k in ("content", "summary", "parts"))
    return "" if has_blocks else payload_json


def _items(conn, read_id: int):
    """(the read's row, the cut of its build or None, its items in order): each item's place,
    group (RECENT / KEPT for the agent's own events, AG_KINDS or "ag's sections" for ag's),
    name (the event type, or the made item's name), size (the manager's own count), the event
    row or made item it is, and its text (an event's readable text, else its payload; a made
    item's text)."""
    meta = conn.execute("SELECT * FROM _reads WHERE read_id = ?", (read_id,)).fetchone()
    cut = None                           # where the build the read was made from cut the history
    if meta is not None and meta["basis"] and str(meta["basis"]).isdigit() and "_builds" in _tables(conn):
        found = conn.execute("SELECT open_from_row FROM _builds WHERE build_id = ?", (int(meta["basis"]),)).fetchone()
        cut = found[0] if found else None
    rows = conn.execute(
        "SELECT i.position, i.row_id, i.made_id, t.name AS type, e.tokens AS etok, e.text AS etext, "
        "e.payload_json AS payload, e.inserted_at AS at, m.name AS made, m.tokens AS mtok, m.item_json AS item "
        "FROM _read_items i LEFT JOIN events e ON e.row_id = i.row_id "
        "LEFT JOIN event_types t ON t.event_type_id = e.event_type_id "
        "LEFT JOIN _made_items m ON m.made_id = i.made_id WHERE i.read_id = ? ORDER BY i.position",
        (read_id,)).fetchall()
    items = []
    for r in rows:
        if r["row_id"] is not None:              # the agent's own, verbatim
            group = RECENT if cut is None or r["row_id"] >= cut else KEPT
            name, tokens, text = r["type"] or "?", r["etok"] or 0, r["etext"] if r["etext"] else readable(r["payload"])
        else:
            name, tokens = r["made"] or "?", r["mtok"] or 0
            group = AG_KINDS.get(name, "ag's sections")
            try:
                made = json.loads(r["item"]) if r["item"] else {}
            except ValueError:
                made = {}
            text = made.get("text") if isinstance(made, dict) and isinstance(made.get("text"), str) else r["item"]
        items.append({"position": r["position"], "group": group, "name": name, "tokens": tokens,
                      "row_id": r["row_id"], "made_id": r["made_id"], "at": _seconds(r["at"]), "text": text or ""})
    return meta, cut, items


def read(gatherer: str, read_id: int) -> dict:
    """What read `read_id` put in the context: each item's kind and size (the manager's own
    count; all of them add up to its `sent_tokens`), grouped as the agent's own events,
    verbatim, by event type -- RECENT (since the cut of the read's build) and KEPT (before
    it) -- and ag's own messages, by name."""
    conn = _connect(gatherer)
    if conn is None:
        return {"error": f"no database for gatherer {gatherer!r}"}
    try:
        meta, cut, items = _items(conn, read_id)
        groups: Dict[str, dict] = {}
        for it in items:
            g = groups.setdefault(it["group"], {"group": it["group"], "tokens": 0, "items": 0, "by_name": {}})
            g["tokens"] += it["tokens"]
            g["items"] += 1
            n = g["by_name"].setdefault(it["name"], {"name": it["name"], "tokens": 0, "items": 0})
            n["tokens"] += it["tokens"]
            n["items"] += 1
        return {"read_id": read_id, "cut": cut, "at": _seconds(meta["read_at"]) if meta else None,
                "real_tokens": meta["real_tokens"] if meta is not None and "real_tokens" in meta.keys() else None,
                "groups": [dict(g, by_name=sorted(g["by_name"].values(), key=lambda n: -n["tokens"]))
                           for g in sorted(groups.values(), key=lambda g: -g["tokens"])]}
    finally:
        conn.close()


TEXT_CHARS = 20000          # the most of one item's text `context` returns; the rest is counted, not sent


HISTORY_ITEMS = 3000        # the most events `history` returns at once


def history(gatherer: str, channel: str, first_row: int, last_row: Optional[int] = None) -> dict:
    """The channel's own events from row `first_row` to `last_row` (None: to its newest), in
    order, as `context` lists items: each one's type, size, time and text (at most
    TEXT_CHARS; `clipped` says how much more), at most HISTORY_ITEMS of them (`more` counts
    the rest) -- a task's messages, or those since the last task. To its newest, they end with
    the channel's pending events (`_pending`): what the model answered that no call has stored yet."""
    conn = _connect(gatherer)
    if conn is None:
        return {"error": f"no database for gatherer {gatherer!r}"}
    try:
        if not _channels_kept(conn):
            return dict(NOTHING_YET)
        top = last_row if last_row is not None else 2 ** 62
        where = f"ifnull(e.{CHANNEL}, '') = ? AND e.row_id >= ? AND e.row_id <= ?"
        n = conn.execute(f"SELECT count(*) FROM events e WHERE {where}", (channel, first_row, top)).fetchone()[0]
        items = []
        for r in conn.execute(
                "SELECT e.row_id, t.name AS type, e.tokens, e.text, e.payload_json, e.inserted_at FROM events e "
                f"LEFT JOIN event_types t ON t.event_type_id = e.event_type_id WHERE {where} ORDER BY e.row_id LIMIT ?",
                (channel, first_row, top, HISTORY_ITEMS)):
            text = r["text"] if r["text"] else readable(r["payload_json"])
            items.append({"row_id": r["row_id"], "name": r["type"] or "?", "tokens": r["tokens"] or 0,
                          "at": _seconds(r["inserted_at"]), "clipped": max(0, len(text or "") - TEXT_CHARS),
                          "text": (text or "")[:TEXT_CHARS]})
        if last_row is None:               # to its newest: what the model answered since, no call has carried yet
            items += _pending(conn, channel, _tables(conn))
        return {"first_row": first_row, "last_row": last_row, "items": items, "more": max(0, n - len(items))}
    finally:
        conn.close()


# ---------------------------------------------------------------- the transcript: the conversation as parts

TRANSCRIPT_ITEMS = 400      # the most events `transcript` returns at once
#: Which role an event's text has, by its type: what the transcript shows it as.
ROLES = {"user_message": "user", "agent_message": "assistant", "agent_reasoning": "thinking",
         "tool_call": "assistant", "tool_output": "user"}


def _clip(value, chars: int = TEXT_CHARS):
    """`value` with every string in it at most `chars` long: a tool's input, as the page shows it."""
    if isinstance(value, str):
        return value if len(value) <= chars else value[:chars] + f"\n… ({len(value) - chars:,} more characters)"
    if isinstance(value, list):
        return [_clip(v, chars) for v in value]
    if isinstance(value, dict):
        return {k: _clip(v, chars) for k, v in value.items()}
    return value


def parts(event_type: str, payload_json: Optional[str], text: Optional[str],
          chars: Optional[int] = TEXT_CHARS) -> List[dict]:
    """An event as the transcript shows it, whatever harness wrote it: its parts, each one of
        {"kind": "text", "role": user/assistant/system, "text"}
        {"kind": "thinking", "text"}                ("" when it is encrypted)
        {"kind": "call", "id", "name", "input"}     a tool call (input: its object, or a string); a codex
                                                    code-mode script also has `calls`: [{name, input}], the
                                                    calls it makes (input None: not written out)
        {"kind": "result", "id", "error", "text"}   a tool's result, `id` its call's
        {"kind": "note", "name", "text"}            anything else: the harness's or ag's own messages (codex's
                                                    message from another agent, "agent_message", among them)
    The harness's own format is read by its rules (harness_kit: Claude Code's content blocks, codex's Responses
    items), and drawn here; a format they do not know (pi's, opencode's) is drawn from its content blocks, and
    anything else shows as its readable text. Each text and input is clipped at `chars` (None: kept whole)."""
    try:
        p = json.loads(payload_json) if payload_json else None
    except ValueError:
        p = None
    role = ROLES.get(event_type)
    if role is None:                         # not the conversation: a system message, ag's notices
        return [{"kind": "note", "name": event_type, "text": text or readable(payload_json)}]
    out: Optional[List[dict]] = None
    h = harness_kit.owner(p)
    if h is not None and h.name == "codex" and isinstance(p, dict) and p.get("type") is not None:
        out = _codex_view(h.read_one(p), chars)
    elif h is not None and h.name == "claude" and isinstance(p.get("content"), list):
        speaker = "system" if p.get("role") in ("system", "developer") else role
        out = [v for x in h.read_one(p) for v in _claude_view(x, speaker)]
    if out is None and isinstance(p, dict) and isinstance(p.get("content"), list):
        out = _blocks_view(p["content"], "system" if p.get("role") in ("system", "developer") else role)
    out = out or []
    if not out:                              # a format this does not read: its words, as its type says
        words = text or readable(payload_json)
        if event_type == "agent_reasoning":
            out.append({"kind": "thinking", "text": words if words != payload_json else ""})
        elif words:
            out.append({"kind": "text", "role": role, "text": words})
    for part in out if chars is not None else []:
        for k in ("text", "input"):
            if k in part:
                part[k] = _clip(part[k], chars)
    return out


def _claude_view(x: "harness_kit.Part", speaker: str) -> List[dict]:
    """A piece of Claude Code's, read (harness_kit.claude), as the transcript draws it."""
    block = x.detail.get("block")
    if block == "text":
        return [{"kind": "text", "role": speaker, "text": x.text}] if (x.text or "").strip() else []
    if x.kind == Kind.REASONING:
        return [{"kind": "thinking", "text": x.detail.get("thinking") or ""}]
    if x.tool is not None:
        return [{"kind": "call", "id": x.tool.id, "name": x.tool.name, "input": x.tool.input}]
    if x.result is not None:
        return [{"kind": "result", "id": x.result.call_id, "error": x.result.error, "text": x.result.output}]
    if block == "image":
        return [{"kind": "note", "name": "image", "text": "[image]"}]
    return []


def _codex_view(read: List["harness_kit.Part"], chars: Optional[int]) -> Optional[List[dict]]:
    """A codex item, read (harness_kit.codex), as the transcript draws it: its call, its result, its reasoning's summary,
    or another agent's message to it; [] for a message (its words, by its type) -- None for an item drawn from its
    content blocks instead."""
    out: List[dict] = []
    for x in read:
        t = x.detail.get("block")
        if t == "agent_message" and x.detail.get("between"):  # codex's: another agent's message to this one
            out.append({"kind": "note", "name": "agent_message", "text": x.text or ""})
        elif t not in CODEX_TYPES | {"tool_search_call", "tool_search_output"}:
            return None
        elif x.tool is not None:
            call = {"kind": "call", "id": x.tool.id, "name": x.tool.name, "input": x.tool.input}
            if call["name"] == CODE_MODE and isinstance(call["input"], str) and script_calls(call["input"]):
                call["calls"] = [{"name": n, "input": _clip(a, chars) if chars else a} for n, a in script_calls(call["input"])]
            out.append(call)
        elif x.result is not None:
            out.append({"kind": "result", "id": x.result.call_id, "error": False, "text": x.result.output})
        elif x.kind == Kind.REASONING:
            out.append({"kind": "thinking", "text": x.detail.get("thinking") or ""})
    return out


def _blocks_view(content: list, speaker: str) -> List[dict]:
    """Content blocks of a format no harness's rules read (pi's; an item codex sends untyped), as the transcript draws
    them: their words and thinking, any calls and results among them, an image as a note."""
    out = []
    for b in content:
        if not isinstance(b, dict):
            continue
        t = b.get("type")
        if t in ("text", "input_text", "output_text"):
            if (b.get("text") or "").strip():
                out.append({"kind": "text", "role": speaker, "text": b["text"]})
        elif t in ("thinking", "redacted_thinking", "reasoning_text"):
            out.append({"kind": "thinking", "text": b.get("thinking") or b.get("text") or ""})
        elif t in ("tool_use", "server_tool_use"):
            out.append({"kind": "call", "id": b.get("id"), "name": b.get("name") or "tool", "input": b.get("input")})
        elif t in ("tool_result", "web_search_tool_result"):
            out.append({"kind": "result", "id": b.get("tool_use_id"), "error": bool(b.get("is_error")),
                        "text": _output(b.get("content"))})
        elif t in ("image", "input_image"):
            out.append({"kind": "note", "name": "image", "text": "[image]"})
    return out


def transcript(gatherer: str, channel: str, after: Optional[int] = None, before: Optional[int] = None) -> dict:
    """The channel's conversation as the transcript shows it: each event's row, type, time and
    `parts` (`parts`), oldest first, at most TRANSCRIPT_ITEMS of them -- those after row `after`,
    else the newest before row `before` (None: the newest of all). `earlier` says whether the
    channel has events before the first; reaching its newest, the items end with its pending
    events (row None): what the model answered that no call has stored yet."""
    conn = _connect(gatherer)
    if conn is None:
        return {"error": f"no database for gatherer {gatherer!r}"}
    try:
        if not _channels_kept(conn):
            return dict(NOTHING_YET)
        cols = ("SELECT e.row_id, t.name AS type, e.text, e.payload_json, e.inserted_at FROM events e "
                f"LEFT JOIN event_types t ON t.event_type_id = e.event_type_id WHERE ifnull(e.{CHANNEL}, '') = ? ")
        if after is not None:
            rows = conn.execute(cols + "AND e.row_id > ? ORDER BY e.row_id LIMIT ?",
                                (channel, after, TRANSCRIPT_ITEMS + 1)).fetchall()
            newest = len(rows) <= TRANSCRIPT_ITEMS
            rows = rows[:TRANSCRIPT_ITEMS]
        else:
            rows = conn.execute(cols + "AND e.row_id < ? ORDER BY e.row_id DESC LIMIT ?",
                                (channel, before if before is not None else 2 ** 62, TRANSCRIPT_ITEMS)).fetchall()[::-1]
            newest = before is None
        items = [{"row_id": r["row_id"], "type": r["type"] or "?", "at": _seconds(r["inserted_at"]),
                  "parts": parts(r["type"] or "?", r["payload_json"], r["text"])} for r in rows]
        earlier = False
        if items:
            earlier = conn.execute(f"SELECT 1 FROM events WHERE ifnull({CHANNEL}, '') = ? AND row_id < ? LIMIT 1",
                                   (channel, items[0]["row_id"])).fetchone() is not None
        elif after is not None:
            earlier = True
        tables = _tables(conn)
        if newest and "_pending" in tables and CHANNEL in _columns(conn, "_pending"):
            for r in conn.execute(f"SELECT received_at, type, payload_json, text FROM _pending WHERE {CHANNEL} = ? "
                                  "ORDER BY pending_id", (channel,)):
                items.append({"row_id": None, "type": r["type"], "at": _seconds(r["received_at"]),
                              "parts": parts(r["type"], r["payload_json"], r["text"])})
        return {"items": items, "earlier": earlier, "newest": newest}
    finally:
        conn.close()


def context(gatherer: str, read_id: int) -> dict:
    """Every item read `read_id` put in the context, in the order the model got them: its
    group, name, size and text (at most TEXT_CHARS of it; `clipped` says how much more)."""
    conn = _connect(gatherer)
    if conn is None:
        return {"error": f"no database for gatherer {gatherer!r}"}
    try:
        meta, cut, items = _items(conn, read_id)
        ids = _preamble_ids(meta["preamble_json"]) if meta is not None and "preamble_json" in meta.keys() else []
        known = _preambles(conn, ids)
        preamble = [{"position": None, "group": PREAMBLE, "name": known[i]["name"], "tokens": known[i]["tokens"],
                     "row_id": None, "made_id": None, "at": None, "text": known[i]["text"]} for i in ids if i in known]
        for it in preamble + items:
            it["clipped"] = max(0, len(it["text"]) - TEXT_CHARS)
            it["text"] = it["text"][:TEXT_CHARS]
        real = meta["real_tokens"] if meta is not None and "real_tokens" in meta.keys() else None
        counted = sum(it["tokens"] for it in preamble + items)
        return {"read_id": read_id, "cut": cut, "at": _seconds(meta["read_at"]) if meta else None,
                "basis": meta["basis"] if meta is not None else None, "real_tokens": real,
                "tokens": sum(it["tokens"] for it in items), "preamble": preamble,
                "not_counted": max(0, real - counted) if real else None, "items": items}
    finally:
        conn.close()


# ---------------------------------------------------------------- the Gatherer's own model calls

def llm_calls() -> List[dict]:
    """The Gatherer's model calls, as its call log keeps them (<home>/logs/llm): each one's
    purpose, model, start, seconds, tokens in and out, error, and the job it ran for when
    the worker named it (`job`: gatherer, job, id, properties)."""
    out = []
    for path in sorted(glob.glob(os.path.join(paths.llm_log_dir(), "*.json"))):
        try:
            with open(path, encoding="utf-8") as fh:
                rec = json.load(fh)
        except (OSError, ValueError):
            continue
        usage = rec.get("usage") or {}
        tin = usage.get("prompt_tokens", usage.get("input_tokens"))
        tout = usage.get("completion_tokens", usage.get("output_tokens"))
        out.append({"purpose": rec.get("purpose"), "model": rec.get("model"), "started": _seconds(rec.get("started")),
                    "seconds": rec.get("seconds"), "tokens_in": tin if isinstance(tin, int) else 0,
                    "tokens_out": tout if isinstance(tout, int) else 0, "error": rec.get("error"),
                    "job": rec.get("job") if isinstance(rec.get("job"), dict) else None})
    return out


def _belongs(call: dict, gatherer: str, channel: str, builds: List[dict], checks: List[dict]) -> bool:
    """Whether a model call was made for this agent: as its job says, else (a log from before
    jobs were named) by time -- within one of its builds, or one of its new-task checks."""
    job = call.get("job")
    if job:
        return job.get("gatherer") == gatherer and (job.get("properties") or {}).get("channel") in (channel, None)
    t = call.get("started")
    if t is None:
        return False
    if call.get("purpose") == "boundary":
        return any(c["asked"] and c["asked"] - 1 <= t <= (c["decided"] or c["asked"]) + 1 for c in checks)
    return any(b["started"] and b["started"] - 1 <= t <= (b["finished"] or time.time()) + 1 for b in builds)


def _cost(model: Optional[str], tin: int, tout: int) -> Optional[float]:
    """The call's cost in USD by LiteLLM's price table, None when it has no price for the model."""
    if not model or "/" not in model or model.split("/", 1)[0] in ("codex", "claude-code"):
        return None
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")    # the price table it ships: no fetch
    os.environ.setdefault("LITELLM_LOG", "ERROR")
    try:
        import litellm
        a, b = litellm.cost_per_token(model=model, prompt_tokens=tin, completion_tokens=tout)
        return float(a) + float(b)
    except Exception:  # noqa: BLE001 - an unpriced model costs "unknown", not an error
        return None


def _llm_summary(calls: List[dict]) -> dict:
    by: Dict[str, dict] = {}
    for c in calls:
        p = by.setdefault(c["purpose"] or "?", {"purpose": c["purpose"] or "?", "calls": 0, "tokens_in": 0,
                                                "tokens_out": 0, "seconds": 0.0, "errors": 0, "cost": 0.0,
                                                "unpriced": 0, "models": set()})
        p["calls"] += 1
        p["tokens_in"] += c["tokens_in"]
        p["tokens_out"] += c["tokens_out"]
        p["seconds"] += c["seconds"] or 0
        p["errors"] += 1 if c["error"] else 0
        p["models"].add(c["model"] or "?")
        cost = _cost(c["model"], c["tokens_in"], c["tokens_out"])
        if cost is None:
            p["unpriced"] += 1
        else:
            p["cost"] += cost
    rows = [dict(p, models=sorted(p["models"]), seconds=round(p["seconds"], 1)) for p in by.values()]
    rows.sort(key=lambda p: -p["calls"])
    total = {k: sum(p[k] for p in rows) for k in ("calls", "tokens_in", "tokens_out", "errors", "cost", "unpriced")}
    return {"by_purpose": rows, "total": total,
            "calls": [{k: c[k] for k in ("purpose", "started", "seconds", "tokens_in", "tokens_out")} for c in calls]}


def snapshot() -> dict:
    """Everything, for a page that stands alone (`ag dashboard --out`): the home, every
    agent over time, and the last read's contents of each (by kind, and item by item); and the
    avatars the actors were given (avatars.py), each picture inside it."""
    pool = avatars.pictures()
    h = avatars.attach(home(), avatars.stored(), pool)
    llm = llm_calls()
    agents, reads, contexts = {}, {}, {}
    for g in h["gatherers"]:
        for a in g["agents"]:
            detail = agent(g["name"], a["channel"], llm)
            agents[f"{g['name']}\u0000{a['channel']}"] = detail
            if detail.get("reads"):
                rid = detail["reads"][-1]["read_id"]
                reads[f"{g['name']}\u0000{rid}"] = read(g["name"], rid)
                contexts[f"{g['name']}\u0000{rid}"] = context(g["name"], rid)
    pictures = {}
    for name in {a["avatar"] for g in h["gatherers"] for a in g["agents"] if a["avatar"]}:
        with open(avatars.path(name), encoding="utf-8") as fh:
            pictures[name] = fh.read()
    return {"home": h, "agents": agents, "reads": reads, "contexts": contexts, "avatars": pictures}
