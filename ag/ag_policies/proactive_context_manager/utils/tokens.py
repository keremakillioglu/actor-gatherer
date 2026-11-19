"""Counting tokens as the provider does, and the harness's own limit. A harness that states its own limit with a
call has the config scaled to it for that call (`use_limit`, config.within_limit).

Every check against max_ and min_context_tokens counts as the provider does (`by_provider`): the
hooks replace ag's counts by the provider's as they learn them, and what is
still ag's is scaled by how far the provider's own count of the channel's last
call ran over ag's (`drift_of`). The build that a provider's count over the
limit starts so decides by that same count where to cut and what to leave out,
and does not keep the running task whole because ag's own count says it fits
(2026-11-01: an Antigravity actor, Gemini counting 20% over ag, started a build
at every call for minutes, each keeping the cut where it was)."""

from contextlib import contextmanager
from typing import Dict, Optional

from ..config import ProactiveContextManagerConfig, within_limit

DRIFT_MAX = 1.5                 # the most `get_provider_drift` scales ag's count by: tokenizers differ by up to ~25% (Gemini's
                                # over o200k_base); a provider's count further over ag's is something ag does not see,
                                # not its own items counted short, and is left to `is_provider_over_limit`
                                # over o200k_base); a provider's count further over ag's is something ag does not see,
                                # not its own items counted short, and is left to `is_provider_over_limit`


class Tokens:
    """A part of ProactiveContextManager (policy.py), as every class of this package is: its methods run on the
    policy, and read what the policy holds -- `config` (the one in force: the read's or the build's), `format`,
    `tokenizer`, `llm`, `jobs` (None: no background work), `gatherers` and `groups` (the config's)."""

    max_given: bool                                   # the gatherer set max_context_tokens: no harness's limit wins
    _limited: Dict[int, ProactiveContextManagerConfig]
    drift: float

    @contextmanager
    def use_limit(self, limit: Optional[int]):
        """`self.config` as a harness's own limit makes it (`config.within_limit`), while in
        the block: one read, or one build. Not when the gatherer sets max_context_tokens, or
        none is stated. (A policy is made for each request the server answers, and each job the
        worker runs: no other thread reads its config meanwhile.)"""
        saved = self.config
        if limit and not self.max_given:
            if limit not in self._limited:
                try:
                    self._limited[limit] = within_limit(saved, limit)
                except ValueError as exc:
                    self.log(f"the harness's limit {limit} leaves too little for the budgets ({exc}); "
                             f"max_context_tokens={saved.max_context_tokens} kept")
                    self._limited[limit] = saved
            self.config = self._limited[limit]
        try:
            yield
        finally:
            self.config = saved

    @staticmethod
    def get_provider_drift(last: Optional[dict]) -> float:
        """How far over ag's count the provider counted a call: `last`'s own count (`real_tokens`, reported after
        it) over ag's count of all it sent (`sent_tokens`), at most DRIFT_MAX -- 1 when either is not known, or the
        provider counted no more than ag. The hooks set the provider's counts in place of ag's as they learn them (counting.py),
        and what is still ag's (new steps not counted yet; a harness with no count endpoint, all of it) is short
        by about this much."""
        real, sent = (last or {}).get("real_tokens"), (last or {}).get("sent_tokens")
        if not isinstance(real, int) or not isinstance(sent, int) or sent <= 0 or real <= sent:
            return 1.0
        return min(real / sent, DRIFT_MAX)

    def get_provider_count(self, tokens: int) -> int:
        """`tokens`, ag's count, as the provider would count them: scaled by `drift` (the channel's last call's,
        set at each read and build) -- what max_ and min_context_tokens are checked against, so a build decides
        by the count that started it."""
        return tokens if self.drift <= 1.0 else int(tokens * self.drift)

    def is_over_limit(self, size: int, last: Optional[dict], build: Optional[dict], ch) -> bool:
        """Whether a read's context of `size` tokens is over max_context_tokens: by ag's count, as the provider
        would count it, or by the provider's own count of the last call, which this read extends (`is_provider_over_limit`)."""
        return self.get_provider_count(size) > self.config.max_context_tokens or self.is_provider_over_limit(last, build, ch)

    def is_provider_over_limit(self, last: Optional[dict], build: Optional[dict], ch) -> bool:
        """Whether the provider's count of the last call's context (`real_tokens`, reported
        after the call) was over max_context_tokens, and that context is the one this read
        extends: the last read was made from the same build (or, like this one, from none).
        After a build its first call has not been counted yet, so a count from before it
        does not ask for another."""
        if not last or not last.get("real_tokens"):
            return False
        if last.get("basis") != (str(build["build_id"]) if build else None):
            return False
        if last["real_tokens"] <= self.config.max_context_tokens:
            return False
        self.log(f"[{ch}] the last call's context was {last['real_tokens']} tokens by the provider's count "
                 f"(ag counted {last.get('est_tokens')}), over max_context_tokens={self.config.max_context_tokens}")
        return True
