"""A tokenizer over litellm.token_counter, for a named model.

LiteLLM picks a tokenizer per model, falling back to o200k_base (as
`Tiktoken`) for a model it has none for. litellm takes seconds to import,
so it is imported on the first count.
"""

from ag.ag_interface import Tokenizer


class LiteLLM(Tokenizer):
    def __init__(self, model: str):
        """`model` as litellm names it, "provider/model"."""
        self.model = model
        self._counter = None
        self._tried = False

    def _load(self):
        if not self._tried:
            self._tried = True
            try:
                import litellm
                self._counter = litellm.token_counter
            except Exception:  # noqa: BLE001 - not installed
                self._counter = None
        return self._counter

    def count(self, text: str) -> int:
        if not text:
            return 0
        counter = self._load()
        if counter is not None:
            try:
                return int(counter(model=self.model, text=text))
            except Exception:  # noqa: BLE001
                pass
        return max(1, len(text) // 4)
