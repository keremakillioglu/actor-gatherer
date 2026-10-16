"""One JSON file per model call, for any LLM implementation: purpose, model,
usage, duration, any error and the answer (first 20,000 characters) -- so a
build can be priced and checked -- and, with `prompts`, the system text and the
prompt, whole."""

import json
import os
from datetime import datetime, timezone
from typing import Optional


class CallLog:
    def __init__(self, log_dir: Optional[str], prompts: bool = False):
        self.log_dir, self.prompts = log_dir, prompts
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
            record = {"purpose": purpose, "model": model, "effort": effort, **extra,
                      "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                      "usage": usage, "seconds": round(seconds, 3),
                      "error": error, "output_chars": len(text), "output": text[:20000]}
            if self.prompts:
                record["system"], record["prompt"] = system, prompt
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(record, fh, default=str)
        except OSError:
            pass
