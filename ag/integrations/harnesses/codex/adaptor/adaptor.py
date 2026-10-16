"""codex's adaptor: its Responses API input items as the context manager's
events (to_events.py), and the context back as input items (to_messages.py)."""

from ag.integrations.tools.ag_orchestrator.adaptor import CHANNEL, AG, CWD, Adaptor

from .to_events import OUTPUTS, to_events
from .to_messages import to_messages


class CodexAdaptor(Adaptor):
    name = "codex"
    outputs = OUTPUTS
    accepts = OUTPUTS + (AG,)
    properties = (CHANNEL, CWD)

    def to_events(self, messages: list):
        return to_events(messages)

    def to_messages(self, context: list, messages: list):
        return to_messages(context, messages)
