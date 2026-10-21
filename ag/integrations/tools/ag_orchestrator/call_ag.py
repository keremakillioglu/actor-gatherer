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
its `outputs`, or a property not in its `properties`, sends nothing (None), and a context
entry not in its `accepts` is noted. The working directory, when given, goes on the events
and the read as the property CWD too. An adaptor that fails, a server that errors or does
not answer, or a context that is not a list each give None and a note.

For a proxy-based harness, ag/integrations/tools/hook_server/hook_server.py is the proxy: it
calls a given hook on every request to the model's endpoint, and relays everything else
unchanged. A URL that starts with `/h/<label>/` hands the hook that label, which the shipped
hooks use as the gatherer.
"""

from typing import Any, Dict, Optional, Tuple

from .adaptor import CWD, Adaptor


async def call_ag(client, gatherer: str, properties: Dict[str, Any], cwd: Optional[str], messages: list,
                  adaptor: Adaptor, out: Optional[dict] = None,
                  measured: Optional[dict] = None, limit: Optional[int] = None) -> Tuple[Optional[list], str]:
    """(the messages the model gets, or None to send the harness's own; a
    note): the adaptor's `to_events`, a `rewrite` to the server, its `to_messages`.
    `out`, when given, gets the read's `read_id` (what the provider's count of
    this call is reported against, `measured`); `measured`, {"read_id",
    "tokens"}, is an earlier call's count, sent with this one; `limit` the
    harness's own limit for this call (where it compacts, or its window ends)."""
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
    body = {"gatherer": gatherer, "properties": properties, "cwd": cwd, "events": events}
    if measured is not None:
        body["measured"] = measured
    if limit:
        body["limit"] = limit
    answer = await client.request("rewrite", body)
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
    if out is not None and isinstance(answer.get("read_id"), int):
        out["read_id"] = answer["read_id"]                # the read's context is what is sent
    return routed, note


READ = "ag_read"      # a proxy hook's key in the hook server's `request.state`: (gatherer, read_id)


def keep_read(request, gatherer: str, out: dict) -> None:
    """For a proxy hook: keep the read this request's context came from (`call_ag`'s `out`)
    on the request, for `report_measured` once the answer is back."""
    state = getattr(request, "state", None)
    if isinstance(state, dict) and isinstance(out.get("read_id"), int):
        state[READ] = (gatherer, out["read_id"])


async def report_measured(ag_clients, request, tokens: Optional[int]) -> None:
    """For a proxy hook's `measured`: the provider's count of the request's context, to the
    read it came from (`keep_read`). Nothing when either is unknown."""
    kept = (getattr(request, "state", None) or {}).get(READ)
    if kept is None or not tokens:
        return
    gatherer, read_id = kept
    await ag_clients.client(gatherer).request("measured", {"gatherer": gatherer, "read_id": read_id,
                                                           "tokens": tokens})
