"""The event types the proactive context manager expects: its contract with the harness.

The five standard types (ag_policies/tools/groups.py: every harness sends
them the same way), and the two generic types for what
happens outside the conversation, defined here (a poller that makes them
defines its own copy): ENVIRONMENT_UPDATE_TYPE (something in the agent's
environment changed; the policy notifies the model when the conversation
refers to its subject) and CONTEXT_STREAM_TYPE (a message from a stream the
user is part of; the policy shows it where it arrived). Any poller that
returns one of the two feeds this policy.

Last, AGENT_REASONING_TYPE: the model's own reasoning (encrypted items, thinking blocks),
kept and sent back but never read. In a gatherer running this
policy the eight are ids 1 to 8, in this order (reasoning last, so the others keep their ids).
"""

from typing import Any

from ag.ag_interface import Event, EventType
from ag.ag_policies.tools.groups import AGENT_MESSAGE, AGENT_REASONING, CONTEXT, TOOL_CALL, TOOL_OUTPUT, USER_MESSAGE
from ag.ag_policies.tools.channel import CHANNEL_PROPERTY
from ag.ag_policies.tools.cwd import CWD_PROPERTY
from ag.ag_policies.tools.poller import POLLER_PROPERTY

# The two types for what happens OUTSIDE the conversation, brought in by pollers.
ENVIRONMENT_UPDATE = "environment_update"   # something in the agent's environment changed: a file
                                            # on disk, a service, a build. Not conversation: the policy
                                            # decides when it is worth telling the model
CONTEXT_STREAM = "context_stream"           # a message from a stream the user is part of -- a chat
                                            # channel, a ticket, a feed -- that may say what a request
                                            # leaves unsaid. Not conversation either

ENVIRONMENT_UPDATE_TYPE = EventType(ENVIRONMENT_UPDATE, (CHANNEL_PROPERTY, POLLER_PROPERTY, CWD_PROPERTY))
CONTEXT_STREAM_TYPE = EventType(CONTEXT_STREAM, (CHANNEL_PROPERTY, POLLER_PROPERTY))


def environment_update(type_id: int, subject: str, what: str, timestamp: Any, source: str = "") -> Event:
    """An ENVIRONMENT_UPDATE event: payload {"subject", "what", "timestamp",
    "source"}; its id is the source, the subject and the timestamp."""
    return Event(type_id, {"subject": subject, "what": what, "timestamp": timestamp, "source": source},
                 id=f"environment_update:{source}:{subject}@{timestamp}", text=f"{subject}: {what}" if what else subject)


def context_stream(type_id: int, stream: str, author: str, text: str, timestamp: Any) -> Event:
    """A CONTEXT_STREAM event: payload {"stream", "author", "text",
    "timestamp"}; its id is the stream and the timestamp."""
    return Event(type_id, {"stream": stream, "author": author, "text": text, "timestamp": timestamp},
                 id=f"context_stream:{stream}:{timestamp}", text=f"{author} in {stream}: {text}")

USER_MESSAGE_TYPE = EventType(USER_MESSAGE, (CHANNEL_PROPERTY, CWD_PROPERTY))
AGENT_MESSAGE_TYPE = EventType(AGENT_MESSAGE, (CHANNEL_PROPERTY, CWD_PROPERTY))
TOOL_CALL_TYPE = EventType(TOOL_CALL, (CHANNEL_PROPERTY, CWD_PROPERTY))
TOOL_OUTPUT_TYPE = EventType(TOOL_OUTPUT, (CHANNEL_PROPERTY, CWD_PROPERTY))
CONTEXT_TYPE = EventType(CONTEXT, (CHANNEL_PROPERTY, CWD_PROPERTY))
AGENT_REASONING_TYPE = EventType(AGENT_REASONING, (CHANNEL_PROPERTY, CWD_PROPERTY))


EVENT_TYPES = (USER_MESSAGE_TYPE, AGENT_MESSAGE_TYPE, TOOL_CALL_TYPE, TOOL_OUTPUT_TYPE, CONTEXT_TYPE,
               ENVIRONMENT_UPDATE_TYPE, CONTEXT_STREAM_TYPE, AGENT_REASONING_TYPE)

__all__ = ["EVENT_TYPES", "ENVIRONMENT_UPDATE", "CONTEXT_STREAM", "ENVIRONMENT_UPDATE_TYPE", "CONTEXT_STREAM_TYPE",
           "environment_update", "context_stream"]
