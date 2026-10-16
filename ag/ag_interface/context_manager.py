"""The contract every context manager implements.

A context manager decides what an agent's context holds. It is given every
event as the agent sees it (`insert`) and asked, before each model call, what
the context should be in response to the event that just occurred (`read`).
How events are kept and how a context is built from them is the
implementation's; what is fixed is the interface, so a caller (e.g. a
harness's hook) can switch implementations without changing anything else.

Events are `event.Event`s: an opaque JSON payload pointing, by id, at one of
the gatherer's `EventType`s. The types are the caller's: defined when the
gatherer is created (`init`), added to later (`add_event_type`), listed with
their ids (`event_types`). What an implementation needs to know about an
event is on its type: its name, and the properties its events carry. Its
text is its payload as JSON.

Each stored event has a ROW ID, the int `insert` returns for it (and `locate`
finds again for a re-sent one). A `read` names the event it responds to by
that id.
"""

from abc import ABC, abstractmethod
from typing import Iterable, List, Optional

from .event import Event, EventType


class ContextManager(ABC):
    """One way of keeping and building an agent's context.

    Subclasses must implement `insert`, `locate`, `read`, `add_event_type`
    and `event_types`. `init` defaults to doing nothing; an implementation
    with storage to create overrides it, and registers the types it is given.
    """

    #: The implementation's name (the manager's: its policy's).
    name: str = ""

    def init(self, gatherer_id: str, event_types: Iterable[EventType] = ()) -> None:
        """Create the gatherer's storage and define its event types.
        Idempotent: an existing gatherer is opened, not recreated, so a
        resumed gatherer keeps its history; a type already defined (same
        name) keeps its id and what it was first defined with.

        Args:
            gatherer_id: the gatherer to create.
            event_types: the types the gatherer's events may have, in the
                order to give them ids. More can be added later with
                `add_event_type`.
        """

    @abstractmethod
    def add_event_type(self, gatherer_id: str, event_type: EventType) -> int:
        """Define one more event type for the gatherer, and return its id. A
        name already defined returns the existing id; nothing about it
        changes.

        Args:
            gatherer_id: the gatherer, as passed to `init`.
            event_type: the type: its name and its properties.
        """

    @abstractmethod
    def insert(self, gatherer_id: str, event: Event) -> Optional[int]:
        """Record one event. Returns its row id, or None if it was already
        recorded (`locate` finds the row id it has).

        Must be safe to call again with an event id already recorded with
        the same properties: a caller that sees the whole conversation on
        every model call inserts every event every time.

        Args:
            gatherer_id: the gatherer the event belongs to, as passed to `init`.
            event: the event: the id of one of the gatherer's types, its
                payload (opaque, JSON-serializable), its id if the caller has
                one, its cost if the caller knows it, and its properties --
                each one its type declares; an unset property is visible to
                a read with any value of it.

        Raises:
            LookupError: the gatherer has no event type with that id.
            ValueError: the event lacks a property its type requires, or
                carries one its type does not declare.
        """

    @abstractmethod
    def locate(self, gatherer_id: str, event_id: str, *, properties: Optional[dict] = None) -> Optional[int]:
        """The row id of the event with this `Event.id`, as a read with
        `properties` sees it -- with those properties, or with them unset --
        or None if it has none. This is how a caller gets the row id of an
        event `insert` reported as already recorded.

        Args:
            gatherer_id: the gatherer, as passed to `init`.
            event_id: the caller's id for the event (`Event.id`).
            properties: the properties looking, as for `read`.
        """

    @abstractmethod
    def read(self, gatherer_id: str, row_id: int, *, properties: Optional[dict] = None) -> list:
        """The context to send on the next model call of the events with
        `properties`, in response to the event `row_id`.

        Built from what was inserted, not from anything the caller holds.
        What the policy makes of the properties is its own: e.g. a policy
        whose events have a `channel` returns the channel's own events and
        the ones with no channel as they were inserted, and other channels
        only as text inside items it makes itself.

        Args:
            gatherer_id: the gatherer to read, as passed to `init`.
            row_id: the event this read responds to: the row id `insert`
                returned (or `locate` found) for it -- normally the last
                event inserted before the model call. An implementation may
                let it steer what the context is; at the least it is recorded
                with the read.
            properties: the read's properties, by name; one not given is
                unset.

        Returns:
            A list of payloads, each as it was given to `insert` -- what goes
            to the model.
        """

    @abstractmethod
    def event_types(self, gatherer_id: str) -> List[EventType]:
        """Every event type the gatherer has, in the order defined, each with
        its `id`. A gatherer with no storage has none.

        Args:
            gatherer_id: the gatherer, as passed to `init`.
        """
