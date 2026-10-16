"""For the tests: a Manager fed codex items, the way the server feeds it.

The policies' tests drive a policy with codex-shaped items. The harness side
turns them into events (`ag/integrations/harnesses/codex/adaptor/to_events.py`), and the server resolves
each event's type name to the gatherer's id -- adding a type the gatherer does
not have -- before `Manager.insert` (ag/ag_harness/server). `CodexItems`
does both, so a test can insert codex items into a real Manager:

    m = CodexItems(Manager(ProactiveContextManager(FORMAT, llm, cfg)))
    m.init("s"); m.insert("s", item, channel_id=None); m.read("s", row, channel_id=None)

`text(item)` is what a reader of a returned item sees: an `ag` message's
text, or a codex item's content -- for the tests' assertions. (What the
policies themselves see of an event is the text the adaptor gave it, else its
payload as JSON: store.text.)
"""

import json
import os
import sys
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ag.ag_interface import FORMAT, Event, EventType  # noqa: E402,F401 - FORMAT for the tests
from ag.integrations.harnesses.codex.adaptor import to_events as codex_format  # noqa: E402
from ag.ag_policies.tools.channel import CHANNEL_PROPERTY  # noqa: E402
from channels import ch, on  # noqa: E402

item_id = codex_format.item_id
classify = codex_format.classify


def text(item) -> str:
    """What a reader of `item` sees: an `ag` message's text; a message's text
    parts (a reasoning item's summary); a call's name and arguments; an
    output; "" for anything else."""
    if not isinstance(item, dict):
        return ""
    if item.get("type") == "ag":
        return str(item.get("text") or "")
    kind = item.get("type")
    if kind in ("function_call", "custom_tool_call"):
        return f"{item.get('name', '')} {item.get('arguments', item.get('input', ''))}".strip()
    if kind in ("function_call_output", "custom_tool_call_output", "tool_search_output"):
        output = item.get("output")
        return output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
    parts = item.get("content")
    if parts is None and kind == "reasoning":
        parts = item.get("summary")
    if isinstance(parts, str):
        return parts
    return "\n".join(p["text"] for p in parts or []
                     if isinstance(p, dict) and isinstance(p.get("text"), str) and p["text"])


class CodexItems:
    """A Manager, fed codex items (or Events, as they are)."""

    def __init__(self, inner):
        self.inner = inner
        self.name = f"codex-{inner.name}"
        self._ids: Dict[str, Dict[str, int]] = {}

    def init(self, gatherer_id: str, event_types=()) -> None:
        self.inner.init(gatherer_id, list(event_types))
        self._ids.pop(gatherer_id, None)

    def type_id(self, gatherer_id: str, name: str) -> int:
        ids = self._ids.get(gatherer_id)
        if ids is None or name not in ids:
            ids = self._ids[gatherer_id] = {t.name: t.id for t in self.inner.event_types(gatherer_id)}
        if name not in ids:
            ids[name] = self.inner.add_event_type(gatherer_id, EventType(name, None, (CHANNEL_PROPERTY,)))
        return ids[name]

    def event(self, gatherer_id: str, item) -> Event:
        e = codex_format.event(item)
        return Event(self.type_id(gatherer_id, e["type"]), e["payload"], id=e["id"], tokens=e.get("tokens"),
                     text=e.get("text"))

    def insert(self, gatherer_id: str, item, *, channel_id: Optional[str]) -> Optional[int]:
        return self.inner.insert(gatherer_id, on(item if isinstance(item, Event) else self.event(gatherer_id, item),
                                             channel_id))

    def bulk_load(self, gatherer_id: str, items, *, channel_id: Optional[str]):
        return self.inner.bulk_load(gatherer_id, [i if isinstance(i, Event) else self.event(gatherer_id, i)
                                                 for i in items], properties=ch(channel_id))

    def locate(self, gatherer_id: str, item, *, channel_id: Optional[str]) -> Optional[int]:
        event_id = item.id if isinstance(item, Event) else item if isinstance(item, str) else item_id(item)
        return self.inner.locate(gatherer_id, event_id, properties=ch(channel_id))

    def read(self, gatherer_id: str, row_id: int, *, channel_id: Optional[str]) -> list:
        return self.inner.read(gatherer_id, row_id, properties=ch(channel_id))

    def event_types(self, gatherer_id: str) -> List[EventType]:
        return self.inner.event_types(gatherer_id)

    def add_event_type(self, gatherer_id: str, event_type: EventType) -> int:
        type_id = self.inner.add_event_type(gatherer_id, event_type)
        self._ids.setdefault(gatherer_id, {})[event_type.name] = type_id
        return type_id

    def __getattr__(self, name):                       # add_poller, set_pollers, poll, last_inserted_at, ...
        return getattr(self.inner, name)
