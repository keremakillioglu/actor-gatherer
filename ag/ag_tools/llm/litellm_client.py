"""An LLM over LiteLLM's SDK (`litellm.completion`): any provider LiteLLM knows,
named by the model.

The model says which provider to call, as LiteLLM names it --
"gemini/gemini-3.8-flash", "anthropic/claude-sonnet-5-5", "openai/gpt-5" --
and the provider's key is read from its usual variable (GEMINI_API_KEY,
ANTHROPIC_API_KEY, OPENAI_API_KEY, ...) unless one is given. With `api_base`,
calls go to that server instead: a LiteLLM proxy, or any OpenAI-compatible
endpoint; a model named without a provider is then sent as "openai/<model>",
which is how LiteLLM talks to such a server.

litellm is imported on the first call (it takes seconds), so a process that
never calls the model never pays for it.
"""

import time
from typing import Optional

from ag.ag_interface import LLM

from .calllog import CallLog


class LiteLLMClient(LLM):
    def __init__(self, *, api_base: Optional[str] = None, api_key: Optional[str] = None,
                 log_dir: Optional[str] = None, log_prompts: bool = False):
        """
        Args:
            api_base: a server to send every call to (a LiteLLM proxy, an
                OpenAI-compatible endpoint); None: the provider's own API.
            api_key: the key; None: LiteLLM reads the provider's variable.
            log_dir: if given, one JSON file per call there: purpose, model,
                usage, duration, any error and the answer (first 20,000
                characters) -- so a build can be priced and checked.
            log_prompts: also keep the system text and the prompt, whole, so
                the log is a complete record of every call.
        """
        self.api_base = api_base or None
        self.api_key = api_key or None
        self.log_dir = log_dir
        self.log_prompts = log_prompts
        self._calllog = CallLog(log_dir, log_prompts)

    def route(self, model: str) -> str:
        """The model as LiteLLM is asked for it: "openai/<model>" for a server
        of our own when the model names no provider, else as given."""
        return f"openai/{model}" if self.api_base and "/" not in model else model

    def complete(self, prompt: str, *, system: Optional[str] = None, model: str,
                 effort: str, timeout: float, purpose: str) -> str:
        messages = ([{"role": "system", "content": system}] if system else []) + \
                   [{"role": "user", "content": prompt}]
        kwargs = {"model": self.route(model), "messages": messages, "timeout": timeout,
                  "drop_params": True}                  # a model without reasoning effort ignores it
        if effort:
            kwargs["reasoning_effort"] = effort
        if self.api_base:
            kwargs["api_base"] = self.api_base
        if self.api_key:
            kwargs["api_key"] = self.api_key
        started = time.time()
        usage, error, text = None, None, ""
        if not model:
            error = "no model: set [policies.llm] model (or AG_LLM_MODEL), e.g. gemini/gemini-3.8-flash"
            self._log(purpose, model, effort, usage, 0.0, error, text, system, prompt)
            return text
        try:
            import litellm
            litellm.suppress_debug_info = True
            response = litellm.completion(**kwargs)
            text = response.choices[0].message.content or ""
            usage = _plain(getattr(response, "usage", None))
        except Exception as exc:  # noqa: BLE001 - never raise to the caller
            error = f"{type(exc).__name__}: {exc}"
        self._log(purpose, kwargs["model"], effort, usage, time.time() - started, error, text,
                  system, prompt)
        return text

    def _log(self, purpose, model, effort, usage, seconds, error, text, system, prompt) -> None:
        self._calllog.write(purpose, model, effort, usage, seconds, error, text, system, prompt,
                            api_base=self.api_base)

def _plain(usage):
    """A response's usage as a plain dict (LiteLLM's is a pydantic model), or None."""
    if usage is None:
        return None
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    return dict(usage) if isinstance(usage, dict) else None
