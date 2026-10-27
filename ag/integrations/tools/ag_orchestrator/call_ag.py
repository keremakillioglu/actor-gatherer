r"""One model call, for a hook in Python (call_ag.ts is the same in TypeScript): the harness's
messages through its adaptor and the Gatherer's server, and back.

The hook works out where the call belongs: the gatherer, the channel (the harness's session
id) and the working directory. It then runs one call through `call_ag`, which never raises:

```python
from ag.integrations.tools.ag_connection.ag_client import AgClient
from ag.integrations.tools.ag_orchestrator.adaptor import CHANNEL
from ag.integrations.tools.ag_orchestrator.call_ag import call_ag

client = AgClient("mine")                  # starts the Gatherer's server on first use
messages, note = await call_ag(client, gatherer, {CHANNEL: session_id}, cwd, harness_messages, MyAdaptor())
send(messages if messages is not None else harness_messages)   # None: the Gatherer could not answer
```

`call_ag` runs `to_events`, sends the events to the Gatherer, and runs `to_messages` on the
context it returns. In TypeScript, `call_ag(server, {gatherer, properties, cwd}, messages,
adaptor)` does the same. It holds the adaptor to what it declares: an event of a type not in
its `outputs`, a property of the request not in its `properties`, or one an event carries of its
own not in its `event_properties`, sends nothing (None), and a context entry not in its
`accepts` is noted. The working directory, when given, goes on the events
and the read as the property CWD too. An adaptor that fails, a server that errors or does
not answer, or a context that is not a list each give None and a note.

For a proxy-based harness, ag/integrations/tools/hook_server/hook_server.py is the proxy: it
calls a given hook on every request to the model's endpoint, and relays everything else
unchanged. A URL that starts with `/h/<label>/` hands the hook that label, which the shipped
hooks use as the gatherer.
"""

import json
from typing import Any, Dict, List, Optional, Tuple

from .adaptor import CWD, Adaptor


async def call_ag(client, gatherer: str, properties: Dict[str, Any], cwd: Optional[str], messages: list,
                  adaptor: Adaptor, out: Optional[dict] = None,
                  measured: Optional[dict] = None, limit: Optional[int] = None,
                  preamble: Optional[list] = None, op: str = "rewrite",
                  process: Optional[dict] = None, run: Optional[str] = None) -> Tuple[Optional[list], str]:
    """(the messages the model gets, or None to send the harness's own; a
    note): the adaptor's `to_events`, a `rewrite` to the server, its `to_messages`.
    `out`, when given, gets the read's `read_id` (what the provider's count of
    this call is reported against, `measured`), and its `tokens`, `budget` and
    `sent_tokens` by the policy's count and its `basis` (the server's `rewrite`), the `context`
    as answered (its stored events with their sizes as stored), the ids of the events given the
    provider has not counted yet (`uncounted`; None: not known), the
    `events` sent, and the context manager's own items as [(made_id, text)] (`ag_items`);
    `measured`, {"read_id",
    "tokens"}, is an earlier call's count, sent with this one; `limit` the
    harness's own limit for this call (where it compacts, or its window ends); `preamble`,
    [{"name", "text"}], what the harness sends besides its messages (its system prompt,
    its tool definitions), kept with the read; `process`, {"pid", "started"}, the harness's process
    that made the call, kept with it too (so a reader can tell whether the session still runs), as is `run`, the
    harness's run that made it, as its launcher named it (`request.run`). `op` "context" asks for the context read only
    (the server's `context`: the events inserted, nothing else of the gatherer changed, no read)."""
    if cwd:
        properties = {**properties, CWD: cwd}                     # where the agent works
    unset = sorted(set(properties) - set(adaptor.properties))
    if unset:
        return None, (f"adaptor {adaptor.name} does not declare the properties {', '.join(unset)}; "
                      f"request unchanged")
    try:
        events = adaptor.to_events(messages)
    except Exception as exc:  # noqa: BLE001 - never block the model call
        return None, f"could not make events: {exc!r}; request unchanged"
    undeclared = sorted({str(e.get("type")) for e in events if isinstance(e, dict)} - set(adaptor.outputs))
    if undeclared:
        return None, (f"adaptor {adaptor.name} made events of types it does not declare "
                      f"({', '.join(undeclared)}); request unchanged")
    own = sorted({k for e in events if isinstance(e, dict) and isinstance(e.get("properties"), dict)
                  for k in e["properties"]} - set(getattr(adaptor, "event_properties", ())))
    if own:
        return None, (f"adaptor {adaptor.name} set properties on its events it does not declare "
                      f"({', '.join(own)}); request unchanged")
    body = {"gatherer": gatherer, "properties": properties, "cwd": cwd, "events": events}
    if measured is not None:
        body["measured"] = measured
    if limit:
        body["limit"] = limit
    if preamble:
        body["preamble"] = preamble
    if process:
        body["process"] = process
    if run:
        body["run"] = run
    answer = await client.request(op, body)
    if not isinstance(answer, dict) or answer.get("error"):
        why = answer.get("error") if isinstance(answer, dict) else repr(answer)
        return None, f"server: {why}; request unchanged"
    context = answer.get("context")
    if not isinstance(context, list):
        return None, str(answer.get("note") or "no context; request unchanged")
    note = str(answer.get("note") or "")
    unaccepted = sorted({str(e.get("type")) for e in context if isinstance(e, dict)} - set(adaptor.accepts))
    if unaccepted:
        note += f"; adaptor {adaptor.name} does not accept {', '.join(unaccepted)}"
    try:
        routed = adaptor.to_messages(context, messages)
    except Exception as exc:  # noqa: BLE001
        return None, f"could not make messages: {exc!r}; request unchanged"
    if out is not None:                                   # a read-only context's too, but its read_id
        out["basis"], out["context"] = answer.get("basis"), context
        out["uncounted"] = answer.get("uncounted") if isinstance(answer.get("uncounted"), list) else None
        out["inserted"] = [r for r in answer.get("inserted") or [] if isinstance(r, int)]     # the rows it stored
        out.update({k: answer[k] for k in ("tokens", "budget", "sent_tokens") if isinstance(answer.get(k), int)})
    if out is not None and isinstance(answer.get("read_id"), int):
        out["read_id"] = answer["read_id"]                # the read's context is what is sent
        out["events"] = events
        out["ag_items"] = [(e.get("made_id"), e.get("text")) for e in context
                           if isinstance(e, dict) and e.get("type") == "ag" and isinstance(e.get("made_id"), int)]
    return routed, note


READ = "ag_read"      # a proxy hook's key in the hook server's `request.state`: (gatherer, read_id)
STORED = "ag_stored"  # and (gatherer, properties, the rows the call stored), for `report_withdrawn`
#: The hook server's status for a call the harness hung up on before its answer was through (hook_server.HUNG_UP).
HUNG_UP = 499


def preamble_of(parts) -> list:
    """[{"name", "text"}] from a request's parts besides its messages, {name: value}: a string
    as it is, a list of text blocks (Anthropic's `system`) joined, anything else (`tools`) as
    JSON with sorted keys -- the same definitions give the same text, stored once."""
    out = []
    for name, value in parts.items():
        if isinstance(value, str):
            text = value
        elif isinstance(value, list) and value and all(isinstance(b, dict) and isinstance(b.get("text"), str) for b in value):
            text = "\n\n".join(b["text"] for b in value)
        elif value:
            text = json.dumps(value, sort_keys=True, ensure_ascii=False)
        else:
            text = ""
        if text.strip():
            out.append({"name": name, "text": text})
    return out


def keep_read(request, gatherer: str, out: dict) -> None:
    """For a proxy hook: keep the read this request's context came from (`call_ag`'s `out`)
    on the request, for `report_measured` once the answer is back (and `read_of`)."""
    state = getattr(request, "state", None)
    if isinstance(state, dict) and isinstance(out.get("read_id"), int):
        state[READ] = (gatherer, out["read_id"])


def read_of(request) -> Optional[int]:
    """The read this request's context came from (`keep_read`); None when not known."""
    kept = (getattr(request, "state", None) or {}).get(READ)
    return kept[1] if kept else None


async def report_measured(ag_clients, request, tokens: Optional[int]) -> None:
    """For a proxy hook's `measured`: the provider's count of the request's context, to the
    read it came from (`keep_read`). Nothing when either is unknown."""
    kept = (getattr(request, "state", None) or {}).get(READ)
    if kept is None or not tokens:
        return
    gatherer, read_id = kept
    await ag_clients.client(gatherer).request("measured", {"gatherer": gatherer, "read_id": read_id,
                                                           "tokens": tokens})


def keep_stored(request, gatherer: str, properties: Dict[str, Any], rows: List[int]) -> None:
    """For a proxy hook: keep the rows of the events this request's call stored (`call_ag`'s `inserted`, of each
    read it made), for `report_withdrawn` should the harness hang up on it."""
    state = getattr(request, "state", None)
    if isinstance(state, dict) and rows:
        state[STORED] = (gatherer, dict(properties), list(rows))


async def report_withdrawn(ag_clients, request) -> None:
    """For a proxy hook whose harness took back what it sent when it hung up on the call (`failed` with HUNG_UP):
    the events the call stored (`keep_stored`) withdrawn -- in no read until the harness sends one again. With the
    call's properties, so the server takes it in the channel's order. Nothing when none were stored."""
    state = getattr(request, "state", None) or {}
    kept = state.get(STORED)
    if kept is None:
        return
    gatherer, properties, rows = kept
    body = {"gatherer": gatherer, "properties": properties, "rows": rows}
    if state.get(READ):
        body["read_id"] = state[READ][1]
    await ag_clients.client(gatherer).request("withdraw", body)
