"""One JSON file per model call, for any LLM implementation: purpose, model,
usage, duration, any error and the answer (first 20,000 characters) -- so a
build can be priced and checked -- and, with `prompts`, the system text and the
prompt, whole. A call made by a worker's job carries the job (`job`: its gatherer,
job, id and properties, from JOB_ENV), so its cost can be put to the gatherer and
channel it was for. With `listeners` (the home's listeners/ folder), each record
written is told to them as `llm` (ag/ag_tools/notify.py), for the job's gatherer and
properties."""

import json
import os
from datetime import datetime, timezone
from typing import Optional

from ..notify import notify

JOB_ENV = "AG_JOB"      # the job the process runs, as JSON (ag.ag_tools.worker sets it)


class CallLog:
    def __init__(self, log_dir: Optional[str], prompts: bool = False, listeners: Optional[str] = None):
        self.log_dir, self.prompts, self.listeners = log_dir, prompts, listeners
        self._calls = 0

    def write(self, purpose, model, effort, usage, seconds, error, text, system, prompt, **extra) -> None:
        """One call's record; `extra` (e.g. where it was sent) goes in as given.
        Never raises: a call that cannot be logged is still answered."""
        if not self.log_dir:
            return
        try:
            os.makedirs(self.log_dir, exist_ok=True)
            self._calls += 1
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
            path = os.path.join(self.log_dir, f"{stamp}-{os.getpid()}-{self._calls}-{purpose}.json")
            job = os.environ.get(JOB_ENV)
            job = json.loads(job) if job else None
            if job:
                extra = {"job": job, **extra}
            record = {"purpose": purpose, "model": model, "effort": effort, **extra,
                      "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                      "usage": usage, "seconds": round(seconds, 3),
                      "error": error, "output_chars": len(text), "output": text[:20000]}
            if self.prompts:
                record["system"], record["prompt"] = system, prompt
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(record, fh, default=str)
        except OSError:
            return
        job = job if isinstance(job, dict) else {}
        notify(self.listeners, job.get("gatherer"), "llm", job.get("properties"))
