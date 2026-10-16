"""The harness's side of `ag.ag_interface.GathererStore`: one gatherer's open
database, as a policy is given it -- the shared tables' operations
(operations.py), bound to the gatherer, and the sqlite3 connection's own
methods for the tables the policy keeps itself.

    Store(conn, gatherer, path)         over an open connection (the manager's)
    StoreGatherers().open(gatherer)         a new connection, for a background job; closed after
"""

import sqlite3
from typing import Any, Dict, Iterable, List, Optional

from ag.ag_interface import EventType, Tokenizer
from ag.ag_interface.store import Row, Gatherers, GathererStore

from . import operations, schema
from .paths import db_path


class Store(GathererStore):
    def __init__(self, conn: sqlite3.Connection, gatherer: str, path: str = "", owned: bool = False):
        self.conn, self.gatherer, self.path = conn, gatherer, path or db_path(gatherer)
        self.owned = owned                                  # close() closes the connection

    # the shared tables
    def event_types(self) -> List[EventType]:
        return operations.event_types(self.conn)

    def rows(self, after_row: int = 0, type_ids: Optional[Iterable[int]] = None, *,
             match: Optional[Dict[str, Any]] = None, differ: Optional[Dict[str, Any]] = None,
             unset_matches: bool = True) -> List[Row]:
        return operations.rows(self.conn, after_row, type_ids, match=match, differ=differ,
                               unset_matches=unset_matches)

    def make_item(self, item: Any, tokenizer: Tokenizer, *, properties: Optional[Dict[str, Any]] = None,
                  name: Optional[str] = None, source: Optional[str] = None) -> int:
        return operations.make_item(self.conn, item, tokenizer, properties=properties, name=name, source=source)

    def made_items(self, made_ids) -> dict:
        return operations.made_items(self.conn, made_ids)

    def last_read(self, properties: Optional[Dict[str, Any]] = None) -> Optional[dict]:
        return operations.last_read(self.conn, properties)

    def high_water(self) -> int:
        return operations.high_water(self.conn)

    # the policy's own tables: the connection's methods
    def __getattr__(self, name: str):
        return getattr(self.conn, name)

    def __enter__(self):
        self.conn.__enter__()
        return self

    def __exit__(self, *exc):
        return self.conn.__exit__(*exc)

    def close(self) -> None:
        if self.owned:
            self.conn.close()


class StoreGatherers(Gatherers):
    def open(self, gatherer_id: str) -> Store:
        return Store(schema.connect(gatherer_id), gatherer_id, owned=True)
