"""The policies' CHANNEL: one line of work in a gatherer -- a harness's thread,
session or conversation -- as an event property (ag.ag_interface.Property).

The harness stores it and filters by it, but what it means is here: a
channel's events are its own; an event with no channel (what a poller
brings in, a history loaded without one) belongs to every channel; another
channel's events are parallel work, shown only as text. The standard types
declare it, optional, so an event without it is one every channel sees.

    CHANNEL_PROPERTY           what a type declares
    channel_of(x)              the channel of a read, a row or properties; None: none
    of(channel_id)             the properties of a channel's events and reads
"""

from typing import Any, Dict, Optional

from ag.ag_interface import Property

CHANNEL = "channel"
CHANNEL_PROPERTY = Property(CHANNEL)


def channel_of(x) -> Optional[str]:
    """The channel of a Read, a Row, or properties (a dict, or None); None:
    none."""
    properties = x if x is None or isinstance(x, dict) else x.properties
    return (properties or {}).get(CHANNEL)


def of(channel_id: Optional[str]) -> Dict[str, Any]:
    """{CHANNEL: channel_id}: what a channel's reads see (`match=`), what the
    others' events differ by (`differ=`), what its made items and jobs carry."""
    return {CHANNEL: channel_id}
