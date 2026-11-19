"""The context management itself: what the agent's context holds, and how it is made.

    assembly.py         one read: which build it uses, the items in order, the gatherer's messages at their rows,
                        and over the limit, where the word-for-word part starts and which steps become notes
    summaries.py        what gets summarized, and when: a build (tasks, their summaries, a ranking of earlier
                        ones) and the new-task check, and what starts each
    sections.py         a build's history sections, as text
    parallel_sessions.py  the session's other sessions: which share its work, the user's requests to them,
                        their tasks, and the note when its group changes
    external_events.py  file-change notices and messages from a stream
    prompts.py          every text the agent reads
"""
