"""Helpers over sequences."""

from typing import List


def ends_inward(indices: List[int]) -> List[int]:
    """First, last, second, second-to-last, ... ."""
    out, lo, hi = [], 0, len(indices) - 1
    while lo <= hi:
        out.append(indices[lo])
        if hi != lo:
            out.append(indices[hi])
        lo, hi = lo + 1, hi - 1
    return out
