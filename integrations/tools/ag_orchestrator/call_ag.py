"""One model call, for a harness whose hook is in Python:
the harness's messages through its adaptor and the context manager's
server, and back. Routing only -- it never looks inside a message: turning
messages into events and the context back into messages is the harness's
adaptor's (adaptor.py); where the call belongs (gatherer, the properties of its
events -- e.g. {CHANNEL: thread} -- working directory) is its routing's.

    messages, note = await call_ag(client, gatherer, {CHANNEL: thread}, cwd, items, adaptor)
    messages or items               # None: send the harness's own

It holds the adaptor to what it declares: an event of a type not in its
`outputs`, or a property not in its `properties`, sends nothing (None), and
a context entry not in its `accepts` is noted. The working directory, when
given, goes on the events and the read as the property CWD too. It never
raises: an adaptor that fails, a server that errors or does not answer, a
context that is not a list -- each gives None and a note. call_ag.ts is the
same in TypeScript.
"""

from typing import Any, Dict, Optional, Tuple

from .adaptor import CWD, Adaptor


async def call_ag(client, gatherer: str, properties: Dict[str, Any], cwd: Optional[str], messages: list,
                  adaptor: Adaptor) -> Tuple[Optional[list], str]:
    """(the messages the model gets, or None to send the harness's own; a
    note): the adaptor's `to_events`, a `rewrite` to the server, its `to_messages`."""
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
    answer = await client.request("rewrite", {"gatherer": gatherer, "properties": properties, "cwd": cwd,
                                              "events": events})
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
        return adaptor.to_messages(context, messages), note
    except Exception as exc:  # noqa: BLE001
        return None, f"could not make messages: {exc!r}; request unchanged"
