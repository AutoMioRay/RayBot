"""Bounded event de-duplication."""

from __future__ import annotations

import time
from collections import OrderedDict


class Deduplicator:
    """Remember recently seen event keys for a bounded TTL.

    QQ may deliver the same message more than once to guarantee at-least-once
    delivery.  The deduplicator suppresses such repeats before handlers run.
    """

    __slots__ = ("_ttl", "_max_size", "_seen")

    def __init__(self, *, ttl: float = 600.0, max_size: int = 20_000) -> None:
        if ttl <= 0:
            raise ValueError("ttl must be positive")
        if max_size < 1:
            raise ValueError("max_size must be at least 1")
        self._ttl = ttl
        self._max_size = max_size
        self._seen: OrderedDict[str, float] = OrderedDict()

    def is_duplicate(self, key: str) -> bool:
        """Return ``True`` when ``key`` was seen within the TTL window."""

        now = time.monotonic()
        self._purge(now)
        if key in self._seen:
            return True
        self._seen[key] = now
        while len(self._seen) > self._max_size:
            self._seen.popitem(last=False)
        return False

    def _purge(self, now: float) -> None:
        boundary = now - self._ttl
        while self._seen:
            _, seen_at = next(iter(self._seen.items()))
            if seen_at >= boundary:
                return
            self._seen.popitem(last=False)

    def clear(self) -> None:
        """Forget every remembered key."""

        self._seen.clear()


__all__ = ["Deduplicator"]
