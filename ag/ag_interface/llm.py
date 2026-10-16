"""The model a context manager may call: text in, text out.

Any class implementing `LLM` can be the one the policies call: the home builds
the one [policies.llm] names (`class`), by default LiteLLMClient, or CLIClient
for a model of a coding agent's CLI (ag/ag_tools/llm/)."""

from abc import ABC, abstractmethod
from typing import Optional


class LLM(ABC):
    #: The model a policy's calls default to (its per-task models fall back on it):
    #: set by whoever builds the client -- the home, from [policies.llm] model.
    model: str = ""

    @abstractmethod
    def complete(self, prompt: str, *, system: Optional[str] = None, model: str,
                 effort: str, timeout: float, purpose: str) -> str:
        """The model's text answer to `prompt`, or "" on any failure. Never
        raises: a context manager must keep working when the model does not.

        Args:
            prompt: the user message.
            system: an optional system message.
            model: the model to use.
            effort: reasoning effort ("low", "medium", "high", ...).
            timeout: seconds before giving up.
            purpose: a short name for the call ("segment", "rank", ...), for
                usage logs.
        """
