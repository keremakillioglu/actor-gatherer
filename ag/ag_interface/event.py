r"""What a context manager is given: events, each of a registered type.

Everything the Gatherer stores is an **event**: a user message, the model's answer, a tool
call, a tool's output, a file change. An event carries an opaque JSON *payload*, which the
Gatherer stores and returns exactly as given, and has an *event type*. It may also carry an
*id* (so a re-sent event is stored once), a *text* (what the policy reads of it, without the
harness's metadata), and a token cost.

Event types are the contract between the three extension points. A policy declares the
types it accepts (`Policy.event_types`); an adaptor and a poller each declare the types
they output. `ag` refuses to run when an output is not among the policy's types.

An event type also declares **properties**: named values its events carry beside the
payload, each required or not, and identifying or not. The store keeps one column per
property, refuses an event that lacks a required one or carries one its type does not
declare, and filters by them when a policy asks. An event is known by its id together
with its *identifying* properties: one with the same id and the same identifying
properties as a stored one is that event, re-sent, and is not stored again -- whatever its
other properties say (the stored event keeps the values it came with). A property is
identifying in a gatherer when any of its types declares it so. Three are in use:

- `channel` (identifying): the session an event belongs to. The harness side sets it on
  every event and on every read. An event without a channel (such as a poller's) is visible
  from every channel. The same id in two channels is two events.
- `cwd`: the agent's working directory, set from the request, and by the file poller to the
  directory it watched. It describes where an event happened: a session whose directory
  changes re-sends its history under the new one, and that history is not stored again.
- `poller`: which of the gatherer's pollers an event came from (its name in the catalog).

Adaptors and pollers declare which properties they set, and `ag` also checks those against
the policy's event types.
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
        identifies: part of what makes an event the same event, with its id (see the
            module's docstring); a property that only describes an event does not.
    """
    name: str
    required: bool = False
    identifies: bool = False


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
            with the same id and the same identifying properties are the same
            event (`Property.identifies`).
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
