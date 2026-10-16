"""What a context manager is given: events, each of a registered type.

Everything that reaches a context manager is an EVENT: a message from the
user, the model's answer, a tool call, a tool's output, an instruction, a
notice from the harness. An event carries an opaque JSON PAYLOAD (the item as
the agent sees it) and points at an EVENT TYPE by id.

Event types are a contract between a policy and the harness that feeds it.
A POLICY defines the types it expects (`Policy.event_types`: name, properties),
and they are registered when a gatherer is created. The HARNESS side agrees
to insert events of those types -- it maps its agent's items onto the names
(`integrations/harnesses/<harness>/adaptor/`). A caller can define more types at any time
(`add_event_type`) and list them with their ids (`event_types`). Every event
inserted names its type by that id; an unknown id is refused.

A type is known by its NAME: what a policy does with its events is the
policy's, which groups the names it knows (ag/ag_policies/tools/groups.py) and
ignores any other. The names, like the types, are the policies' (each
policy's events.py) and the pollers', not this contract's.

An event may carry its TEXT beside its payload: what a reader of the history
needs of it -- a message's words, a tool call's name and arguments, a tool's
output -- without the harness's bookkeeping (ids, metadata, wrappers). The
harness side gives it, since only it knows its agent's items; wherever a policy
renders or counts an event it uses the text, and the payload as JSON when there
is none. The payload is still what goes back to the agent, as it was given.

A type also lists its PROPERTIES: the named values an event of the type may
carry beside its payload (e.g. a policy's `channel`), each required or not.
What a property means is the policy's; the harness only stores it, one column
per property any registered type declares, refuses an event that lacks a
required one or carries one its type does not declare, and filters by them
when a policy asks (`GathererStore.rows`). An event without a value for a
property has it unset.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

#: What a property's name may be: it names a column (`p_<name>`).
PROPERTY_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class Property:
    """A named value events of a type may carry.

    Attributes:
        name: letters, digits and `_`, not starting with a digit.
        required: an event of the type must carry it (a value, not None).
    """
    name: str
    required: bool = False


@dataclass(frozen=True)
class EventType:
    """A kind of event, known by its name; once registered, by its id too.

    Attributes:
        name: what identifies the type within a gatherer: registering a name
            twice is the same type. Any non-empty string; the harness side
            normally derives it from the agent's item.
        properties: the `Property`s its events may carry; none by default.
        id: the gatherer's id for the type, set on the types `event_types`
            returns and by `add_event_type`; None on a definition not yet
            registered. Not part of equality: a definition equals the
            registered type it became.
    """
    name: str
    properties: Tuple[Property, ...] = ()
    id: Optional[int] = field(default=None, compare=False)


@dataclass
class Event:
    """One thing that happened, as the agent saw it.

    Attributes:
        type_id: the id of its event type in the gatherer (`EventType.id`).
        payload: the item itself, opaque and JSON-serializable. Stored and
            returned by `read` exactly as given.
        id: the caller's stable id for the event, if it has one. Two events
            with the same id and the same properties are the same event.
            None: every insert is a new event, known only by the row id
            `insert` returns.
        tokens: what the event costs in the model's context, if the caller
            knows better than a tokenizer would (e.g. an opaque blob). None:
            the implementation counts its text -- or, without one, its
            payload as JSON.
        properties: its properties' values, by name: each one its type
            declares (`EventType.properties`), a string or a number. A
            property left out, or None, is unset.
        text: its readable text, if the caller gives one: what a policy
            shows and counts of it. None: its payload as JSON.
    """
    type_id: int
    payload: Any
    id: Optional[str] = None
    tokens: Optional[int] = None
    properties: Dict[str, Any] = field(default_factory=dict)
    text: Optional[str] = None
