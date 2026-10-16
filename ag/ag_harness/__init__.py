"""The context manager's harness: what runs a policy over a gatherer's trace
database. It is one of five packages:

    ag/ag_interface/   the contract: events and their types; the Policy and Poller
                    bases; what a policy is given (GathererStore, Gatherers, Jobs)
    ag/ag_harness/     this: the manager, the store, the server, the home
    ag/ag_tools/       what it runs policies with: model clients, tokenizers, the
                    background worker (WorkerJobs), helpers
    ag/ag_policies/    the policy (proactive_context_manager) and the toolkit it is
                    built from
    ag/ag_pollers/     the poller (file changes)

The harness imports ag.ag_interface and no policy or poller: the home builds the
ones config.toml's catalog names by class path
(`class = "ag.ag_policies.proactive_context_manager:ProactiveContextManager"`),
and gives a policy what it needs -- format, llm, options, tokenizer, jobs at
construction; the gatherer's store on each call.

A context manager is an implementation of `ag.ag_interface.ContextManager`: `init`
creates a gatherer's storage and defines its event types, `add_event_type`
defines one more, `insert` records one event (returning its row id, which
`locate` finds again for a re-sent one), `read` returns the context to send
next in response to an event named by row id, and `event_types` lists the
gatherer's types with their ids. `Manager` (manager.py) is the one here: it
owns the database, runs a POLICY and asks its POLLERS at read time.

    manager.py   Manager: the ContextManager over the store, running a policy
    store/       the trace database every policy shares (schema, operations, paths),
                 and gatherer.py: Store and StoreGatherers, the interface's GathererStore
                 and Gatherers over it
    server/      the context manager behind stdio (`python -m ag.ag_harness.server`)
    home/        ~/.ag: config.toml (the catalog, defaults, the LLM), plugins, gatherers

Gatherers are resolved to database files internally (`store.paths.db_path`:
~/.ag/gatherers/<gatherer>/context.db, or under AG_HOME). Events carry the
PROPERTIES their types declare, each a column the store adds for it; what
a property means is the policy's, and this package names none. Everything
is an EVENT: an opaque,
JSON-serializable payload -- stored and returned verbatim -- of one of the
gatherer's `EventType`s, named by id. What turns a particular agent's messages
into events is the harness side (`ag/integrations/harnesses/<harness>/adaptor/`),
which reaches this package only through its server, over stdio; this package
knows no harness. What a policy writes itself comes back as an `ag` message.
"""

from ag.ag_interface import (LLM, ContextManager, Event, EventType, Format, AgFormat, FORMAT, AG, is_ag, Poller,
                          Tokenizer, Context, Policy, Read, TypeIds)
from .manager import Manager
from .store.paths import db_path  # noqa: F401 - for callers that want the file itself

__all__ = ["ContextManager", "Event", "EventType", "Format", "AgFormat", "FORMAT", "AG", "is_ag", "LLM", "Poller", "Tokenizer",
           "Manager", "Policy", "Read", "Context", "TypeIds", "db_path"]
