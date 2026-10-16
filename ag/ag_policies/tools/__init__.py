"""The context-management toolkit: what a policy composes a context from.

Part of ag.ag_policies because only policies use it; the harness knows nothing
of it, and it imports nothing of the harness (ag.ag_interface alone).

A tool computes something and returns or stores it; it decides nothing about
what goes into a context or what runs next. Those decisions are a policy's
(ag/ag_policies/<policy>/), which composes the tools in its own `read`, `build` and
`check`. Nothing here imports a policy.

    groups.py        Groups: how a policy groups the event types it knows; the tools take one
    channel.py       CHANNEL: the event property a line of work is; channel_of, of
    poller.py        POLLER: the event property a poller's id is
    cwd.py           CWD: the event property a working directory is; same_place
    history.py       Entry, Turn, Task; rows, turns, split, arrange, merge,
                     opens_turn, other_requests -- a channel's history, by type
    tasks.py, turns.py   helpers over tasks and turns
    answers.py       reading JSON out of a model's answer (the object with a key; (a, b) pairs)
    sequences.py     ends_inward(): first, last, second, second-to-last, ...
    options.py       config_from(): a policy's config from its options, models defaulting to the LLM's
    log.py           warn(): a line to stderr

    segmentation.py  turns -> named tasks                     (model calls)
    summarize.py     what each task established               (model calls)
    boundary.py      does the new message start a new task?   (a model call)
    ranking.py       earlier tasks by relevance to the work now (a model call)
                     Each declares what it is told as its own `Params` (model, effort,
                     timeout, its sizes); a policy's config builds them.

    render.py        entries and tasks as text; fitting a task into a budget   (pure)

Background work is not here: a policy starts it through the `jobs` it is
given (ag.ag_interface.Jobs), which the harness runs in a worker of its own.

What a policy makes of the tools' results -- which sections, in what words;
which tables, what is kept -- is the policy's (e.g. ag/ag_policies/proactive_context_manager/
layout.py and tables.py). The tools return tasks, a ranking, a verdict, text.
"""
