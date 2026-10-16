"""The event types the toolkit knows, and how a policy groups them.

The type names themselves are defined here, for the policies that use them
(the contract, ag.ag_interface, names none): each policy's events.py declares
them as its types. The tools take a `Groups` and never a policy's constants:
a policy that groups the types differently passes its own. The defaults are
grouped as the policies use them. A type in no group is not the
toolkit's business: never loaded, counted or returned.
"""

from dataclasses import dataclass
from typing import Tuple

USER_MESSAGE = "user_message"      # a real request from the user: opens a turn
AGENT_MESSAGE = "agent_message"    # the model's answer (its reasoning too, where the agent shows it)
TOOL_CALL = "tool_call"            # a request to run a tool
TOOL_OUTPUT = "tool_output"        # a tool's result
CONTEXT = "context"                # text the harness or its configurer put in front of the model --
                                   # instructions, injected context, notices -- carried verbatim,
                                   # never treated as conversation
AGENT_REASONING = "agent_reasoning"  # the model's own reasoning, opaque (e.g. encrypted):
                                   # sent back as it was where the history is verbatim, never
                                   # read, rendered or counted
#: The types the toolkit knows.
TYPES = (USER_MESSAGE, AGENT_MESSAGE, TOOL_CALL, TOOL_OUTPUT, CONTEXT, AGENT_REASONING)


@dataclass(frozen=True)
class Groups:
    """The groups of event types the tools distinguish, by type name.

    Attributes:
        user: types whose events open a turn: a real request from the user.
        messages: types rendered in the messages-only parts (the request
            index, earlier messages, related tasks, ranking, task sizes).
        tools: types rendered only in the full parts (a previous task,
            summaries; segmentation counts them).
        pinned: types carried verbatim wherever they are and never rendered
            into a section (instructions, injected context, notices).
        verbatim: types returned only where the history is returned as it
            was (the running task; everything before a build) and never
            read: not rendered, not shown to a model call, not counted in a
            task's size (the model's encrypted reasoning).
    """
    user: Tuple[str, ...] = (USER_MESSAGE,)
    messages: Tuple[str, ...] = (USER_MESSAGE, AGENT_MESSAGE)
    tools: Tuple[str, ...] = (TOOL_CALL, TOOL_OUTPUT)
    pinned: Tuple[str, ...] = (CONTEXT,)
    verbatim: Tuple[str, ...] = (AGENT_REASONING,)

    @property
    def history(self) -> Tuple[str, ...]:
        """Every type in any group: what a policy using these groups loads."""
        return tuple(dict.fromkeys(self.user + self.messages + self.tools + self.pinned + self.verbatim))
