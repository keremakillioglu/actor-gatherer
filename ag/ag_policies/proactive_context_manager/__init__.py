"""The proactive context manager: earlier history as sections built in the
background, aware of what happens outside the conversation (file changes,
stream messages), with the user's requests to the session's OTHER channels
shown during a task.

    policy.py     ProactiveContextManager(Policy): the entry points, and one read from start to finish
    config.py     ProactiveContextManagerConfig: what can be tuned -- when it builds, the budgets of its
                  sections, the models the tools call
    events.py     the event types it expects: the five standard ones, environment_update, context_stream
                  and agent_reasoning

    core/         the context management itself
      assembly.py           one read: which build it uses, the items in order, the gatherer's messages at
                            their rows, and over the limit, the word-for-word part's start and left-out notes
      summaries.py          what gets summarized, and when: a build (tasks, their summaries, a ranking of
                            earlier ones) and the new-task check, and what starts each
      sections.py           a build's history sections, as text
      parallel_sessions.py  the session's other sessions: which share its work, the user's requests to them,
                            their tasks, and the note when its group changes
      external_events.py    file-change notices and messages from a stream
      prompts.py            every text the agent reads
    utils/        what it runs on
      tokens.py             counting tokens as the provider does, and the harness's own limit
      jobs.py               running builds and checks in the background
    db/           what it keeps
      tables.py             its tables and their operations, and making a gatherer message
      report.py             a gatherer from outside, read-only: what a build went through, what reads adopted

Composed from the policies' toolkit (ag_policies/tools), for any poller.
"""

from .config import ProactiveContextManagerConfig
from .policy import ProactiveContextManager

__all__ = ["ProactiveContextManager", "ProactiveContextManagerConfig"]
