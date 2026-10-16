"""Helpers over turns."""

from typing import Dict, List

from .history import Entry, Turn


def messages(turn: Turn) -> List[Entry]:
    """The user and agent messages of a turn, nothing else."""
    return [e for e in turn.entries if e.is_message]


def turns_between(turns: List[Turn], start_turn: int, end_turn: int) -> List[Turn]:
    return [t for t in turns if start_turn <= t.index <= end_turn]


def by_turn(turns: List[Turn]) -> Dict[int, Turn]:
    """Turns by their index."""
    return {t.index: t for t in turns}
