"""The contract between the context manager's harness and a policy.

The harness (ag/ag_harness/) owns the gatherer's database: it creates it,
records events and their types, polls, and logs every read. A POLICY decides
what the context is. It imports this package and nothing of the harness:
everything it works with is given to it --

    at construction      format, llm, options (and, from the harness's home,
                         tokenizer, gatherers, jobs, log): whichever it takes
    on each call         the gatherer's store (`GathererStore`, store.py): the
                         shared tables' operations, and a sqlite3 connection's
                         methods for the policy's own tables
    set by the manager   `tokenizer` and `gatherers`, when not given

A policy learns about events from their TYPES, by id. It defines the types
it expects (`Policy.event_types`, its contract with the harness), groups the
names it works from, and resolves them to the gatherer's type ids with
`TypeIds`; it loads rows by those ids (`store.rows(type_ids=...)`)
and reads an event's text with `event_text` (the caller's text, else the
payload as JSON). It never
writes `events` or the read log. Whatever else it needs to keep lives in
tables it creates in `init` and operates on in its own module.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

import sys
from .event import EventType
from .store import Row, event_text


@dataclass(frozen=True)
class Read:
    """One read call: which gatherer, the read's properties, and the event it
    responds to.

    Attributes:
        gatherer_id: the gatherer, as the caller named it.
        properties: the read's properties, by name (event.py): which events
            it is for, in the policy's own terms (e.g. its `channel`). A
            property it does not give is unset.
        row_id: the event this read responds to -- the row id `insert`
            returned for it; normally the last event before the model call.
    """
    gatherer_id: str
    properties: Dict[str, Any]
    row_id: int


@dataclass
class Context:
    """What a policy returns for a read.

    Attributes:
        items: the payloads to send, in order.
        refs: where each item came from, one `Ref` (store.py) per item
            (a stored row, or a made item), in the same order; what the
            manager logs in `_read_items`.
        basis: what the context was built from, in the policy's own terms
            (e.g. a build id), or None; logged in `_reads.basis`.
    """
    items: list = field(default_factory=list)
    refs: list = field(default_factory=list)
    basis: Optional[str] = None


class TypeIds:
    """A gatherer's event types, resolved for a policy: which id each name has.
    Loaded from the store's `event_types` (`TypeIds.load(store)`); one small
    query, done at each entry point, so a type added while the gatherer runs
    is seen by the next read or build."""

    def __init__(self, types: List[EventType]):
        self.types = list(types)
        self.by_id: Dict[int, EventType] = {t.id: t for t in types}
        self.by_name: Dict[str, int] = {t.name: t.id for t in types}

    @classmethod
    def load(cls, store) -> "TypeIds":
        return cls(store.event_types())

    def of(self, *names: str) -> FrozenSet[int]:
        """The ids of the types named; a name the gatherer does not have has
        none."""
        return frozenset(self.by_name[n] for n in names if n in self.by_name)

    def name(self, type_id: int) -> Optional[str]:
        t = self.by_id.get(type_id)
        return t.name if t else None

    @staticmethod
    def text(row: Row) -> str:
        """An event's readable text (`event_text`)."""
        return event_text(row)


class Policy(ABC):
    """One way of building an agent's context from the gatherer's database."""

    #: What the registry and the read log call it.
    name: str = ""

    #: The event types this policy expects the harness to insert: its side of
    #: the contract. Name and properties. Registered, in this order, when a gatherer
    #: is created, before any the caller adds.
    event_types: Tuple[EventType, ...] = ()

    #: What the harness gives it, when its constructor was not given them:
    #: the tokenizer events are counted with, and `Gatherers` (store.py), which
    #: opens a gatherer's store for work outside a read. Set by the manager.
    tokenizer = None
    gatherers = None
    #: `Jobs` (store.py), which starts background work; None = none is started.
    jobs = None

    def log(self, line: str) -> None:
        """A line for whoever runs it (a background worker's log). The
        harness may give another (`log=`)."""
        print(f"[policy {self.name}] {line}", file=sys.stderr, flush=True)

    def init(self, store) -> None:
        """Create whatever the policy keeps in the gatherer's database beyond
        the shared tables. Idempotent; the manager calls it whenever it
        creates or first opens a gatherer. Default: nothing."""

    @abstractmethod
    def read(self, store, read: Read) -> Context:
        """The context to send in response to `read`, from the gatherer's
        database. May write made items and the policy's own tables, and may
        start or wait for background work. Never records the read: the
        manager does that with what is returned.

        Args:
            store: the gatherer's `GathererStore` (store.py).
            read: the read call: gatherer, properties, and the event responded to.
        """

    def bulk_loaded(self, store, gatherer_id: str, properties: Dict[str, Any]) -> Any:
        """Called after the manager stored a whole recorded history at once
        (`Manager.bulk_load`). A policy that can prepare its context from it
        in one go does so here; what it returns is what `bulk_load` returns.
        Default: nothing."""
        return None
