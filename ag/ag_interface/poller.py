"""A source of events from outside the conversation, asked at read time.

The agent's own activity reaches the manager through `insert`, item by item,
from a harness that sees the conversation. Some events happen elsewhere: a
file changed on disk, a build finished, a message arrived on another
channel. A POLLER is how those get in. The manager asks each of its pollers,
when it reads, for what happened since it last asked -- it keeps that moment
itself, per gatherer and per poller -- and stores what they return before
the policy builds the context.
"""

from abc import ABC, abstractmethod
from typing import List, Optional

from .event import Event, EventType


class Poller(ABC):
    """One source of events outside the conversation."""

    #: Identifies the source: the manager keeps one "last asked" mark per name.
    name: str = ""

    #: Which poller of the gatherer's it is, given by whoever builds it (the home:
    #: its catalog name, `file_changes`); "" = not given, its `name` stands in.
    #: A poller may put it on its events, as a property it declares.
    id: str = ""

    #: The names of the event properties it sets on its events (e.g. its id,
    #: as "poller"), and nothing else: an event carrying another is dropped,
    #: and ag refuses to run a policy whose types for `outputs` do not declare
    #: them all.
    properties: tuple = ()

    #: The names of the event types it outputs (e.g. "environment_update"), and
    #: nothing else. Required: a poller that declares none is refused, an event
    #: it returns of another type is dropped, and ag refuses to run a policy
    #: whose event types do not take them all.
    outputs: tuple = ()

    @abstractmethod
    def poll(self, since: Optional[float], types: List[EventType]) -> List[Event]:
        """The events that occurred after `since`, oldest first.

        Args:
            since: seconds since the epoch: when this poller was last asked
                for this gatherer. None the first time: there is no earlier
                moment to compare with, and the poller decides what that
                means -- nothing (start watching from now), or what came
                before (a channel's backlog).
            types: the gatherer's event types, with their ids (`EventType.id`).
                An event returned must be typed by one of them; a poller whose
                type the gatherer does not have returns nothing, since the
                gatherer's policy did not ask for it.

        Returns:
            Events with `type_id` set from `types`, and an `id` that makes the
            same occurrence, if seen again, a duplicate.
        """
