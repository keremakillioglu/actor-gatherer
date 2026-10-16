"""The trace database: one SQLite file per gatherer, the tables every policy
shares, and the operations on them.

    schema.py      the shared tables (event_types, events, the made items, the
                   read log), and opening a gatherer's file (connect, connection)
    operations.py  every operation on those tables: types, insert / insert_many /
                   locate, rows, made items, the read log
    paths.py       gatherer id -> database file

A policy's own tables are not here: it creates them in its `init` and
operates on them in its own module (e.g. ag_policies/proactive_context_manager/tables.py).
"""

from .paths import db_path

__all__ = ["db_path"]
