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
    r"""One source of events outside the conversation.

    Before every model call, the Gatherer asks each of the gatherer's pollers for what happened
    since it last asked, stores what they return, and only then lets the policy build the context.

    - `since` is when this poller was last asked for this gatherer, in seconds since the epoch;
      `None` the first time. The poller decides what `None` means: the file poller reports
      nothing and starts from now, while a poller reading a log might return its backlog.
    - `types` are the gatherer's event types with their ids. Return events typed by those ids
      (`Event(type_id, payload, id=..., properties=..., text=...)`), and nothing if the gatherer
      lacks your type.
    - Give each event an `id` that is the same if the same occurrence is seen again: duplicates
      are stored once.
    - Return `environment_update` or `context_stream` events when they fit, so that existing
      policies already know how to show them. An event of a type not in `outputs`, or with a
      property not in `properties`, is dropped. A poller that raises is skipped, and never fails
      a model call.
    - A poller's events belong to no channel: every session in the gatherer sees them.

    **A sketch.** A poller that turns messages appended to a JSON-lines file (say, exported from
    a team chat) into `context_stream` events, which `proactive_context_manager` shows to the
    agent where they arrived:

    ```python
    # ~/.ag/plugins/chat_log.py
    import json
    import os

    from ag.ag_interface import Event, Poller


    class ChatLogPoller(Poller):
        outputs = ("context_stream",)        # one {"author", "text", "ts"} per line
        properties = ("poller",)

        def __init__(self, path, stream="#team"):
            self.path, self.stream = os.path.expanduser(path), stream
            self.name = f"chat_log:{self.path}"

        def poll(self, since, types):
            type_id = next((t.id for t in types if t.name == "context_stream"), None)
            if type_id is None or not os.path.exists(self.path):
                return []
            events = []
            with open(self.path) as fh:
                for line in fh:
                    m = json.loads(line)
                    if since is not None and m["ts"] <= since:
                        continue
                    events.append(Event(
                        type_id,
                        {"stream": self.stream, "author": m["author"], "text": m["text"], "timestamp": m["ts"]},
                        id=f"context_stream:{self.stream}:{m['ts']}",
                        properties={"poller": self.id or self.name},
                        text=f"{m['author']} in {self.stream}: {m['text']}"))
            return events
    ```

    Registered in config.toml, and added to a gatherer (or to `[pollers] default`):

    ```toml
    [pollers.available.team_chat]
    file = "chat_log.py"
    class = "ChatLogPoller"
    args = { path = "~/team-chat.jsonl", stream = "#team" }
    ```

    ```sh
    ag --gatherer team --poller file_changes --poller team_chat claude
    ```

    An existing gatherer's pollers can be changed at any time by editing `pollers` in its
    `gatherer.toml`.

    A working poller: `FileChangePoller`, in `ag/ag_pollers/file_changes.py`.
    """

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
