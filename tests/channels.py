"""The policies' channel property, as the tests give it: `on(event, c)` is the
event in channel `c`; `ch(c)` the properties of a read, a lookup or a load
in it (None: no channel)."""

from dataclasses import replace

from ag.ag_policies.tools.channel import CHANNEL, of as ch  # noqa: F401


def on(event, channel):
    return replace(event, properties=ch(channel))
