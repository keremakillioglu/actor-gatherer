"""Claude's own count of what Claude Code's calls hold, for the context manager to size contexts by.

ag counts every event with its own tokenizer, and Claude's is not it: Claude makes about half as
many tokens again of the same text, an image costs a fraction of its base64, and the thinking
Claude Code sends back is encrypted -- ag sees no text in it, while the API counts it. The API's
/v1/messages/count_tokens counts exactly, at the request's own upstream with its own credentials,
and so does this, after each call is sent (`Counter.start`: in the background, never delaying it):

    a new step        each step of Claude Code's messages not counted yet (an assistant message with
                      the tool results answering it, or a user message), counted standalone -- after a
                      one-word placeholder, the placeholder subtracted -- then split into its blocks by
                      counting it again without each: a text, image or tool notice taken out, a tool
                      result's content cut to one word; a tool call gets what is left. A step the API
                      will not take alone (a notice of a tool since gone) is counted in the history.
    thinking          counted as sent, and without it: the difference is what the call's thinking
                      cost, and its rise since the blocks already counted is the new block's. The API
                      counts thinking only after the history the model wrote it in, so standalone it
                      would count nothing.
    the context       ag's own items (its sections, notices) standalone, once per text.
    manager's items
    the preamble      the system prompt and the tools, once per version: the placeholder with them,
                      with the system prompt alone, and with neither.

The counts go to the server (`counted`), which sets them in place of the tokenizer's.

Thinking under a build (`fresh_thinking`, before a call is sent): the API counts a thinking
block -- and the model reads it -- only after the exact history it was written in. A build replaces
that history with its sections, so the thinking from before the switch is dead weight the model no
longer reads (and, sent, it was seen to keep the model from thinking again). From a switch to a new
basis on, the thinking from before it is left out of every call -- but a tool loop's: when the
switch came at tool results, the thinking of the turn that called them stays (the API wants it
there). Their counts go to 0: they are not sent again.

What is remembered is ag's, not this process's. Where the context switched to its basis is the read
log's: the server marks each stored event of a context that came before the event its first read
made from that basis responded to (`before_basis`), and that event (`opens_basis`). Whether an event
is counted, and what it cost, are the store's: each stored event of a context comes with its size as
stored and whether that is the provider's count, and the answer names the call's events not counted
yet (`uncounted`). So a hook server started again, or a second one, leaves out and counts what the
last one would have. A `Channel` keeps caches only, whose loss costs count_tokens calls, never a
count: what this process counted (a call read before the last one's counts were stored would count
them again), what thinking cost, and the costs of ag's texts and of the preamble versions.
"""

import asyncio
import copy
import hashlib
import json
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from ..adaptor.to_events import blocks_of, piece_key, pieces, without_cache_control

COUNTED = ("model", "messages", "system", "tools", "tool_choice", "thinking")      # what count_tokens takes
CREDENTIALS = ("authorization", "x-api-key", "anthropic-version", "anthropic-beta")
CANNOT_COUNT = (404, 405, 501)               # the upstream has no count_tokens: not asked again
COUNT_SECONDS = 5.0
STEPS_PER_CALL = 25          # new steps counted after one call at most; the rest after the next ones
PLACEHOLDER = [{"role": "user", "content": [{"type": "text", "text": "x"}]}]
THINKING = ("thinking", "redacted_thinking")
TAKEN_OUT = ("text", "image", "document", "tool_addition", "tool_removal")    # counted without them


def countable(body: dict) -> dict:
    """What count_tokens takes of a Messages request: its model, messages, system prompt, thinking,
    and its tools but the server tools it refuses (tool search itself). Deferred tools stay: once tool
    search has loaded one, the history refers to it, and a count without it is refused."""
    out = {k: body[k] for k in COUNTED if k in body}
    tools = [t for t in out.get("tools") or () if isinstance(t, dict) and t.get("type") in (None, "custom")]
    if tools:
        out["tools"] = tools
    else:
        out.pop("tools", None)
        out.pop("tool_choice", None)
    return out


def without_markers(value):
    """`value` without cache_control anywhere: Claude Code moves its markers from call to call."""
    if isinstance(value, dict):
        return {k: without_markers(v) for k, v in value.items() if k != "cache_control"}
    if isinstance(value, list):
        return [without_markers(v) for v in value]
    return value


def as_blocks(messages: list) -> List[dict]:
    """The messages with a string content as its one text block, cache markers taken out."""
    return [dict(m, content=[{"type": "text", "text": m["content"]}]) if isinstance(m.get("content"), str) else m
            for m in without_markers(messages)]


def signature(block: dict) -> Optional[str]:
    """What names a thinking block: its signature (or redacted data)."""
    return block.get("signature") or block.get("data")


def steps_of(messages: list) -> List[tuple]:
    """(start, end) of each step: cut after any message but an assistant one ending in a tool call or
    thinking -- the cuts the API takes."""
    out, start = [], 0
    for i, m in enumerate(messages):
        blocks = blocks_of(m)
        last = blocks[-1].get("type") if blocks else None
        if m.get("role") != "assistant" or last not in ("tool_use",) + THINKING:
            out.append((start, i + 1))
            start = i + 1
    if start < len(messages):
        out.append((start, len(messages)))
    return out


def answers_tools(messages: list) -> bool:
    """Whether the request's last message is tool results: the call goes on a turn's tool loop."""
    return bool(messages) and messages[-1].get("role") == "user" and \
        any(b.get("type") == "tool_result" for b in blocks_of(messages[-1]))


def stored(context: Optional[list]) -> Dict[str, dict]:
    """The stored events of a context the server answered, by id."""
    return {e["id"]: e for e in context or () if isinstance(e, dict) and isinstance(e.get("id"), str)
            and isinstance(e.get("payload"), dict)}


def thinking_of(context: Optional[list]) -> Dict[str, dict]:
    """The thinking blocks of a context the server answered: each signature, its stored event."""
    return {signature(b): e for e in stored(context).values() for b in blocks_of(e["payload"])
            if b.get("type") in THINKING and signature(b)}


def opened_at(messages: list, piece: Optional[dict]) -> Optional[int]:
    """The index of the message of `messages` holding the event `piece` (its payload), the latest such;
    None if none does."""
    want = [without_cache_control(b) for b in blocks_of(piece or {})]
    if not want:
        return None
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == piece.get("role"):
            have = [without_cache_control(b) for b in blocks_of(messages[i])]
            if all(w in have for w in want):
                return i
    return None


def fresh_thinking(context: Optional[list], messages: list) -> Tuple[list, Dict[str, int]]:
    """(`messages`, made from the server's `context` to be sent, without the thinking from before its
    basis -- see the module's doc --, and what that took out: {its event's id: its size as stored}).
    As they are under the history itself (no event of the context `before_basis`)."""
    before = {s: e for s, e in thinking_of(context).items() if e.get("before_basis")}
    if not before:
        return messages, {}
    opening = next((e["payload"] for e in stored(context).values() if e.get("opens_basis")), None)
    at, keep = opened_at(messages, opening), set()
    if at is not None and answers_tools(messages[:at + 1]):      # the tool loop's own, at the switch
        last = next((m for m in reversed(messages[:at]) if m.get("role") == "assistant"), None)
        keep = {signature(b) for b in blocks_of(last or {}) if b.get("type") in THINKING}
    out, gone = [], {}
    for m in messages:
        if m.get("role") == "assistant" and isinstance(m.get("content"), list):
            kept = []
            for b in m["content"]:
                s = signature(b) if b.get("type") in THINKING else None
                if s in before and s not in keep:
                    gone[before[s]["id"]] = before[s].get("tokens") or 0
                else:
                    kept.append(b)
            if not kept:
                continue
            if len(kept) != len(m["content"]):
                m = dict(m, content=kept)
        out.append(m)
    return out, gone


@dataclass
class Channel:
    """One conversation's caches (see the module's doc): what is known of them is the store's."""
    counting: Set[str] = field(default_factory=set)           # event ids this process counted
    thinking: Dict[str, int] = field(default_factory=dict)    # a thinking block's signature: its cost
    texts: Dict[str, int] = field(default_factory=dict)       # the sha of an ag item's text: its cost
    made: Set[int] = field(default_factory=set)               # made ids counted
    preambles: Set[str] = field(default_factory=set)          # the system prompt and tools counted
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class Counter:
    """Claude's own counts of Claude Code's calls, for one hook: `exact` before a call is sent (the
    pre-send check), `start` once it is sent."""

    def __init__(self, enabled: bool = True, log=lambda gatherer, line: None):
        self.enabled, self.log = enabled, log
        self.uncountable: Set[str] = set()
        self.channels: Dict[tuple, Channel] = {}
        self.tasks: Set[asyncio.Task] = set()

    def channel(self, gatherer: str, channel: str) -> Channel:
        return self.channels.setdefault((gatherer, channel), Channel())

    # ------------------------------------------------------------------ asking the API

    async def ask(self, session, request, body: dict):
        """count_tokens of `body` at the request's upstream with its credentials: the count; an error's
        message (a string) when the API refuses it; None when it cannot be asked."""
        upstream = getattr(request, "upstream", None)
        if not self.enabled or not upstream or upstream in self.uncountable:
            return None
        url = upstream.rstrip("/") + request.path.rstrip("/") + "/count_tokens"
        headers = {k: v for k, v in (request.headers or {}).items() if k.lower() in CREDENTIALS}
        headers["content-type"] = "application/json"
        from aiohttp import ClientError                 # the hook server's own: it runs there
        try:
            async with session.post(url, json=countable(body), headers=headers) as resp:
                if resp.status in CANNOT_COUNT:
                    self.uncountable.add(upstream)
                    print(f"{upstream} cannot count tokens ({resp.status}); not asked again", file=sys.stderr, flush=True)
                    return None
                answer = await resp.json(content_type=None)
        except (ClientError, OSError, ValueError, asyncio.TimeoutError) as exc:
            print(f"counting tokens failed: {exc!r}", file=sys.stderr, flush=True)
            return None
        if resp.status != 200:
            error = answer.get("error") if isinstance(answer, dict) else answer
            return str(error.get("message") if isinstance(error, dict) else error)[:300]
        tokens = answer.get("input_tokens") if isinstance(answer, dict) else None
        return tokens if isinstance(tokens, int) and tokens >= 0 else None

    def session(self):
        from aiohttp import ClientSession, ClientTimeout
        return ClientSession(timeout=ClientTimeout(total=COUNT_SECONDS))

    async def exact(self, request, body: dict) -> Optional[int]:
        """The request counted exactly as it is; None if it cannot be."""
        async with self.session() as session:
            n = await self.ask(session, request, body)
        return n if isinstance(n, int) else None

    # ------------------------------------------------------------------ after a call is sent

    def start(self, request, client, gatherer: str, properties: dict, body: dict, messages: list,
              sent: list, out: dict) -> None:
        """Count what the call holds that is not counted yet, in the background: `messages` Claude
        Code's own, `sent` what the model got, `out` call_ag's (its events, the context answered, the
        events not counted yet, ag's items, its read_id, and `left_out`, what the hook took out of the
        read's context before sending it, and `left_out_events`, by event: `fresh_thinking`'s)."""
        if not self.enabled or not getattr(request, "upstream", None) or request.upstream in self.uncountable:
            return
        task = asyncio.ensure_future(self.count_call(request, client, gatherer, properties, body, messages, sent, out))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def count_call(self, request, client, gatherer, properties, body, messages, sent, out) -> None:
        from ag.integrations.tools.ag_orchestrator.adaptor import CHANNEL
        ch = self.channel(gatherer, properties.get(CHANNEL, ""))
        async with ch.lock:
            try:
                async with self.session() as session:
                    counts = await self.counts(session, request, ch, body, messages, sent, out)
            except Exception as exc:  # noqa: BLE001 - a lost count never breaks the hook
                print(f"[{gatherer}] counting failed: {exc!r}", file=sys.stderr, flush=True)
                return
            if any(counts.values()):
                await client.request("counted", {"gatherer": gatherer, "properties": properties, **counts})
                self.log(gatherer, f"counted {len(counts['counts'])} events, {len(counts['made'])} of ag's items, "
                                   f"{len(counts['preamble_counts'])} preamble parts")

    async def counts(self, session, request, ch: Channel, body: dict, messages: list, sent: list, out: dict) -> dict:
        found = {"counts": {}, "made": {}, "preamble_counts": [], "left_out": {}}
        if out.get("left_out") and isinstance(out.get("read_id"), int):
            found["left_out"][str(out["read_id"])] = out["left_out"]
        known = stored(out.get("context"))
        for event in out.get("left_out_events") or ():      # not sent again: 0, unless the store has it so
            if not (known.get(event, {}).get("counted") and not known[event].get("tokens")):
                found["counts"][event] = 0
                ch.counting.add(event)
        base = {k: body[k] for k in COUNTED if k in body and k != "messages"}
        placeholder = await self.ask(session, request, dict(base, messages=PLACEHOLDER))
        if not isinstance(placeholder, int):
            return found
        await self.preamble(session, request, ch, base, placeholder, found)
        ids = self.event_ids(messages, out.get("events") or [])
        uncounted = set(out["uncounted"]) if isinstance(out.get("uncounted"), list) else None
        await self.steps(session, request, ch, base, placeholder, as_blocks(messages), ids, uncounted, found)
        await self.thinking(session, request, ch, base, as_blocks(sent), out.get("context"), out.get("events"), found)
        for made_id, text in out.get("ag_items") or ():
            if made_id in ch.made or not isinstance(text, str):
                continue
            sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if sha not in ch.texts:
                n = await self.ask(session, request, dict(base, messages=PLACEHOLDER + [
                    {"role": "user", "content": [{"type": "text", "text": text}]}]))
                if not isinstance(n, int):
                    continue
                ch.texts[sha] = max(n - placeholder, 0)
            found["made"][str(made_id)] = ch.texts[sha]
            ch.made.add(made_id)
        return found

    async def preamble(self, session, request, ch: Channel, base: dict, placeholder: int, found: dict) -> None:
        """The system prompt's and the tools' counts, once per version (named as preamble_of names them)."""
        from ag.integrations.tools.ag_orchestrator.call_ag import preamble_of
        parts = {p["name"]: p["text"] for p in preamble_of({"system": base.get("system"), "tools": base.get("tools")})}
        sha = hashlib.sha256(json.dumps(parts, sort_keys=True).encode("utf-8")).hexdigest()
        if not parts or sha in ch.preambles:
            return
        bare = await self.ask(session, request, {"model": base.get("model"), "messages": PLACEHOLDER})
        system = await self.ask(session, request, {"model": base.get("model"), "system": base.get("system"),
                                                    "messages": PLACEHOLDER}) if "system" in parts else bare
        if not (isinstance(bare, int) and isinstance(system, int)):
            return
        sizes = {"system": system - bare, "tools": placeholder - system}
        found["preamble_counts"] += [{"name": n, "text": t, "tokens": max(sizes.get(n, 0), 0)} for n, t in parts.items()]
        ch.preambles.add(sha)

    @staticmethod
    def event_ids(messages: list, events: list) -> List[List[Optional[str]]]:
        """For each block of each message, the id of the event it is (None: one stored before this
        call's events start, counted after an earlier call)."""
        queue: Dict[str, List[str]] = {}
        for e in events:
            if isinstance(e, dict) and isinstance(e.get("id"), str):
                queue.setdefault(piece_key(e.get("payload")), []).append(e["id"])
        out = []
        for m in messages:
            ids = []
            for piece in pieces([m]):
                taken = queue.get(piece_key(piece))
                ids.append(taken.pop(0) if taken else None)
            out.append(ids)
        return out

    async def steps(self, session, request, ch: Channel, base: dict, placeholder: int, messages: list,
                    ids: List[list], uncounted: Optional[Set[str]], found: dict) -> None:
        """The new steps' counts (the module's doc): of the blocks of this call's events the store has
        not counted (`uncounted`; None: not known, all of them), but those this process has."""
        def due(event) -> bool:
            return bool(event) and event not in ch.counting and (uncounted is None or event in uncounted)

        done = 0
        for start, end in steps_of(messages):
            if done >= STEPS_PER_CALL:
                return
            blocks = [(i, j, b) for i in range(start, end) for j, b in enumerate(blocks_of(messages[i]))]
            todo = [(i, j, b) for i, j, b in blocks if b.get("type") not in THINKING
                    and j < len(ids[i]) and due(ids[i][j])]
            if not todo:
                continue
            # thinking is the thinking count's: the step without it, each block keeping its place
            at = [[j for j, b in enumerate(blocks_of(m)) if b.get("type") not in THINKING] for m in messages[start:end]]
            step = [dict(m, content=[blocks_of(m)[j] for j in js]) for m, js in zip(copy.deepcopy(messages[start:end]), at)]
            if any(not m["content"] for m in step):
                at = [list(range(len(blocks_of(m)))) for m in messages[start:end]]
                step = copy.deepcopy(messages[start:end])
            costs = await self.split(session, request, base, placeholder, step, start)
            if costs is not None:
                costs = {(i, at[i - start][j]): n for (i, j), n in costs.items()}
            if costs is None:                       # not standalone: in the history, by size
                costs = await self.in_history(session, request, base, messages, start, end)
            if costs is None:
                continue
            for (i, j), n in costs.items():
                event = ids[i][j] if j < len(ids[i]) else None
                if due(event):
                    found["counts"][event] = max(n, 0)
                    ch.counting.add(event)
            done += 1

    async def split(self, session, request, base: dict, placeholder: int, step: list, offset: int):
        """{(message index, block index): cost} of a step's blocks but thinking, standalone; None if the
        API will not take the step alone."""
        whole = await self.ask(session, request, dict(base, messages=PLACEHOLDER + step))
        if not isinstance(whole, int):
            return None
        costs, rest = {}, []
        for i, m in enumerate(step):
            for j, b in enumerate(blocks_of(m)):
                kind = b.get("type")
                if kind in THINKING:
                    continue
                n = None
                if kind in TAKEN_OUT:
                    cut = copy.deepcopy(step)
                    cut[i]["content"] = [x for k, x in enumerate(cut[i]["content"]) if k != j]
                    cut = [x for x in cut if x["content"]]
                    c = await self.ask(session, request, dict(base, messages=PLACEHOLDER + cut)) if cut else placeholder
                    n = whole - c if isinstance(c, int) else None
                elif kind == "tool_result":
                    cut = copy.deepcopy(step)
                    cut[i]["content"][j]["content"] = "x"
                    c = await self.ask(session, request, dict(base, messages=PLACEHOLDER + cut))
                    n = whole - c + 1 if isinstance(c, int) else None      # beside a one-word result
                if n is None:
                    rest.append((offset + i, j))
                else:
                    costs[(offset + i, j)] = n
        left = whole - placeholder - sum(costs.values())
        if rest:                                    # tool calls: what is left, shared
            for k, at in enumerate(rest):
                costs[at] = left // len(rest) + (1 if k < left % len(rest) else 0)
        elif costs:                                 # the step's framing, on its last block
            last = list(costs)[-1]
            costs[last] += left
        return costs

    async def in_history(self, session, request, base: dict, messages: list, start: int, end: int):
        """{(message index, block index): cost} of a step counted where it is -- the history to its end
        less the history before it -- shared by the size of each block but thinking; None if refused."""
        before = await self.ask(session, request, dict(base, messages=messages[:start])) if start else 0
        upto = await self.ask(session, request, dict(base, messages=messages[:end]))
        if not (isinstance(before, int) and isinstance(upto, int)):
            return None
        sizes = {(i, j): len(json.dumps(b)) for i in range(start, end)
                 for j, b in enumerate(blocks_of(messages[i])) if b.get("type") not in THINKING}
        total, whole = sum(sizes.values()) or 1, upto - before
        return {at: whole * s // total for at, s in sizes.items()}

    async def thinking(self, session, request, ch: Channel, base: dict, sent: list, context: Optional[list],
                       new_events: Optional[list], found: dict) -> None:
        """The sent thinking's cost, by counting the call with and without it: a new block's is the rise
        over the blocks already counted -- by the store (as the context came), or by this process."""
        events = {**thinking_of(new_events), **thinking_of(context)}
        for s, e in events.items():
            if e.get("counted") and s not in ch.thinking:
                ch.thinking[s] = e.get("tokens") or 0
        sigs = [signature(b) for m in sent if m.get("role") == "assistant"
                for b in blocks_of(m) if b.get("type") in THINKING and signature(b)]
        new = [s for s in sigs if s not in ch.thinking]
        if not new:
            return
        full = await self.ask(session, request, dict(base, messages=sent))
        bare = []
        for m in copy.deepcopy(sent):
            if m.get("role") == "assistant":
                m["content"] = [b for b in m["content"] if b.get("type") not in THINKING]
                if not m["content"]:
                    continue
            bare.append(m)
        without = await self.ask(session, request, dict(base, messages=bare))
        if not (isinstance(full, int) and isinstance(without, int)):
            return
        rise = full - without - sum(ch.thinking[s] for s in sigs if s in ch.thinking)
        for k, s in enumerate(new):
            ch.thinking[s] = max(rise // len(new) + (1 if k < rise % len(new) else 0), 0)
            if s in events:
                found["counts"][events[s]["id"]] = ch.thinking[s]
                ch.counting.add(events[s]["id"])

    async def close(self) -> None:
        """Let counts still being taken finish (briefly)."""
        if self.tasks:
            await asyncio.wait(list(self.tasks), timeout=COUNT_SECONDS * 2)
