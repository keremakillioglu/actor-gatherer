"""An answer as ag's hooks record it (records.py's `reply_part` and `reply_end`) and a turn's model call (`model_call`),
put into a gatherer through ag's manager as its server's `insert` puts them -- what a reader (the dashboard) sees of an
answer no call has carried back yet. For tests that set one up."""
from ag.ag_harness.server import Server
from ag.integrations.tools.ag_orchestrator.records import model_call, reply_end, reply_parts

STREAMING = "streaming"


def answered(manager, gatherer: str, properties: dict, events: list, answer: str, stop=None, read_id=None) -> None:
    """`events` -- [{type, payload, text?}] -- recorded as answer `answer`'s parts and, unless it still streams
    (`stop` STREAMING), its end: why it stopped (None: not said), on read `read_id` when given."""
    records = reply_parts(answer, events) + ([] if stop == STREAMING else [reply_end(answer, stop, read_id)])
    insert(manager, gatherer, properties, records)


def turn(manager, gatherer: str, properties: dict, harness: str = "claude") -> None:
    """A turn's model call, as the hook records it."""
    insert(manager, gatherer, properties, [model_call("turn", harness)])


def insert(manager, gatherer: str, properties: dict, records: list) -> None:
    for e in Server.events_of(manager, gatherer, records, properties):
        manager.insert(gatherer, e)
