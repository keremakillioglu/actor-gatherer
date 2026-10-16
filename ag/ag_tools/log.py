"""Diagnostics. To stderr, which a background worker sends to its log file."""

import sys


def warn(message: str) -> None:
    print(f"[ag.ag_tools] {message}", file=sys.stderr)
