"""What the dashboard shows, read from the context manager's home -- every gatherer's
database, opened read-only, and ag's own logs -- as plain JSON-ready dicts.

    home()                        every gatherer and its agents (channels), with their
                                  status; the hook servers ag started
    agent(gatherer, channel)      one agent over time: each read's size (ag's own count,
                                  the provider's, the harness's limit), its rebuilds, its
                                  tasks and how many had begun by each read, its builds,
                                  and the Gatherer's model calls made for it; and
                                  every token it was sent across its calls, by kind
    read(gatherer, read_id)       what one read put in the agent's context, by kind
    context(gatherer, read_id)    every item of it, in order, with its text
    history(gatherer, channel, a, b)  the agent's own events from row a to b: a task's messages
    transcript(gatherer, channel, ...)  its conversation, each event as harness-free parts

An agent is a channel of a gatherer: one harness session (codex's thread, Claude Code's
session, ...), some of them started from the page (sessions.py); which harness, its events' shape tells (`harness_of`). Its STATUS (`status_of`):
CLOSED when the harness's process that made its last call no longer runs; else IDLE when its turn
is over -- its last answer ended without a tool call -- and RUNNING when it is not (waiting on a
tool, or on the model). Where the process is not known (a call from before ag recorded it, not
Linux), a turn left unfinished for more than STALE_SECONDS counts as over. `running` is RUNNING,
or a build running for it. Its `last` is its latest activity: a read, an event, or a pending
answer (the reply that ends a turn, which no call stores until the user writes again) -- what
the page compares with when the reader last looked at it, to show it FINISHED. A REBUILD is a
read whose context comes from another build than the agent's read before it: the condensed
history was replaced.

Each read has these sizes: `sent_tokens`, ag's own count of everything it sent (what the
read returned, `_read_items`, added up -- what read() breaks down); `preamble_tokens`, its
count of what the harness sent besides (None: not recorded); `est_tokens`, the
policy's count of it against its budget (which leaves out the agent's preamble and the
sections' fixed overview); and `real_tokens`, the provider's count. A database written
before a column existed reads as None there. Nothing here writes anything.
"""

import glob
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import home as paths
from . import hiding, sessions

RUNNING_SECONDS = 120          # (no longer decides anything; kept for the page's older copies)
STALE_SECONDS = 1800           # an unfinished turn with no process to ask: over, after this long
RUNNING, IDLE, CLOSED = "running", "idle", "closed"
#: An answer's stop reason, as the provider gives it: the turn goes on (a tool to run, a paused
#: turn), or is over. Any other (Codex's `completed` on every answer, none) tells nothing: its
#: last event does.
GOES_ON = {"tool_use", "pause_turn"}
OVER = {"end_turn", "stop_sequence", "max_tokens", "refusal"}
CHANNEL = "p_channel"          # the channel property's column (ag.ag_policies.tools.channel)


def _connect(gatherer: str) -> Optional[sqlite3.Connection]:
    path = paths.db_path(gatherer)
    if not os.path.exists(path):
        return None
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=8)
    conn.row_factory = sqlite3.Row
    return conn


def _columns(conn, table: str) -> set:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


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
    the hook servers ag started, and which gatherers the reader hid or kept (`hiding`, hiding.py).
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
    _with_started(gatherers, sessions.stored() if started is None else started)
    for g in gatherers:                  # when it was made: its first event, else its config's time
        g["created"] = min((a["created"] for a in g["agents"] if a.get("created")), default=None) or _made(g["name"])
    gatherers.sort(key=lambda g: g.get("created") or 0, reverse=True)
    return {"home": paths.HOME, "now": now, "running_seconds": RUNNING_SECONDS, "gatherers": gatherers,
            "hook_servers": _hook_servers(), "hiding": hiding.stored()}


def _with_started(gatherers: List[dict], started: List[dict]) -> None:
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
                 "sent_tokens": None, "harness": s["harness"], "last_user_message": None,
                 "created": None, "last": _seconds(s["created_at"]), "building": False, "running": False,
                 "turn_over": True, "status": IDLE}
            g["agents"].append(a)
        a["session"] = s
        if a.get("holder") and a["holder"]["pid"] == s.get("pid"):
            a["holder"]["dashboard"] = True          # the dashboard's own agent, mid-turn
        a["created"] = min((x for x in (a["created"], _seconds(s["created_at"])) if x), default=None)
        if s["status"] in ("starting", "running") or s.get("queued"):   # its agent works, or a message waits for it
            a["status"], a["running"] = RUNNING, True
        g["last"] = max(g["last"] or 0, a["last"] or 0) or None
    for g in gatherers:                  # newest created first, as `_agents` has them
        for a in g["agents"]:
            a["chattable"] = chattable(a)
        g["agents"].sort(key=lambda a: a.get("created") or 0, reverse=True)


def chattable(a: dict) -> bool:
    """Whether the page may message the agent: a Claude Code session (the only harness the dashboard
    runs), with a directory to resume it in, that no other process has open (its `holder`, else the
    process its last call named) -- the dashboard's own agent aside."""
    if a.get("harness") not in ("claude", None) or not (a.get("cwd") or a.get("session")):
        return False
    held = a.get("holder")
    if held:
        return bool(held.get("dashboard"))
    return a.get("alive") is not True or bool(a.get("session") and a["session"].get("pid") == a.get("pid"))


def _agents(conn, now: float) -> List[dict]:
    if CHANNEL not in _columns(conn, "events"):
        return []
    sizes = [c for c in ("est_tokens", "real_tokens", "limit_tokens") if c in _columns(conn, "_reads")]
    out: Dict[str, dict] = {}
    for r in conn.execute(f"SELECT {CHANNEL} AS ch, count(*) AS n, min(inserted_at) AS first, max(inserted_at) AS last FROM events "
                          f"WHERE {CHANNEL} IS NOT NULL GROUP BY {CHANNEL}"):
        out[r["ch"]] = {"channel": r["ch"], "events": r["n"], "created": _seconds(r["first"]), "last_event": _seconds(r["last"]), "reads": 0,
                        "last_read": None, "cwd": None, "tasks": 0, "est_tokens": None, "real_tokens": None,
                        "limit_tokens": None, "sent_tokens": None, "pid": None, "alive": None}
    if CHANNEL in _columns(conn, "_reads"):
        for r in conn.execute(f"SELECT {CHANNEL} AS ch, count(*) AS n, max(read_at) AS last FROM _reads "
                              f"GROUP BY {CHANNEL}"):
            if r["ch"] in out:
                out[r["ch"]].update(reads=r["n"], last_read=_seconds(r["last"]))
        cols = _columns(conn, "_reads")
        cwd = "p_cwd" in cols
        process = [c for c in ("pid", "pid_started") if c in cols]
        for ch, a in out.items():
            last = conn.execute(f"SELECT {', '.join(['read_id'] + sizes + (['p_cwd'] if cwd else []))} FROM _reads "
                                f"WHERE {CHANNEL} = ? ORDER BY read_id DESC LIMIT 1", (ch,)).fetchone()
            if last is not None:
                a.update({k: last[k] for k in sizes}, cwd=last["p_cwd"] if cwd else None,
                         sent_tokens=_sent(conn, last["read_id"]))
            if len(process) == 2:                    # the newest call that named its process
                p = conn.execute(f"SELECT pid, pid_started FROM _reads WHERE {CHANNEL} = ? AND pid IS NOT NULL "
                                 f"ORDER BY read_id DESC LIMIT 1", (ch,)).fetchone()
                if p is not None:
                    a["pid"], a["alive"] = p["pid"], paths.process_alive(p["pid"], p["pid_started"])
    if "_open" in _tables(conn):                     # which process has each session open (ag's launcher, its calls)
        for ch, pid, started, by in conn.execute("SELECT session, pid, pid_started, opened_by FROM _open"):
            if ch in out and paths.process_alive(pid, started) is not False:
                out[ch]["holder"] = {"pid": pid, "by": by}
                out[ch]["pid"], out[ch]["alive"] = pid, True
    if "tasks" in _tables(conn):
        for r in conn.execute("SELECT channel_key AS ch, count(*) AS n FROM tasks GROUP BY channel_key"):
            if r["ch"] in out:
                out[r["ch"]]["tasks"] = r["n"]
    answered = {}                                    # each agent's newest pending answer: one no call has carried yet
    if "_pending" in _tables(conn) and CHANNEL in _columns(conn, "_pending"):
        answered = {ch: _seconds(t) for ch, t in conn.execute(
            f"SELECT {CHANNEL}, max(received_at) FROM _pending WHERE {CHANNEL} IS NOT NULL GROUP BY {CHANNEL}")}
    building = _running_builds(conn)
    last_user = {}                                   # each agent's newest user message: what it was last asked
    for ch, text, payload in conn.execute(
            f"SELECT e.{CHANNEL}, e.text, e.payload_json FROM events e JOIN event_types t ON t.event_type_id = e.event_type_id "
            f"WHERE t.name = 'user_message' AND e.row_id IN (SELECT max(e2.row_id) FROM events e2 "
            f"JOIN event_types t2 ON t2.event_type_id = e2.event_type_id WHERE t2.name = 'user_message' GROUP BY e2.{CHANNEL})"):
        last_user[ch] = (text if text else readable(payload)) or ""
    tables = _tables(conn)
    for ch, a in out.items():
        a["harness"] = _harness(conn, ch)
        a["last_user_message"] = " ".join(last_user.get(ch, "").split())[:600] or None
        a["last"] = max(a["last_read"] or 0, a["last_event"] or 0, answered.get(ch) or 0) or None   # its latest activity
        a["building"] = ch in building
        a["turn_over"] = turn_over(conn, ch, tables)[0]
        a["status"] = status_of(a.get("alive"), a["turn_over"], a["last"], now)
        a["running"] = a["building"] or a["status"] == RUNNING
    return sorted(out.values(), key=lambda a: a["created"] or 0, reverse=True)   # in place: newest created first


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
                        f"WHERE e.{CHANNEL} = ? AND t.name NOT IN ('environment_update', 'context_stream') "
                        "ORDER BY e.row_id DESC LIMIT 1", (channel,)).fetchone()
    if last is None:
        return True, None
    return last[0] == "agent_message", _seconds(last[1])


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


CODEX_TYPES = {"message", "function_call", "function_call_output", "custom_tool_call", "custom_tool_call_output",
               "reasoning", "local_shell_call", "web_search_call", "compaction", "compaction_summary"}


def harness_of(payloads) -> Optional[str]:
    """The harness an agent runs on, as its events' shape tells -- ag stores no name: codex's
    Responses items, Claude Code's Anthropic message pieces, pi's messages, opencode's
    {info, parts} messages; None when none of them shows."""
    for p in payloads:
        if not isinstance(p, dict):
            continue
        if "info" in p and ("parts" in p or "sessionID" in (p.get("info") or {})) or "sessionID" in p:
            return "opencode"
        if p.get("type") in CODEX_TYPES and ("role" in p or "call_id" in p or "summary" in p or "id" in p):
            return "codex"
        blocks = [c for c in p.get("content") or [] if isinstance(c, dict)] if isinstance(p.get("content"), list) else []
        kinds = {c.get("type") for c in blocks}
        if kinds & {"input_text", "output_text"}:
            return "codex"
        if "api" in p or p.get("role") == "toolResult" or kinds & {"toolCall"}:
            return "pi"
        if kinds & {"tool_use", "tool_result", "redacted_thinking"} or p.get("role") == "system":
            return "claude"
    return None


def _harness(conn, channel: str) -> Optional[str]:
    rows = conn.execute(f"SELECT payload_json FROM events WHERE {CHANNEL} = ? ORDER BY row_id LIMIT 60", (channel,))
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
    last = conn.execute(f"SELECT max(read_id) FROM _reads WHERE {CHANNEL} = ?", (channel,)).fetchone()[0]
    kept = _USAGE.get((path, channel))
    if kept and kept[0] == last:
        return dict(kept[1])
    cut = ("LEFT JOIN _builds b ON b.build_id = CAST(r.basis AS INTEGER) " if "_builds" in tables else "")
    since = "b.open_from_row IS NULL OR i.row_id >= b.open_from_row" if cut else "1"
    rows = conn.execute(
        f"SELECT CASE WHEN i.row_id IS NULL THEN 'made' WHEN {since} THEN 'recent' ELSE 'kept' END AS kind, "
        "coalesce(t.name, m.name, '?') AS item, count(*) AS n, sum(coalesce(e.tokens, m.tokens, 0)) AS tok "
        f"FROM _read_items i JOIN _reads r ON r.read_id = i.read_id AND r.{CHANNEL} = ? {cut}"
        "LEFT JOIN events e ON e.row_id = i.row_id LEFT JOIN event_types t ON t.event_type_id = e.event_type_id "
        "LEFT JOIN _made_items m ON m.made_id = i.made_id GROUP BY 1, 2", (channel,)).fetchall()
    entries = [{"group": RECENT if r["kind"] == "recent" else KEPT if r["kind"] == "kept"
                else AG_KINDS.get(r["item"], "ag's sections"), "name": r["item"], "items": r["n"], "tokens": r["tok"] or 0}
               for r in rows]
    cols = _columns(conn, "_reads")
    pre = "preamble_json" if "preamble_json" in cols else "NULL"
    real = "real_tokens" if "real_tokens" in cols else "NULL"
    per_read = conn.execute(f"SELECT read_id, {pre}, {real} FROM _reads WHERE {CHANNEL} = ?", (channel,)).fetchall()
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
        f"JOIN _reads r ON r.read_id = i.read_id AND r.{CHANNEL} = ? LEFT JOIN events e ON e.row_id = i.row_id "
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
        return _agent(conn, gatherer, channel, llm if llm is not None else llm_calls())
    finally:
        conn.close()


def _agent(conn, gatherer: str, channel: str, llm: List[dict]) -> dict:
    tables, read_cols = _tables(conn), _columns(conn, "_reads")
    sizes = [c for c in ("est_tokens", "real_tokens", "limit_tokens") if c in read_cols]
    reads = []
    for r in conn.execute(f"SELECT read_id, read_at, row_id, basis{''.join(', ' + c for c in sizes)} FROM _reads "
                          f"WHERE {CHANNEL} = ? ORDER BY read_id", (channel,)):
        reads.append({"read_id": r["read_id"], "at": _seconds(r["read_at"]), "row_id": r["row_id"],
                      "basis": r["basis"], **{k: (r[k] if k in sizes else None)
                                             for k in ("est_tokens", "real_tokens", "limit_tokens")}})
    tasks = []
    if "tasks" in tables:
        times = dict(conn.execute(f"SELECT row_id, inserted_at FROM events WHERE {CHANNEL} = ?", (channel,)))
        for r in conn.execute("SELECT task_index, name, description, first_row, last_row, tokens FROM tasks "
                              "WHERE channel_key = ? ORDER BY task_index", (channel,)):
            tasks.append({"index": r["task_index"], "name": r["name"], "description": r["description"],
                          "first_row": r["first_row"], "last_row": r["last_row"], "tokens": r["tokens"],
                          "started": _seconds(times.get(r["first_row"])), "ended": _seconds(times.get(r["last_row"]))})
    sent = dict(conn.execute(                # ag's count of all it sent: what each read returned, added up
        "SELECT i.read_id, coalesce(sum(e.tokens), 0) + coalesce(sum(m.tokens), 0) FROM _read_items i "
        f"JOIN _reads r ON r.read_id = i.read_id AND r.{CHANNEL} = ? "
        "LEFT JOIN events e ON e.row_id = i.row_id LEFT JOIN _made_items m ON m.made_id = i.made_id "
        "GROUP BY i.read_id", (channel,)))
    pre = dict(conn.execute(f"SELECT read_id, preamble_json FROM _reads WHERE {CHANNEL} = ?", (channel,))) \
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
    return {"gatherer": gatherer, "channel": channel, "harness": _harness(conn, channel), "reads": reads,
            "pending": _pending(conn, channel, tables),
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
                          f"WHERE {CHANNEL} = ? ORDER BY pending_id", (channel,)):
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
                f"LEFT JOIN event_types t ON t.event_type_id = e.event_type_id WHERE e.{CHANNEL} = ? AND e.row_id > ? "
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
        top = last_row if last_row is not None else 2 ** 62
        where = f"e.{CHANNEL} = ? AND e.row_id >= ? AND e.row_id <= ?"
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


def _output(value) -> str:
    """A tool result's words: a string, or the text of its blocks ("[image]" for an image)."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        words = []
        for b in value:
            if isinstance(b, str):
                words.append(b)
            elif isinstance(b, dict):
                if isinstance(b.get("text"), str):
                    words.append(b["text"])
                elif b.get("type") in ("image", "input_image"):
                    words.append("[image]")
        return "\n".join(words)
    if isinstance(value, dict):
        for k in ("output", "content", "text"):
            if k in value:
                return _output(value[k])
    return "" if value is None else json.dumps(value, ensure_ascii=False)


def _arguments(raw):
    """A codex call's arguments: a JSON string, read as its object when it is one."""
    if isinstance(raw, str):
        try:
            got = json.loads(raw)
            return got if isinstance(got, dict) else raw
        except ValueError:
            return raw
    return raw


def parts(event_type: str, payload_json: Optional[str], text: Optional[str]) -> List[dict]:
    """An event as the transcript shows it, whatever harness wrote it: its parts, each one of
        {"kind": "text", "role": user/assistant/system, "text"}
        {"kind": "thinking", "text"}                ("" when it is encrypted)
        {"kind": "call", "id", "name", "input"}     a tool call (input: its object, or a string)
        {"kind": "result", "id", "error", "text"}   a tool's result, `id` its call's
        {"kind": "note", "name", "text"}            anything else: the harness's or ag's own messages
    The harness's own format is read here (Claude Code's content blocks, codex's Responses items),
    and nowhere else: anything this does not know shows as its readable text."""
    try:
        p = json.loads(payload_json) if payload_json else None
    except ValueError:
        p = None
    role = ROLES.get(event_type)
    if role is None:                         # not the conversation: a system message, ag's notices
        return [{"kind": "note", "name": event_type, "text": text or readable(payload_json)}]
    out: List[dict] = []
    if isinstance(p, dict) and p.get("type") in CODEX_TYPES | {"tool_search_call", "tool_search_output"}:
        kind = p["type"]
        if kind in ("function_call", "custom_tool_call", "tool_search_call"):
            out.append({"kind": "call", "id": p.get("call_id") or p.get("id"), "name": p.get("name") or kind,
                        "input": _arguments(p.get("arguments", p.get("input")))})
        elif kind == "local_shell_call":
            out.append({"kind": "call", "id": p.get("call_id") or p.get("id"), "name": "local_shell",
                        "input": (p.get("action") or {})})
        elif kind == "web_search_call":
            out.append({"kind": "call", "id": p.get("id"), "name": "web_search", "input": p.get("action") or {}})
        elif kind.endswith("_output"):
            out.append({"kind": "result", "id": p.get("call_id"), "error": False,
                        "text": _output(p.get("output", p.get("tools")))})
        elif kind == "reasoning":
            out.append({"kind": "thinking", "text": "\n\n".join(s.get("text", "") for s in p.get("summary") or []
                                                                if isinstance(s, dict))})
    elif isinstance(p, dict) and isinstance(p.get("content"), list):
        speaker = "system" if p.get("role") in ("system", "developer") else role
        for b in p["content"]:
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
    if not out:                              # a format this does not read: its words, as its type says
        words = text or readable(payload_json)
        if event_type == "agent_reasoning":
            out.append({"kind": "thinking", "text": words if words != payload_json else ""})
        elif words:
            out.append({"kind": "text", "role": role, "text": words})
    for part in out:
        for k in ("text", "input"):
            if k in part:
                part[k] = _clip(part[k])
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
        cols = ("SELECT e.row_id, t.name AS type, e.text, e.payload_json, e.inserted_at FROM events e "
                f"LEFT JOIN event_types t ON t.event_type_id = e.event_type_id WHERE e.{CHANNEL} = ? ")
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
            earlier = conn.execute(f"SELECT 1 FROM events WHERE {CHANNEL} = ? AND row_id < ? LIMIT 1",
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
    agent over time, and the last read's contents of each (by kind, and item by item)."""
    h = home()
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
    return {"home": h, "agents": agents, "reads": reads, "contexts": contexts}
