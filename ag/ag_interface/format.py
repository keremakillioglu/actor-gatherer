"""How a policy puts text of its own in front of the model: an `ag` message.

A policy that adds text of its own to the context -- a condensation of
earlier history, a notice, a stream message -- makes it with a Format. The
package has one, `FORMAT`: the context manager's own message,

    {"type": "ag", "name": <what it is>, "text": <the text>}

returned by a read among the events, where the model should see it. The
harness side decides how to show it to its model (a developer message, a
user message, ...); the context manager knows no harness's format.
`name` is the policy's name for it (e.g. `earlier`, `related`,
`environment_update`).
"""

from abc import ABC, abstractmethod
from typing import Any, Optional

#: The type of the context manager's own messages.
AG = "ag"


class Format(ABC):
    @abstractmethod
    def make_section(self, text: str, name: Optional[str] = None) -> Any:
        """An item that carries `text` to the model as context; `name` says
        what it is."""


class AgFormat(Format):
    def make_section(self, text: str, name: Optional[str] = None) -> dict:
        """The context manager's own message."""
        return {"type": AG, "name": name, "text": text}


FORMAT = AgFormat()


def is_ag(item) -> bool:
    """Whether `item` is one of the context manager's own messages."""
    return isinstance(item, dict) and item.get("type") == AG and isinstance(item.get("text"), str)
