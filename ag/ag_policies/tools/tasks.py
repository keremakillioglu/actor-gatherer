"""Helpers over tasks: their turns and entries, their size, and where they
sit in a loaded history."""

from typing import List

from .history import Entry, Task, Turn


def task_turns(task: Task, turns: List[Turn]) -> List[Turn]:
    """The turns a task spans."""
    return [t for t in turns if task.start_turn <= t.index <= task.end_turn]


def full_entries(task: Task, turns: List[Turn]) -> List[Entry]:
    """Its non-empty messages and tool items (no pinned or verbatim ones)."""
    return [e for t in task_turns(task, turns) for e in t.entries
            if e.text.strip() and (e.is_message or e.is_tool)]


def message_entries(task: Task, turns: List[Turn]) -> List[Entry]:
    """Its non-empty user and agent messages."""
    return [e for t in task_turns(task, turns) for e in t.entries if e.is_message and e.text.strip()]


def task_tokens(task: Task, turns: List[Turn]) -> int:
    """Its size: user and agent message tokens only."""
    return sum(t.message_tokens for t in turns if task.start_turn <= t.index <= task.end_turn)


def locate(tasks: List[Task], turns: List[Turn]) -> List[Task]:
    """Re-derive turn numbers (and size) from each task's rows. A task whose
    rows no longer open any turn is dropped."""
    located = []
    for task in tasks:
        span = [t for t in turns if task.first_row <= t.first_row <= task.last_row]
        if not span:
            continue
        task.start_turn, task.end_turn = span[0].index, span[-1].index
        task.tokens = sum(t.message_tokens for t in span)
        located.append(task)
    return located
