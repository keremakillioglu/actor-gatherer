"""The provider's own count of what codex's calls hold, for the context manager to size contexts by --
as the Claude Code hook's counting.py does with Anthropic's count_tokens, here with OpenAI's
/v1/responses/input_tokens.

ag counts every event with its own tokenizer (o200k_base), and the model's count is not quite it:
codex's tool definitions come out higher by ag's count, the conversation lower (the framing of each
item), and a reasoning item -- encrypted -- is 0 to ag. The count endpoint counts a request as the
call itself is counted, and this asks it, after each call is sent (`Counter.start`: in the
background, never delaying it):

    a new step        each step of codex's items not counted yet (the items up to a cut that leaves
                      no tool call without its output), counted standalone -- after a one-word
                      placeholder, the placeholder subtracted -- then split into its items by
                      counting it again without each: a message (or other context item) taken out,
                      a tool output's content cut to one word; a tool call gets what is left. A step
                      the endpoint will not take alone is counted in the history, shared by size.
    the context       ag's own items (its sections, notices) standalone, once per text, as they are
    manager's items   sent (to_messages.ag_message).
    the preamble      the instructions and the tools, once per version, where the request has them
                      as fields: the placeholder with them, with the instructions alone, and with
                      neither. Codex 0.164 sends neither: its instructions and tool definitions are
                      input items (developer messages, `additional_tools`), events, counted as steps.

Where it asks: at the request's own upstream with its own credentials (an API-key login: the API's
/v1/responses/input_tokens) -- as for Claude Code. Under a ChatGPT login, codex's upstream (the
ChatGPT backend) has no such endpoint; the API's is asked instead, with the key in OPENAI_API_KEY as
the hook server has it (none: not asked). An endpoint that cannot count is not asked again; a model
it does not know, not again for that model.

Reasoning. The endpoint counts codex's encrypted reasoning as nothing -- counted with it or without,
a request comes to the same -- though the call's own count (its reported input tokens, `measured`)
holds it. So, once that count is back (`Counter.reported`): the request as sent, counted by the
endpoint, falls short of it by what the reasoning it sends costs; less the reasoning already
costed, that is what the reasoning new in it costs, shared evenly among those items (as Claude
Code's thinking's rise is). Reasoning stays where it is sent: codex's model reads an earlier turn's
reasoning while it stays beside what it produced, and the policy cuts and stubs whole steps, so it
always does.

Without the endpoint (no key, a model it does not know, an upstream that cannot count), the call's
own counts tell the rest (`Counter.reported`): two calls of a channel in a row, the later's context
the earlier's with items added (the same build, nothing taken out), differ by exactly what those
items cost -- shared among them as ag's own counts would share it (by the length of what ag counts of
each: nothing of a reasoning item, whose cost its neighbours then carry). A channel's first call is
so from nothing. After a build, the first call is not differenced; the ones after it
are again.

Codex's items are read through the adaptor class the hook is given (its `to_events` for an item's
event, its `to_messages` for how the context manager's own items are sent), as the hook reads them.

The counts go to the server (`counted`), which sets them in place of the tokenizer's.

What is known is ag's, not this process's: each stored event of a context comes with its size as
stored and whether that is the provider's count, and the answer names the call's events not counted
yet (`uncounted`). So a hook server started again counts what the last one would have, and costs
reasoning already costed at what it was found to cost (`learn`). A `Channel` keeps caches, and what
a call needs until its own count is back; differencing, which needs the last call's own count,
starts again at the next call after one whose events the store has counted.
"""

import asyncio
import copy
import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urlsplit

TOOL_CALL, TOOL_OUTPUT, AGENT_REASONING = "tool_call", "tool_output", "agent_reasoning"   # the event types

COUNTED = ("model", "input", "instructions", "tools", "tool_choice", "parallel_tool_calls", "reasoning", "text",
           "truncation")                     # what the count endpoint takes
CREDENTIALS = ("authorization", "openai-organization", "openai-project")
CANNOT_COUNT = (403, 404, 405, 501)          # the endpoint is not there: not asked again
API = "https://api.openai.com/v1/responses/input_tokens"   # where a ChatGPT login's calls are counted
KEY_ENV = "OPENAI_API_KEY"                   # the key it is asked with
CHATGPT = "/backend-api/"                    # a ChatGPT login's path (codex's chatgpt.com/backend-api/codex)
COUNT_SECONDS = 5.0
REPORT_SECONDS = 600.0       # how long the reasoning's count waits for the call's own counting to finish
STEPS_PER_CALL = 25          # new steps counted after one call at most; the rest after the next ones
KEPT_SENT = 8                # calls whose own count is awaited, per channel, at most
PLACEHOLDER = [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": "x"}]}]
REASONING = "reasoning"


def countable(body: dict) -> dict:
    """What the count endpoint takes of a Responses request: its model, input, instructions, tools and
    the settings that change what the model is given (reasoning, text, tool choice)."""
    return {k: body[k] for k in COUNTED if k in body and body[k] is not None}


def event_of(adaptor, item) -> Optional[dict]:
    """The event an item is, as the adaptor makes it; None for one it makes none of."""
    try:
        made = adaptor.to_events([item]) if isinstance(item, dict) else []
    except Exception:  # noqa: BLE001 - an item the adaptor cannot read: not counted
        return None
    return made[0] if made and isinstance(made[0], dict) else None


def kind_of(adaptor, item) -> str:
    """An item's event type, as the adaptor gives it."""
    return (event_of(adaptor, item) or {}).get("type") or ""


def key_of(adaptor, item) -> str:
    """An item's id, as its event has it (the adaptor's: codex's own id, else a hash of it)."""
    made = event_of(adaptor, item)
    return made["id"] if made and isinstance(made.get("id"), str) else json.dumps(item, sort_keys=True)


def ag_item(adaptor, text: str) -> Optional[dict]:
    """The context manager's own item as the adaptor sends it."""
    try:
        out = adaptor.to_messages([{"type": "ag", "name": "", "text": text}], [])
    except Exception:  # noqa: BLE001
        return None
    return out[0] if out and isinstance(out[0], dict) else None


def steps_of(items: list, kinds: List[str]) -> List[tuple]:
    """(start, end) of each step: cut after any item but a tool call or reasoning, once every tool call
    since the last cut has its output -- the cuts the endpoint takes (an output without its call is
    refused)."""
    out, start, open_ = [], 0, set()
    for i, it in enumerate(items):
        kind, call = kinds[i], it.get("call_id") if isinstance(it, dict) else None
        if kind == TOOL_CALL and call:
            open_.add(call)
        elif kind == TOOL_OUTPUT:
            open_.discard(call)
        if kind not in (TOOL_CALL, AGENT_REASONING) and not open_:
            out.append((start, i + 1))
            start = i + 1
    if start < len(items):
        out.append((start, len(items)))
    return out


def is_reasoning(item) -> bool:
    return isinstance(item, dict) and item.get("type") == REASONING


def weight_of(adaptor, item) -> int:
    """An item's share of a count shared among items, as ag counts it: the length of its event's text,
    else of its JSON; nothing for an event ag counts as nothing (a reasoning item)."""
    made = event_of(adaptor, item) or {}
    if made.get("tokens") == 0:
        return 0
    text = made.get("text")
    return len(text if isinstance(text, str) else json.dumps(item, sort_keys=True, ensure_ascii=False))


@dataclass
class Sent:
    """One call's context as it was sent, for counting by the call's own count: its build, its preamble
    parts ([(name, text)]), and each item's key with what it is in the gatherer -- ("event", its id, or
    None: not this call's) or ("made", made_id) -- and the item."""
    basis: Optional[str]
    preamble: List[Tuple[str, str]]
    keys: List[str]
    parts: List[Tuple[str, Optional[object], dict]]


@dataclass
class Channel:
    """What one conversation's counting remembers between calls: caches (see the module's doc), and
    what a call needs until its own count is back."""
    counting: Set[str] = field(default_factory=set)           # event ids this process counted
    reasoning: Dict[str, int] = field(default_factory=dict)   # a reasoning item's id: its cost
    texts: Dict[str, int] = field(default_factory=dict)       # the sha of an ag item's text: its cost
    made: Set[int] = field(default_factory=set)               # made ids counted
    preambles: Set[str] = field(default_factory=set)          # the instructions and tools counted
    exact: Dict[int, "asyncio.Future"] = field(default_factory=dict)   # read_id: the request as sent, counted
    sent: Dict[int, Sent] = field(default_factory=dict)       # read_id: its context, kept until its count is back
    last: Optional[tuple] = None                              # (Sent, its own count): the last call counted so
                                                              # (False: none yet, but the store has counts)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class Counter:
    """The provider's counts of codex's calls, for one hook: `exact` before a call is sent (the pre-send
    check), `start` once it is sent, `reported` once its own count is back."""

    def __init__(self, adaptor, enabled: bool = True, log=lambda gatherer, line: None):
        self.adaptor, self.enabled, self.log = adaptor, enabled, log
        self.uncountable: Set[str] = set()                    # endpoints that cannot count
        self.unknown: Set[tuple] = set()                      # (endpoint, model): a model it does not know
        self.channels: Dict[tuple, Channel] = {}
        self.tasks: Set[asyncio.Task] = set()

    def channel(self, gatherer: str, channel: str) -> Channel:
        return self.channels.setdefault((gatherer, channel), Channel())

    # ------------------------------------------------------------------ asking the endpoint

    def target(self, request, model) -> Optional[Tuple[str, dict]]:
        """(url, headers) the request is counted at -- its upstream's endpoint with its credentials, or,
        under a ChatGPT login, the API's with OPENAI_API_KEY -- or None: not counted (off, no key, an
        endpoint that cannot count, a model it does not know)."""
        upstream, path = getattr(request, "upstream", None), getattr(request, "path", "") or ""
        if not self.enabled or not upstream:
            return None
        if CHATGPT in path or (urlsplit(upstream).hostname or "").endswith("chatgpt.com"):
            key = os.environ.get(KEY_ENV)
            if not key:
                return None
            url, headers = API, {"authorization": f"Bearer {key}"}
        else:
            url = upstream.rstrip("/") + path.rstrip("/") + "/input_tokens"
            headers = {k: v for k, v in (request.headers or {}).items() if k.lower() in CREDENTIALS}
        if url in self.uncountable or (url, model) in self.unknown:
            return None
        headers["content-type"] = "application/json"
        return url, headers

    def can_count(self, request, body: dict) -> bool:
        return self.target(request, body.get("model")) is not None

    async def ask(self, session, request, body: dict):
        """The endpoint's count of `body`: the count; an error's message (a string) when it refuses it;
        None when it cannot be asked."""
        where = self.target(request, body.get("model"))
        if where is None:
            return None
        url, headers = where
        from aiohttp import ClientError                 # the hook server's own: it runs there
        try:
            async with session.post(url, json=countable(body), headers=headers) as resp:
                answer = await resp.json(content_type=None)
        except (ClientError, OSError, ValueError, asyncio.TimeoutError) as exc:
            print(f"counting tokens failed: {exc!r}", file=sys.stderr, flush=True)
            return None
        error = answer.get("error") if isinstance(answer, dict) else answer
        message = str(error.get("message") if isinstance(error, dict) else error or "")[:300]
        if resp.status == 404 and isinstance(error, dict) and (error.get("code") == "model_not_found"
                                                                or "model" in message.lower() and "exist" in message):
            self.unknown.add((url, body.get("model")))
            print(f"{url} does not know the model {body.get('model')!r}; not asked for it again", file=sys.stderr,
                  flush=True)
            return None
        if resp.status in CANNOT_COUNT:
            self.uncountable.add(url)
            print(f"{url} cannot count tokens ({resp.status}); not asked again", file=sys.stderr, flush=True)
            return None
        if resp.status != 200:
            return message
        tokens = answer.get("input_tokens") if isinstance(answer, dict) else None
        return tokens if isinstance(tokens, int) and tokens >= 0 else None

    def session(self):
        from aiohttp import ClientSession, ClientTimeout
        return ClientSession(timeout=ClientTimeout(total=COUNT_SECONDS))

    async def exact(self, gatherer: str, channel: str, request, body: dict) -> Optional[int]:
        """The request counted exactly as it is, its reasoning at what it was found to cost (the endpoint
        counts it as nothing); None if it cannot be."""
        async with self.session() as session:
            n = await self.ask(session, request, body)
        if not isinstance(n, int):
            return None
        known = self.channel(gatherer, channel).reasoning
        return n + sum(known.get(key_of(self.adaptor, i), 0) for i in body.get("input") or () if is_reasoning(i))

    def learn(self, gatherer: str, channel: str, context: Optional[list]) -> None:
        """What a context the server answered says reasoning costs: each counted reasoning event's size
        as stored, for one this process has not costed itself (started since, say)."""
        known = self.channel(gatherer, channel).reasoning
        for e in context or ():
            if isinstance(e, dict) and e.get("counted") and isinstance(e.get("id"), str) and e["id"] not in known \
                    and isinstance(e.get("payload"), dict) and is_reasoning(e["payload"]):
                known[e["id"]] = e.get("tokens") or 0

    # ------------------------------------------------------------------ once it is sent

    def sent(self, gatherer: str, channel: str, out: dict, sent: list, preamble: list) -> None:
        """Keep what the read `out` (call_ag's) sent -- its preamble parts, its items, each the event or
        ag item it is -- until the call's own count is back (`reported`)."""
        read_id = out.get("read_id")
        if not self.enabled or not isinstance(read_id, int):
            return
        ids = {e.get("id") for e in out.get("events") or () if isinstance(e, dict)}
        made = {}
        for made_id, text in out.get("ag_items") or ():
            item = ag_item(self.adaptor, text) if isinstance(text, str) else None
            if item is not None:
                made.setdefault(json.dumps(item, sort_keys=True), (made_id, text))
        keys, parts = [], []
        for item in sent:
            if not isinstance(item, dict):
                continue
            mine = made.get(json.dumps(item, sort_keys=True))
            if mine is not None:
                keys.append("made:" + hashlib.sha256(mine[1].encode("utf-8")).hexdigest())
                parts.append(("made", mine[0], item))
            else:
                iid = key_of(self.adaptor, item)
                keys.append(iid)
                parts.append(("event", iid if iid in ids else None, item))
        ch = self.channel(gatherer, channel)
        self.learn(gatherer, channel, out.get("context"))
        if ch.last is None and any(isinstance(e, dict) and e.get("counted") for e in out.get("context") or ()):
            ch.last = False                      # counted before this process: not differenced from nothing
        ch.sent[read_id] = Sent(out.get("basis"), [(p["name"], p["text"]) for p in preamble or ()], keys, parts)
        while len(ch.sent) > KEPT_SENT:          # a call whose count never came back
            ch.sent.pop(next(iter(ch.sent)))

    def start(self, request, client, gatherer: str, properties: dict, body: dict, items: list,
              sent: list, out: dict) -> None:
        """Count what the call holds that is not counted yet, in the background: `items` codex's own,
        `sent` what the model got, `out` call_ag's (its events, ag's items, its read_id)."""
        if not self.can_count(request, body):
            return
        read_id = out.get("read_id")
        from ag.integrations.tools.ag_orchestrator.adaptor import CHANNEL
        ch = self.channel(gatherer, properties.get(CHANNEL, ""))
        if isinstance(read_id, int):
            ch.exact[read_id] = asyncio.get_event_loop().create_future()
        task = asyncio.ensure_future(self.count_call(request, client, gatherer, properties, body, items, sent, out))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def count_call(self, request, client, gatherer, properties, body, items, sent, out) -> None:
        from ag.integrations.tools.ag_orchestrator.adaptor import CHANNEL
        ch = self.channel(gatherer, properties.get(CHANNEL, ""))
        exact = ch.exact.get(out.get("read_id"))
        async with ch.lock:
            try:
                async with self.session() as session:
                    counts = await self.counts(session, request, ch, body, items, sent, out, exact)
            except Exception as exc:  # noqa: BLE001 - a lost count never breaks the hook
                print(f"[{gatherer}] counting failed: {exc!r}", file=sys.stderr, flush=True)
                counts = None
            finally:
                if exact is not None and not exact.done():
                    exact.set_result(None)
            if counts and any(counts.values()):
                await client.request("counted", {"gatherer": gatherer, "properties": properties, **counts})
                self.log(gatherer, f"counted {len(counts['counts'])} events, {len(counts['made'])} of ag's items, "
                                   f"{len(counts['preamble_counts'])} preamble parts")

    async def counts(self, session, request, ch: Channel, body: dict, items: list, sent: list, out: dict,
                     exact=None) -> dict:
        found = {"counts": {}, "made": {}, "preamble_counts": []}
        base = {k: body[k] for k in COUNTED if k in body and k != "input"}
        whole = await self.ask(session, request, dict(base, input=sent))      # as sent: for the reasoning's count
        if exact is not None and not exact.done():
            exact.set_result(whole if isinstance(whole, int) else None)
        placeholder = await self.ask(session, request, dict(base, input=PLACEHOLDER))
        if not isinstance(placeholder, int):
            return found
        await self.preamble(session, request, ch, base, placeholder, found)
        ids = self.event_ids(items, out.get("events") or [])
        uncounted = set(out["uncounted"]) if isinstance(out.get("uncounted"), list) else None
        await self.steps(session, request, ch, base, placeholder, items, ids, uncounted, found)
        for made_id, text in out.get("ag_items") or ():
            if made_id in ch.made or not isinstance(text, str):
                continue
            sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if sha not in ch.texts:
                item = ag_item(self.adaptor, text)
                if item is None:
                    continue
                n = await self.ask(session, request, dict(base, input=PLACEHOLDER + [item]))
                if not isinstance(n, int):
                    continue
                ch.texts[sha] = max(n - placeholder, 0)
            found["made"][str(made_id)] = ch.texts[sha]
            ch.made.add(made_id)
        return found

    async def preamble(self, session, request, ch: Channel, base: dict, placeholder: int, found: dict) -> None:
        """The instructions' and the tools' counts, once per version (named as preamble_of names them)."""
        from ag.integrations.tools.ag_orchestrator.call_ag import preamble_of
        parts = {p["name"]: p["text"] for p in preamble_of({"instructions": base.get("instructions"),
                                                            "tools": base.get("tools")})}
        sha = hashlib.sha256(json.dumps(parts, sort_keys=True).encode("utf-8")).hexdigest()
        if not parts or sha in ch.preambles:
            return
        bare = await self.ask(session, request, {"model": base.get("model"), "input": PLACEHOLDER})
        instructions = await self.ask(session, request, {"model": base.get("model"), "instructions": base.get("instructions"),
                                                         "input": PLACEHOLDER}) if "instructions" in parts else bare
        if not (isinstance(bare, int) and isinstance(instructions, int)):
            return
        sizes = {"instructions": instructions - bare, "tools": placeholder - instructions}
        found["preamble_counts"] += [{"name": n, "text": t, "tokens": max(sizes.get(n, 0), 0)} for n, t in parts.items()]
        ch.preambles.add(sha)

    def event_ids(self, items: list, events: list) -> List[Optional[str]]:
        """For each of codex's items, the id of the event it is (None: none of this call's -- before
        codex's summary of a compacted history, say)."""
        ids = {e.get("id") for e in events if isinstance(e, dict)}
        return [k if k in ids else None for k in (key_of(self.adaptor, i) for i in items)]

    async def steps(self, session, request, ch: Channel, base: dict, placeholder: int, items: list,
                    ids: List[Optional[str]], uncounted: Optional[Set[str]], found: dict) -> None:
        """The new steps' counts (the module's doc): of this call's events the store has not counted
        (`uncounted`; None: not known, all of them), but those this process has."""
        def due(event) -> bool:
            return bool(event) and event not in ch.counting and (uncounted is None or event in uncounted)

        done, kinds = 0, [kind_of(self.adaptor, i) for i in items]
        for start, end in steps_of(items, kinds):
            if done >= STEPS_PER_CALL:
                return
            todo = [i for i in range(start, end) if not is_reasoning(items[i]) and due(ids[i])]
            if not todo:
                continue
            # reasoning is the reasoning count's: the step without it
            at = [i for i in range(start, end) if not is_reasoning(items[i])]
            step = [copy.deepcopy(items[i]) for i in at]
            costs = await self.split(session, request, base, placeholder, step, [kinds[i] for i in at])
            if costs is not None:
                costs = {at[k]: n for k, n in costs.items()}
            if costs is None:                       # not standalone: in the history, by size
                costs = await self.in_history(session, request, base, items, start, end)
            if costs is None:
                continue
            for i, n in costs.items():
                if due(ids[i]):
                    found["counts"][ids[i]] = max(n, 0)
                    ch.counting.add(ids[i])
            done += 1

    async def split(self, session, request, base: dict, placeholder: int, step: list, kinds: List[str]):
        """{index in the step: cost} of a step's items (of these event types), standalone; None if the
        endpoint will not take the step alone."""
        whole = await self.ask(session, request, dict(base, input=PLACEHOLDER + step))
        if not isinstance(whole, int):
            return None
        costs, rest = {}, []
        for k, item in enumerate(step):
            kind, n = kinds[k], None
            if kind == TOOL_OUTPUT:
                cut = copy.deepcopy(step)
                cut[k]["output"] = "x"
                c = await self.ask(session, request, dict(base, input=PLACEHOLDER + cut))
                n = whole - c + 1 if isinstance(c, int) else None      # beside a one-word output
            elif kind != TOOL_CALL:                                    # a message, or anything else: taken out
                cut = [x for j, x in enumerate(step) if j != k]
                c = await self.ask(session, request, dict(base, input=PLACEHOLDER + cut)) if cut else placeholder
                n = whole - c if isinstance(c, int) else None
            if n is None:
                rest.append(k)
            else:
                costs[k] = n
        left = whole - placeholder - sum(costs.values())
        if rest:                                    # tool calls: what is left, shared
            for j, k in enumerate(rest):
                costs[k] = left // len(rest) + (1 if j < left % len(rest) else 0)
        elif costs:                                 # the step's framing, on its last item
            last = list(costs)[-1]
            costs[last] += left
        return costs

    async def in_history(self, session, request, base: dict, items: list, start: int, end: int):
        """{item index: cost} of a step counted where it is -- the history to its end less the history
        before it -- shared by the size of each item but reasoning; None if refused."""
        before = await self.ask(session, request, dict(base, input=items[:start])) if start else 0
        upto = await self.ask(session, request, dict(base, input=items[:end]))
        if not (isinstance(before, int) and isinstance(upto, int)):
            return None
        sizes = {i: len(json.dumps(items[i])) for i in range(start, end) if not is_reasoning(items[i])}
        total, whole = sum(sizes.values()) or 1, upto - before
        return {i: whole * s // total for i, s in sizes.items()}

    # ------------------------------------------------------------------ once its own count is back

    def reported(self, request, client, gatherer: str, channel: str, read_id: int, tokens: Optional[int],
                 body: dict) -> None:
        """The call's own count of read `read_id` is back: what it tells, counted in the background --
        the reasoning's cost, where the endpoint counted the call; else every new item's, by
        difference with the call before."""
        if not self.enabled or not isinstance(tokens, int) or tokens <= 0:
            return
        task = asyncio.ensure_future(self.count_reported(request, client, gatherer, channel, read_id, tokens, body))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def count_reported(self, request, client, gatherer, channel, read_id, tokens, body) -> None:
        from ag.integrations.tools.ag_orchestrator.adaptor import CHANNEL
        ch = self.channel(gatherer, channel)
        exact = ch.exact.pop(read_id, None)
        try:
            n = await asyncio.wait_for(asyncio.shield(exact), REPORT_SECONDS) if exact is not None else None
        except (asyncio.TimeoutError, asyncio.CancelledError):
            n = None
        async with ch.lock:
            sent = ch.sent.pop(read_id, None)
            try:
                if exact is not None:
                    counts = self.reasoning_counts(ch, sent, tokens, n)
                elif not self.can_count(request, body):
                    counts = self.differenced(ch, sent, tokens)
                else:
                    counts = {}
            except Exception as exc:  # noqa: BLE001 - a lost count never breaks the hook
                print(f"[{gatherer}] counting by the call's own count failed: {exc!r}", file=sys.stderr, flush=True)
                return
            if sent is not None:
                ch.last = (sent, tokens)
            if counts.get("counts") or counts.get("made") or counts.get("preamble_counts"):
                await client.request("counted", {"gatherer": gatherer, "properties": {CHANNEL: channel},
                                                 "counts": counts.get("counts", {}), "made": counts.get("made", {}),
                                                 "preamble_counts": counts.get("preamble_counts", [])})
                self.log(gatherer, f"[{channel}] counted {len(counts.get('counts', {}))} events, "
                                   f"{len(counts.get('made', {}))} of ag's items by the call's own count")

    @staticmethod
    def reasoning_counts(ch: Channel, sent: Optional[Sent], tokens: int, exact: Optional[int]) -> dict:
        """The cost of the reasoning new in a call: what its own count is over the endpoint's count of it
        as sent, less the reasoning it sent that is costed already -- shared evenly among the new."""
        if sent is None or not isinstance(exact, int):
            return {}
        reasoning = [(k, at) for k, (kind, at, item) in zip(sent.keys, sent.parts) if kind == "event" and is_reasoning(item)]
        new = [(k, at) for k, at in reasoning if k not in ch.reasoning]
        if not new:
            return {}
        rise = max(tokens - exact - sum(ch.reasoning[k] for k, _ in reasoning if k in ch.reasoning), 0)
        counts = {}
        for j, (k, at) in enumerate(new):
            ch.reasoning[k] = rise // len(new) + (1 if j < rise % len(new) else 0)
            if at:
                counts[at] = ch.reasoning[k]
                ch.counting.add(at)
        return {"counts": counts}

    def differenced(self, ch: Channel, sent: Optional[Sent], tokens: int) -> dict:
        """Every item new in a call since the last one counted so -- the same build and preamble, its
        context that one's with items added -- at what the two calls' own counts differ by, shared by
        ag's counts (`weight_of`). A channel's first is so from nothing: its preamble parts too."""
        if sent is None or ch.last is False:          # False: counted before this process, from no count of its
            return {}
        first = ch.last is None
        before, base = (Sent(sent.basis, sent.preamble, [], []), 0) if first else ch.last
        if before.basis != sent.basis or before.preamble != sent.preamble or sent.keys[:len(before.keys)] != before.keys:
            return {}                                    # a build, or something taken out: not by difference
        new = [("item", k, part) for k, part in zip(sent.keys[len(before.keys):], sent.parts[len(before.keys):])]
        if first:
            new = [("preamble", name, text) for name, text in sent.preamble] + new
        rise = tokens - base
        if not new or rise <= 0:
            return {}
        weights = [len(x[2]) if x[0] == "preamble" else self.part_weight(x[2]) for x in new]
        total = sum(weights)
        shares = [rise * w // total for w in weights] if total else [rise // len(new)] * len(new)
        shares[-1] += rise - sum(shares)                 # what rounding left, on the last
        counts, made, preamble = {}, {}, []
        for (what, key, part), share in zip(new, shares):
            if what == "preamble":
                preamble.append({"name": key, "text": part, "tokens": share})
                continue
            kind, at, item = part
            if kind == "event" and at:
                counts[at] = share
                ch.counting.add(at)
                if is_reasoning(item):
                    ch.reasoning[key] = share
            elif kind == "made" and isinstance(at, int):
                made[str(at)] = share
        return {"counts": counts, "made": made, "preamble_counts": preamble}

    def part_weight(self, part: tuple) -> int:
        """A sent item's share of a differenced count: an ag item's text's length, else `weight_of`'s."""
        kind, _, item = part
        if kind == "made":
            content = item.get("content") if isinstance(item.get("content"), list) else []
            return sum(len(c.get("text") or "") for c in content if isinstance(c, dict))
        return weight_of(self.adaptor, item)

    async def close(self) -> None:
        """Let counts still being taken finish (briefly)."""
        if self.tasks:
            await asyncio.wait(list(self.tasks), timeout=COUNT_SECONDS * 2)
