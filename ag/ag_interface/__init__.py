r"""The contract every context manager implements, and what it is given: what a policy, a
poller and the harness side build on.

The framework is built to be extended in three places. A **context policy** decides what
context each model call gets. A **poller** brings in information from the environment. An
**adaptor**, with a launcher, connects a new harness. Each is a class you name in
`config.toml`; nothing else in `ag` needs to change. Policies and pollers can live in
`~/.ag/plugins/`, or in any importable package.
"""

from .context_manager import ContextManager
from .event import Event, EventType, Property
from .format import AG, FORMAT, AgFormat, Format, is_ag
from .llm import LLM
from .poller import Poller
from .policy import Context, Policy, Read, TypeIds
from .store import Jobs, Ref, Row, Gatherers, GathererStore, event_text, property_column
from .tokenizer import Tokenizer

__all__ = ["ContextManager", "Event", "EventType", "Property", "Format", "AgFormat", "FORMAT", "AG", "is_ag", "LLM", "Poller", "Tokenizer",
           "Policy", "Read", "Context", "TypeIds", "GathererStore", "Gatherers", "Jobs", "Row", "Ref", "event_text", "property_column"]
