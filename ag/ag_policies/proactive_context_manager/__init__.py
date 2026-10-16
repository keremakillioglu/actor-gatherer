"""The proactive context manager: earlier history as sections built in the
background, aware of what happens outside the conversation (file changes,
stream messages), with the user's requests to the session's OTHER channels
shown during a task.

    events.py   the event types it expects: the five standard ones, environment_update,
                context_stream and agent_reasoning
    config.py   ProactiveContextManagerConfig: when it builds, the budgets of its sections,
                the models the tools call, and the wording of what it shows
    layout.py   its sections, as text
    tables.py   its tables
    report.py   a gatherer from outside, read-only: what a build analysed, what reads adopted
    policy.py   ProactiveContextManager(Policy): read, build, check, failed, bulk_loaded;
                `assemble` is where the outside and the other channels come in

Composed from the policies' toolkit (ag_policies/tools), for any poller.
"""

from .config import ProactiveContextManagerConfig
from .policy import ProactiveContextManager

__all__ = ["ProactiveContextManager", "ProactiveContextManagerConfig"]
