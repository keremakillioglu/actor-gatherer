"""Policies: each one a way of turning a gatherer's database into a context.

    tools/          the toolkit every policy composes its context from: history,
                    segmentation, summaries, boundary checks, ranking, rendering,
                    reading JSON out of a model's answer
    proactive_context_manager/
                    the policy: earlier history as sections at decreasing detail,
                    built in the background; the two generic outside types any
                    poller returns (its events.py) -- `environment_update` notified
                    when the conversation refers to its subject, `context_stream`
                    shown where it arrived; and the user's requests to the
                    session's other channels, shown during a task

A policy imports ag.ag_interface -- the contract -- and nothing of the context
manager's harness (ag.ag_harness): everything it works with is given to it.
At construction, whichever of format, llm (with its default model), options,
tokenizer, gatherers, jobs and log it takes; on each call, the gatherer's
store (ag.ag_interface.GathererStore), which holds what policies share -- the
events, their types, the made items, the read log -- and gives a sqlite3
connection's methods for the tables the policy keeps itself. Background work
goes through `jobs` (ag.ag_interface.Jobs), which runs the policy's method of
that name in another process. A policy knows events by their types alone:
the event types it works from, grouped, resolved to the gatherer's ids.

To add a policy, add a package (here, or anywhere importable) with a
ag.ag_interface.Policy subclass, and name it in the catalog of config.toml:
`[policies.available.<name>] class = "module:Class"`.
"""
