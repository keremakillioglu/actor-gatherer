"""The POLLER property: which of the gatherer's pollers an event came from -- its
id, the poller's name in the catalog (e.g. `file_changes`). The pollers
set it on what they bring in; the outside types declare it, optional, so an
event of theirs a harness sent itself carries none.
"""

from ag.ag_interface import Property

POLLER = "poller"
POLLER_PROPERTY = Property(POLLER)

