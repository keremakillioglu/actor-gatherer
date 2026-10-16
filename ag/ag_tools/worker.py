"""The detached worker: run one policy method, then exit; `spawn`, how one is
started; and `WorkerJobs`, the `ag.ag_interface.Jobs` a policy is given to start
one without knowing how.

    python3 -m ag.ag_tools.worker --factory MODULE:CALLABLE --gatherer S \\
        --job NAME --id N [--properties JSON] [--path DIR ...]

A read must return quickly, but analysing a long history takes minutes of
model calls, so a policy starts this process (`spawn`) and goes on. The
factory is how the worker gets the SAME policy the caller runs -- its format,
model client, config and tokenizer -- which the package cannot know. It is
imported (with each --path on sys.path) and called with the gatherer if it
takes an argument, else with none; it
returns a context manager (possibly wrapped, with `.inner` leading to the
`Manager`, whose `.policy` is the policy).

The worker decides nothing: it calls `policy.<job>(gatherer, properties, id)`
-- the properties the policy started the job with (ag.ag_interface.Jobs).
What a job does, and what follows from its result, is the policy's method.
When that method raises, the worker hands the failure back to the policy too
-- `policy.failed(gatherer, properties, job, id, error)`, if it has one -- so
the policy decides what a failed job leaves behind (a claim released, a
verdict recorded) and a crash never leaves a claim held.
"""

import argparse
import json
import os
import subprocess
import sys
import traceback
from typing import Any, Callable, Dict, Optional, Union

from ag.ag_interface.store import Jobs

from .imports import call, load_factory
from .log import warn

# <repo> (this file is <repo>/ag/ag_tools/worker.py)
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def command(gatherer_id: str, properties: Optional[Dict[str, Any]], job: str, job_id: int, *, factory: str,
            paths=()) -> list:
    """The worker's command line: run the policy method `job` for `job_id`
    (a build id, or the row id of the message to check) on `gatherer_id`, with
    `properties`, getting the policy from `factory` ("module:callable"),
    with each of `paths` on sys.path."""
    cmd = [sys.executable, "-m", "ag.ag_tools.worker",
           "--factory", factory, "--gatherer", gatherer_id, "--job", job, "--id", str(job_id)]
    if properties:
        cmd += ["--properties", json.dumps(properties)]
    for path in paths:
        cmd += ["--path", path]
    return cmd


def spawn(gatherer_id: str, properties: Optional[Dict[str, Any]], job: str, job_id: int, *, factory: str, paths=(),
          log: Union[str, Callable[[str], str]] = "") -> None:
    """Start the worker, detached from the caller, which does not wait. Its
    output goes to `log` -- a path, or (gatherer) -> a path; none: nowhere.
    Raises OSError if it cannot be started."""
    log = (log(gatherer_id) if callable(log) else log) or os.devnull
    os.makedirs(os.path.dirname(log) or ".", exist_ok=True)
    with open(log, "a", encoding="utf-8") as out:
        subprocess.Popen(command(gatherer_id, properties, job, job_id, factory=factory, paths=paths), cwd=_REPO,
                         stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, start_new_session=True)


class WorkerJobs(Jobs):
    """`ag.ag_interface.Jobs`, as the harness gives a policy: each job is this
    worker, detached, which gets the same policy from `factory` (the home's
    `manager`, with `paths` on sys.path) and calls its method of the job's name.
    `log`: where each job's output goes, a path or (gatherer) -> a path (the
    harness gives its logs/gatherers/<gatherer>/worker.log)."""

    def __init__(self, factory: str, paths=(), log: Union[str, Callable[[str], str]] = ""):
        self.factory, self.paths, self.log = factory, list(paths), log

    def start(self, gatherer_id: str, properties: Optional[Dict[str, Any]], job: str, job_id: int) -> None:
        spawn(gatherer_id, properties, job, job_id, factory=self.factory, paths=self.paths, log=self.log)


def unwrap(manager):
    """The policy inside whatever the factory returned: through a wrapper's
    `.inner` and a manager's `.policy`."""
    while True:
        if hasattr(manager, "inner"):
            manager = manager.inner
        elif hasattr(manager, "policy"):
            manager = manager.policy
        else:
            return manager


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m ag.ag_tools.worker")
    ap.add_argument("--factory", required=True)
    ap.add_argument("--gatherer", required=True)
    ap.add_argument("--job", required=True, help="the policy method to run")
    ap.add_argument("--id", type=int, required=True, help="what it runs on: a build id, or a row id")
    ap.add_argument("--properties", type=json.loads, default={}, help="the job's properties, as a JSON object")
    ap.add_argument("--path", action="append", default=[])
    args = ap.parse_args(argv)
    policy = None
    try:
        policy = unwrap(call(load_factory(args.factory, args.path), args.gatherer))      # a factory may take the gatherer
        if getattr(policy, "gatherers", None) is None:
            raise RuntimeError(f"{args.factory} gave a policy with no `gatherers` to open the gatherer with: "
                               f"return a manager (ag.ag_harness.Manager), which gives it one")
        result = getattr(policy, args.job)(args.gatherer, args.properties, args.id)
        warn(f"{args.job} {args.id} for {args.gatherer} {args.properties}: {result!r}"[:300])
        return 0
    except Exception as exc:  # noqa: BLE001 - hand it to the policy, never leave a claim held
        traceback.print_exc()
        try:
            failed = getattr(policy, "failed", None)
            if failed is not None:
                failed(args.gatherer, args.properties, args.job, args.id, f"{type(exc).__name__}: {exc}")
            else:
                warn(f"{args.job} {args.id} failed and the policy records no failures: {exc!r}")
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
