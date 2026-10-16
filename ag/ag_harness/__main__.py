"""Command line: create a gatherer's database ahead of time, define its event
types, or list them.

    python3 -m ag.ag_harness init <gatherer_id> [--type NAME[:PROPERTIES] ...]
    python3 -m ag.ag_harness add-type <gatherer_id> NAME[:PROPERTIES]
    python3 -m ag.ag_harness event-types <gatherer_id>

PROPERTIES are the type's, comma-separated, each `name` (optional) or
`name!` (required).

`init` is idempotent: calling it again for the same gatherer changes nothing; a type already defined keeps its id. All of this
works on the storage alone: no model, no Format.
"""

import argparse
import os
import sys

from . import db_path
from .store import operations, schema
from ag.ag_interface import EventType, Property


def parse_type(spec: str) -> EventType:
    """`NAME[:PROPERTIES]` -> EventType."""
    name, _, props = spec.partition(":")
    if not name:
        raise argparse.ArgumentTypeError(f"an event type needs a name: {spec!r}")
    return EventType(name, tuple(Property(p.rstrip("!"), p.endswith("!"))
                                               for p in props.split(",") if p.strip("!")))


def shown(t: EventType) -> str:
    return ",".join(p.name + ("!" if p.required else "") for p in t.properties) or "-"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m ag.ag_harness")
    sub = ap.add_subparsers(dest="command", required=True)
    p_init = sub.add_parser("init", help="create a gatherer's database, with its event types")
    p_init.add_argument("gatherer_id")
    p_init.add_argument("--type", dest="types", action="append", default=[], type=parse_type,
                        metavar="NAME[:PROPERTIES]", help="an event type to define (repeatable)")
    p_add = sub.add_parser("add-type", help="define one more event type for a gatherer")
    p_add.add_argument("gatherer_id")
    p_add.add_argument("type", type=parse_type, metavar="NAME[:PROPERTIES]")
    p_types = sub.add_parser("event-types", help="a gatherer's event types, with their ids, in order")
    p_types.add_argument("gatherer_id")
    args = ap.parse_args(argv)

    if args.command == "init":
        conn = schema.connect(args.gatherer_id)
        try:
            for t in args.types:
                operations.register_type(conn, t)
        finally:
            conn.close()
        print(db_path(args.gatherer_id))
    elif args.command == "add-type":
        conn = schema.connect(args.gatherer_id)
        try:
            print(operations.register_type(conn, args.type))
        finally:
            conn.close()
    elif args.command == "event-types":
        if not os.path.exists(db_path(args.gatherer_id)):
            print(f"no gatherer {args.gatherer_id!r} ({db_path(args.gatherer_id)})", file=sys.stderr)
            return 1
        conn = schema.connect(args.gatherer_id)
        try:
            for t in operations.event_types(conn):
                print(f"{t.id}\t{t.name}\t{shown(t)}")
        finally:
            conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
