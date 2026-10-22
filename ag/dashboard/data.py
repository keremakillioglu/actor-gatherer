"""What the dashboard shows, read from the context manager's home -- every gatherer's
database, opened read-only, and ag's own logs -- as plain JSON-ready dicts.

    home()                        every gatherer and its agents (channels), with their
                                  status; the hook servers ag started
    agent(gatherer, channel)      one agent over time: each read's size (ag's own count,
                                  the provider's, the harness's limit), its rebuilds, its
                                  tasks and how many had begun by each read, its builds,
                                  and the Gatherer's model calls made for it
    read(gatherer, read_id)       what one read put in the agent's context, by kind

An agent is a channel of a gatherer: one harness session (codex's thread, Claude Code's
session, ...); which harness, its events' shape tells (`harness_of`). It is RUNNING when its last read is recent (RUNNING_SECONDS) or a build is
running for it, else idle. A REBUILD is a read whose context comes from another build
than the agent's read before it: the condensed history was replaced.

Each read has three sizes: `sent_tokens`, ag's own count of everything it sent (what the
read returned, `_read_items`, added up -- what read() breaks down); `est_tokens`, the
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

from ag.ag_harness.store import paths

RUNNING_SECONDS = 120          # a read this recent: the agent is running
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
    root = paths.TRACE_DIR
    if not os.path.isdir(root):
        return []
    return sorted(n for n in os.listdir(root) if os.path.exists(os.path.join(root, n, "context.db")))


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
        from ag.integrations.harnesses.codex.setup.hook_servers import HookServers
        return [{"port": s.port, "pid": s.pid, "upstream": s.upstream} for s in HookServers(paths.AG_HOME).running()]
    except Exception:  # noqa: BLE001 - the dashboard shows what it can
        return []


def home() -> dict:
    """Every gatherer and its agents, newest activity first, and the hook servers ag started."""
    now = time.time()
    gatherers = []
    for name in gatherer_names():
        conn = _connect(name)
        if conn is None:
            continue
        try:
            agents = _agents(conn, now)
        except sqlite3.Error as exc:
            gatherers.append({"name": name, "policy": _policy(name), "error": str(exc), "agents": []})
            continue
        finally:
            conn.close()
        gatherers.append({"name": name, "policy": _policy(name), "agents": agents,
                          "last": max((a["last"] or 0 for a in agents), default=0) or None})
    gatherers.sort(key=lambda g: g.get("last") or 0, reverse=True)
    return {"home": paths.AG_HOME, "now": now, "running_seconds": RUNNING_SECONDS, "gatherers": gatherers,
            "hook_servers": _hook_servers()}


def _agents(conn, now: float) -> List[dict]:
    if CHANNEL not in _columns(conn, "events"):
        return []
    sizes = [c for c in ("est_tokens", "real_tokens", "limit_tokens") if c in _columns(conn, "_reads")]
    out: Dict[str, dict] = {}
    for r in conn.execute(f"SELECT {CHANNEL} AS ch, count(*) AS n, max(inserted_at) AS last FROM events "
                          f"WHERE {CHANNEL} IS NOT NULL GROUP BY {CHANNEL}"):
        out[r["ch"]] = {"channel": r["ch"], "events": r["n"], "last_event": _seconds(r["last"]), "reads": 0,
                        "last_read": None, "cwd": None, "tasks": 0, "est_tokens": None, "real_tokens": None,
                        "limit_tokens": None, "sent_tokens": None}
    if CHANNEL in _columns(conn, "_reads"):
        for r in conn.execute(f"SELECT {CHANNEL} AS ch, count(*) AS n, max(read_at) AS last FROM _reads "
                              f"GROUP BY {CHANNEL}"):
            if r["ch"] in out:
                out[r["ch"]].update(reads=r["n"], last_read=_seconds(r["last"]))
        cwd = "p_cwd" in _columns(conn, "_reads")
        for ch, a in out.items():
            last = conn.execute(f"SELECT {', '.join(['read_id'] + sizes + (['p_cwd'] if cwd else []))} FROM _reads "
                                f"WHERE {CHANNEL} = ? ORDER BY read_id DESC LIMIT 1", (ch,)).fetchone()
            if last is not None:
                a.update({k: last[k] for k in sizes}, cwd=last["p_cwd"] if cwd else None,
                         sent_tokens=_sent(conn, last["read_id"]))
    if "tasks" in _tables(conn):
        for r in conn.execute("SELECT channel_key AS ch, count(*) AS n FROM tasks GROUP BY channel_key"):
            if r["ch"] in out:
                out[r["ch"]]["tasks"] = r["n"]
    building = _running_builds(conn)
    for ch, a in out.items():
        a["harness"] = _harness(conn, ch)
        a["last"] = max(a["last_read"] or 0, a["last_event"] or 0) or None
        a["building"] = ch in building
        a["running"] = a["building"] or bool(a["last_read"] and now - a["last_read"] < RUNNING_SECONDS)
    return sorted(out.values(), key=lambda a: a["last"] or 0, reverse=True)


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
    for r in reads:
        r["sent_tokens"] = sent.get(r["read_id"])
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
    return {"gatherer": gatherer, "channel": channel, "harness": _harness(conn, channel), "reads": reads,
            "tasks": tasks, "builds": builds,
            "checks": checks, "rebuilds": sum(1 for r in reads if r["rebuild"]), "llm": _llm_summary(mine),
            "llm_attributed_by_time": sum(1 for c in mine if not c.get("job"))}


# ---------------------------------------------------------------- what a read held

#: The agent's own events, verbatim: since the cut of the build the read was made from (all of
#: them before any build), and those kept from before it (its preamble, the pinned rows).
RECENT, KEPT = "Recent history", "Kept from before the cut"
#: ag's own messages by name, as the read's breakdown groups them; any other name is a section of its own.
AG_KINDS = {"environment_update": "File-change notices", "parallel_request": "Other agents' requests",
            "context_stream": "Stream messages"}


def read(gatherer: str, read_id: int) -> dict:
    """What read `read_id` put in the context: each item's kind and size (the manager's own
    count; all of them add up to its `sent_tokens`), grouped as the agent's own events,
    verbatim, by event type -- RECENT (since the cut of the read's build) and KEPT (before
    it) -- and ag's own messages, by name."""
    conn = _connect(gatherer)
    if conn is None:
        return {"error": f"no database for gatherer {gatherer!r}"}
    try:
        groups: Dict[str, dict] = {}
        meta = conn.execute("SELECT * FROM _reads WHERE read_id = ?", (read_id,)).fetchone()
        cut = None                       # where the build the read was made from cut the history
        if meta is not None and meta["basis"] and str(meta["basis"]).isdigit() and "_builds" in _tables(conn):
            found = conn.execute("SELECT open_from_row FROM _builds WHERE build_id = ?", (int(meta["basis"]),)).fetchone()
            cut = found[0] if found else None
        rows = conn.execute(
            "SELECT i.row_id, i.made_id, t.name AS type, e.tokens AS etok, m.name AS made, m.tokens AS mtok "
            "FROM _read_items i LEFT JOIN events e ON e.row_id = i.row_id "
            "LEFT JOIN event_types t ON t.event_type_id = e.event_type_id "
            "LEFT JOIN _made_items m ON m.made_id = i.made_id WHERE i.read_id = ? ORDER BY i.position",
            (read_id,)).fetchall()
        for r in rows:
            if r["row_id"] is not None:          # the agent's own, verbatim
                group = RECENT if cut is None or r["row_id"] >= cut else KEPT
                name, tokens = r["type"] or "?", r["etok"] or 0
            else:
                name, tokens = r["made"] or "?", r["mtok"] or 0
                group = AG_KINDS.get(name, "ag's sections")
            g = groups.setdefault(group, {"group": group, "tokens": 0, "items": 0, "by_name": {}})
            g["tokens"] += tokens
            g["items"] += 1
            n = g["by_name"].setdefault(name, {"name": name, "tokens": 0, "items": 0})
            n["tokens"] += tokens
            n["items"] += 1
        return {"read_id": read_id, "cut": cut, "at": _seconds(meta["read_at"]) if meta else None,
                "real_tokens": meta["real_tokens"] if meta is not None and "real_tokens" in meta.keys() else None,
                "groups": [dict(g, by_name=sorted(g["by_name"].values(), key=lambda n: -n["tokens"]))
                           for g in sorted(groups.values(), key=lambda g: -g["tokens"])]}
    finally:
        conn.close()


# ---------------------------------------------------------------- the Gatherer's own model calls

def llm_calls() -> List[dict]:
    """The Gatherer's model calls, as its call log keeps them (<home>/logs/llm): each one's
    purpose, model, start, seconds, tokens in and out, error, and the job it ran for when
    the worker named it (`job`: gatherer, job, id, properties)."""
    out = []
    for path in sorted(glob.glob(os.path.join(paths.AG_HOME, "logs", "llm", "*.json"))):
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
    agent over time, and the last read's contents of each."""
    h = home()
    llm = llm_calls()
    agents, reads = {}, {}
    for g in h["gatherers"]:
        for a in g["agents"]:
            detail = agent(g["name"], a["channel"], llm)
            agents[f"{g['name']}\u0000{a['channel']}"] = detail
            if detail.get("reads"):
                rid = detail["reads"][-1]["read_id"]
                reads[f"{g['name']}\u0000{rid}"] = read(g["name"], rid)
    return {"home": h, "agents": agents, "reads": reads}
