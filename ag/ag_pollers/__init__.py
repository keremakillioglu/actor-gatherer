"""Pollers: sources of events from outside the conversation (`interface.Poller`).

    file_changes.py   FileChangePoller: the files under a directory modified since
                      the last poll, as `environment_update` events

A poller is the harness's side of a policy's contract for events the agent
does not produce: it returns events typed by the gatherer's types and returns
nothing for a type the gatherer does not have. The manager asks its pollers
at read time, before the policy builds the context (`Manager.poll`).
"""

from .file_changes import FileChangePoller

__all__ = ["FileChangePoller"]
