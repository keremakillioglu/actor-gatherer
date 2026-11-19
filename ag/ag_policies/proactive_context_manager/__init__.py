"""The proactive context manager: earlier history as sections built in the
background, aware of what happens outside the conversation (file changes,
stream messages), with the user's requests to the session's OTHER channels
shown during a task.

    policy.py             ProactiveContextManager(Policy): the entry points, and one read from start
                          to finish. It is made of parts, one class per question, each in its own file:
    context_limit.py      keeping the context under its token limit
    external_events.py    file-change notices and messages from a stream
    parallel_requests.py  the user's requests to the session's other channels
    session_groups.py     which sessions share work, and telling a session its group changed
    gatherer_messages.py  the gatherer's messages: their names, making one, placing them among the rows
    builds.py             during a read: starting builds and checks, waiting for them, adopting a ready one
    analysis.py           in the worker: what a build computes, and the boundary check

    layout.py             a build's sections, as text
    tables.py             what it stores: tasks, cleaned messages, builds, boundary checks
    wording.py            every text it writes for the agent to read
    config.py             ProactiveContextManagerConfig: what can be tuned -- when it builds, the budgets
                          of its sections, the models the tools call
    events.py             the event types it expects: the five standard ones, environment_update,
                          context_stream and agent_reasoning
    report.py             a gatherer from outside, read-only: what a build analysed, what reads adopted

Composed from the policies' toolkit (ag_policies/tools), for any poller.
"""

from .config import ProactiveContextManagerConfig
from .policy import ProactiveContextManager

__all__ = ["ProactiveContextManager", "ProactiveContextManagerConfig"]
