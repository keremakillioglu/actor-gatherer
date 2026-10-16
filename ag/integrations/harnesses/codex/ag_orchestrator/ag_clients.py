"""A context manager server per gatherer, for the hooks behind the hook server (codex's and
Claude Code's), which serve many gatherers at once: each gatherer gets a client of its own
(ag/integrations/tools/ag_connection/ag_client.py), started on its first request and kept, so a read
that waits for a background build (up to the policy's `sync_seconds`) holds up only its own gatherer.

    ag_clients = AgClients(lambda gatherer: AgClient("codex"))
    client = ag_clients.client(gatherer)           # made the first time
    await ag_clients.close()                   # every server stopped
"""

from typing import Callable, Dict


class AgClients:
    """A server client per gatherer, made on first use.

    Args:
        make: (gatherer) -> a client: anything with `async request(op, body)`
            and `async stop()` (`ag_client.AgClient`).
    """

    def __init__(self, make: Callable):
        self.make = make
        self.by_gatherer: Dict[str, object] = {}

    def client(self, gatherer: str):
        client = self.by_gatherer.get(gatherer)
        if client is None:
            client = self.by_gatherer[gatherer] = self.make(gatherer)
        return client

    async def close(self) -> None:
        for client in self.by_gatherer.values():
            await client.stop()
        self.by_gatherer.clear()
