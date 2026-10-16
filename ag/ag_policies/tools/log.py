"""warn(): a line to stderr -- where a background job's output goes."""

import sys


def warn(message: str) -> None:
    print(f"[ag.ag_policies] {message}", file=sys.stderr, flush=True)
