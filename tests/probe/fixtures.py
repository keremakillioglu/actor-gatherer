"""A version's fixtures, written from what a probe run captured (probe.py): the calls the tap saw (tap.py), the longest
conversation a turn sent, and the harness's own record of the session -- trimmed to what the rules read, and nothing
of the person's in them -- then the reading of them (reading.py) as expected.json.

What is kept of a call: its method and path; the headers the rules read (never a key or a token); of its body, the
conversation (`messages`, a Responses `input`) and what says which call it is (Claude Code's `metadata` -- its session
alone --, codex's `client_metadata`, `prompt_cache_key`), its tools by name; never its system prompt or instructions. A
call's conversation keeps its first two and last six messages. Every string longer than LONG keeps its head and its
tail (not one holding a task's notice); home folders, the person's name as their home has it and email addresses are replaced (PRIVATE, EMAIL)."""

import json
import os
import re
from typing import Dict, List, Optional, Tuple

import harness_kit
from harness_kit import CallKind, Kind

LONG = 1600                     # a string longer than this keeps its head and tail
HEAD, TAIL = 1000, 400
RECORD_LONG = 700               # the same, in a record's lines
CALL_MESSAGES = (2, 6)          # a call's conversation: its first and last messages kept
HEADERS = re.compile(r"^(user-agent|x-claude-code-[\w-]+|anthropic-version|anthropic-beta|x-app|session[-_]id|thread-id|"
                     r"conversation[-_]id|x-codex-[\w-]+|originator|version|openai-beta|x-openai-subagent)$", re.I)
CLAUDE_BODY = ("model", "messages", "tools", "metadata", "max_tokens", "stream", "thinking", "output_config")
CODEX_BODY = ("model", "input", "tools", "client_metadata", "prompt_cache_key", "stream", "store", "include", "reasoning",
              "tool_choice", "parallel_tool_calls")


def private_words() -> List[Tuple[str, str]]:
    """What is replaced in every fixture: the home folder, the user's name as the home names them (an email address is
    replaced wherever it is: EMAIL)."""
    home = os.path.expanduser("~")
    user = os.path.basename(home)
    return [(home + "/", "/Users/me/"), (home, "/Users/me"), (f"-Users-{user}-", "-Users-me-")]


PRIVATE = private_words()
MCP = re.compile(r"mcp__[A-Za-z0-9_-]+")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
INSTALL = re.compile(r'(installation_id\\?"\s*:\s*\\?")[0-9a-f-]{36}')
#: The lines of a record its follower reads, by their type (and their payload's type, codex's) -- besides, in Claude
#: Code's, any line with a task's notice in it, which its follower reads whatever its type: that line kept as its
#: notices alone (`notices_of`).
RECORD_TYPES = {"claude": {"user": None, "assistant": None, "queue-operation": None},
                "codex": {"event_msg": ("task_started", "task_complete", "turn_aborted", "item_completed"),
                          "response_item": ("message", "function_call", "custom_tool_call", "function_call_output",
                                            "custom_tool_call_output")}}
NOTICE = "<task-notification>"


def scrub(text: str, long: int = LONG) -> str:
    for old, new in PRIVATE:
        text = text.replace(old, new)
    text = INSTALL.sub(lambda m: m.group(1) + "00000000-0000-0000-0000-000000000000",
                       EMAIL.sub("me@example.com", MCP.sub("mcp__x", text)))
    if len(text) > long and NOTICE not in text:          # a task's notice whole: the follower reads it
        head, tail = (HEAD, TAIL) if long == LONG else (long * 2 // 3, long // 4)
        text = f"{text[:head]}\n[… {len(text) - head - tail} characters trimmed …]\n{text[-tail:]}"
    return text


def clean(value, long: int = LONG):
    """`value` with every string scrubbed (`scrub`)."""
    if isinstance(value, str):
        return scrub(value, long)
    if isinstance(value, list):
        return [clean(v, long) for v in value]
    if isinstance(value, dict):
        return {scrub(k, 10 ** 6): clean(v, long) for k, v in value.items()}
    return value


def tools(listed) -> list:
    """A call's tools by name (and type, where the API's own), the MCP servers' as one."""
    out, seen = [], set()
    for t in listed if isinstance(listed, list) else []:
        if not isinstance(t, dict):
            continue
        name = MCP.sub("mcp__x", str(t.get("name") or ""))
        stub = {k: v for k, v in (("type", t.get("type")), ("name", name)) if v}
        key = json.dumps(stub, sort_keys=True)
        if key not in seen:
            seen.add(key)
            out.append(stub)
    return out


def call_fixture(harness: str, captured: dict, name: str) -> dict:
    body = captured["body"]
    keep = CLAUDE_BODY if harness == "claude" else CODEX_BODY
    out = {k: body[k] for k in keep if k in body}
    if "tools" in out:
        out["tools"] = tools(out["tools"])
    meta = out.get("metadata")
    if isinstance(meta, dict) and isinstance(meta.get("user_id"), str):
        try:
            sid = json.loads(meta["user_id"]).get("session_id")
        except (ValueError, AttributeError):
            sid = None
        out["metadata"] = {"user_id": json.dumps({"session_id": sid})} if sid else {}
    key = "messages" if harness == "claude" else "input"
    trimmed = 0
    first, last = CALL_MESSAGES
    if isinstance(out.get(key), list) and len(out[key]) > first + last:
        trimmed = len(out[key]) - first - last
        out[key] = out[key][:first] + out[key][-last:]
    headers = {k.lower(): v for k, v in captured["headers"].items() if HEADERS.match(k)}
    return clean({"name": name, "method": captured["method"], "path": captured["path"].split("?", 1)[0]
                  + ("?" + captured["path"].split("?", 1)[1] if "?" in captured["path"] else ""),
                  "headers": headers, "body": out, "trimmed": trimmed})


def captured_calls(path: str) -> List[dict]:
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return sorted(out, key=lambda c: c["n"])


#: The model endpoints: a POST to one that the rules do not read as a call is kept too ("unread-<its last part>").
ENDPOINTS = re.compile(r"/(messages|responses)(/[\w-]+)?$")


def pick(harness: str, captured: List[dict], session: str) -> Tuple[List[dict], Optional[dict]]:
    """(the calls kept: the smallest of each kind -- each side call's class or source; a turn after a compaction, and
    one the tap refused, apart --, and of each model endpoint's POSTs the rules do not read as a call; the turn whose
    conversation is the longest)."""
    h = harness_kit.get(harness)
    best: Dict[str, dict] = {}
    longest, size = None, -1
    for c in captured:
        if c["method"] != "POST" or not isinstance(c["body"], dict):
            continue
        got = h.call(c["method"], c["path"], c["headers"], c["body"])
        if got is None:
            endpoint = ENDPOINTS.search(c["path"].split("?", 1)[0])
            name = f"unread-{endpoint.group(0).rsplit('/', 1)[1]}" if endpoint else None
            if name and (name not in best or c["raw_bytes"] < best[name]["raw_bytes"]):
                best[name] = c
            continue
        sort = got.detail.get("class") or got.detail.get("source") or ""
        compacted = got.kind == CallKind.TURN and any(p.kind == Kind.COMPACTION_SUMMARY for p in h.read(h.items(got.history[:4])))
        name = got.kind + (f"-{sort}" if sort and got.kind != CallKind.TURN else "") + ("-compacted" if compacted else "") \
            + ("-error" if c.get("injected") else "")
        if name not in best or c["raw_bytes"] < best[name]["raw_bytes"]:
            best[name] = c
        if got.kind == CallKind.TURN and got.session == session and len(got.history) > size:
            longest, size = c, len(got.history)
    return [call_fixture(harness, best[n], n) for n in sorted(best)], longest


def record_lines(harness: str, path: str) -> List[bytes]:
    """The lines of the harness's record its follower reads (`wanted`, as it goes; of RECORD_TYPES), trimmed: each a
    JSON object written back as the harness writes it, compactly."""
    h = harness_kit.get(harness)
    follower = h.follower(path)
    out = []
    with open(path, "rb") as fh:
        for i, line in enumerate(fh):
            line = line.rstrip(b"\n")
            if not line.strip() or not follower.wanted(line):
                continue
            follower.take(line, f"{i}")
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if not isinstance(value, dict):
                continue
            types = RECORD_TYPES.get(harness, {})
            payload = value.get("payload") if isinstance(value.get("payload"), dict) else {}
            if value.get("type") not in types or (types[value["type"]] and payload.get("type") not in types[value["type"]]):
                if harness != "claude" or NOTICE.encode() not in line or not value.get("timestamp"):
                    continue
                value = {k: value[k] for k in ("type", "timestamp", "sessionId") if k in value} | {
                    "notices": notices_of(value)}
            out.append(json.dumps(clean(value, RECORD_LONG), ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    return out


def notices_of(value) -> List[str]:
    """The strings of a JSON value that hold a task's notice: all the follower reads of a line of another type."""
    if isinstance(value, str):
        return [value] if NOTICE in value else []
    items = value.values() if isinstance(value, dict) else value if isinstance(value, list) else []
    return [s for v in items for s in notices_of(v)]


def write(folder: str, harness: str, calls: List[dict], conversation: Optional[dict], record: Optional[str],
          meta: dict) -> dict:
    """The fixtures in `folder`, and their reading (expected.json). The reading."""
    from reading import features, reading     # beside this module
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "calls.json"), "w", encoding="utf-8") as fh:
        json.dump(calls, fh, indent=1, ensure_ascii=False)
    if conversation is not None:
        key = "messages" if harness == "claude" else "input"
        with open(os.path.join(folder, "conversation.json"), "w", encoding="utf-8") as fh:
            json.dump({"history": clean(conversation["body"][key])}, fh, indent=1, ensure_ascii=False)
    if record:
        with open(os.path.join(folder, "record.jsonl"), "wb") as fh:
            fh.write(b"".join(line + b"\n" for line in record_lines(harness, record)))
    got = reading(folder, harness)
    with open(os.path.join(folder, "expected.json"), "w", encoding="utf-8") as fh:
        json.dump(got, fh, indent=1, ensure_ascii=False)
    with open(os.path.join(folder, "probe.json"), "w", encoding="utf-8") as fh:
        json.dump({**meta, "features": features(got)}, fh, indent=1, ensure_ascii=False)
    return got

