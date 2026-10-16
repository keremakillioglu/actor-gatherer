"""The default tokenizer: tiktoken's o200k_base."""

from ag.ag_interface import Tokenizer


class Tiktoken(Tokenizer):
    """Counts with tiktoken. Never raises: without tiktoken, or on an encode
    failure, characters / 4. The encoder costs ~0.7 s to load, so it is
    loaded on the first count, not at construction."""

    def __init__(self, encoding: str = "o200k_base"):
        self.encoding = encoding
        self._encoder = None
        self._tried = False

    def _load(self):
        if not self._tried:
            self._tried = True
            try:
                import tiktoken
                self._encoder = tiktoken.get_encoding(self.encoding)
            except Exception:  # noqa: BLE001 - no tiktoken, or no encoding file
                self._encoder = None
        return self._encoder

    def count(self, text: str) -> int:
        if not text:
            return 0
        encoder = self._load()
        if encoder is not None:
            try:
                return len(encoder.encode(text, disallowed_special=()))
            except Exception:  # noqa: BLE001
                pass
        return max(1, len(text) // 4)
