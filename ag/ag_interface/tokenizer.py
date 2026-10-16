"""How a context manager counts tokens."""

from abc import ABC, abstractmethod


class Tokenizer(ABC):
    @abstractmethod
    def count(self, text: str) -> int:
        """How many tokens `text` is. Must not raise: a bad count is better
        than no context."""
