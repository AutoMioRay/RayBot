"""Asynchronous token-bucket rate limiting for OpenAPI routes."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class RateRule:
    """A token bucket rule.

    Attributes:
        rate: Tokens replenished per second. Use ``qpm / 60`` for per-minute
            limits.
        burst: Maximum number of tokens that may accumulate.
    """

    rate: float
    burst: int

    def __post_init__(self) -> None:
        if self.rate <= 0:
            raise ValueError("rate must be positive")
        if self.burst < 1:
            raise ValueError("burst must be at least 1")


class TokenBucket:
    """A single asynchronous token bucket.

    ``acquire`` waits until a token is available.  The bucket is deliberately
    small and allocation-free in the steady state.
    """

    __slots__ = ("_rate", "_capacity", "_tokens", "_updated", "_lock")

    def __init__(self, rule: RateRule) -> None:
        self._rate = rule.rate
        self._capacity = float(rule.burst)
        self._tokens = float(rule.burst)
        self._updated = asyncio.get_running_loop().time()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: float = 1.0) -> None:
        """Wait until ``tokens`` can be consumed."""

        if tokens > self._capacity:
            raise ValueError("requested tokens exceed bucket capacity")

        loop = asyncio.get_running_loop()
        while True:
            async with self._lock:
                now = loop.time()
                elapsed = now - self._updated
                if elapsed > 0:
                    self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
                    self._updated = now
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                missing = tokens - self._tokens
                wait = missing / self._rate
            await asyncio.sleep(wait)


# Route names are grouped by the official frequency limits in the reference
# documentation.  Per-minute values are converted to per-second token rates.
DEFAULT_RULES: Mapping[str, RateRule] = {
    "message.send.c2c": RateRule(100.0, 100),
    "message.send.group": RateRule(100.0, 100),
    "message.stream.c2c": RateRule(50.0, 50),
    "message.recall.c2c": RateRule(10.0, 10),
    "message.recall.group": RateRule(10.0, 10),
    "media.upload.c2c": RateRule(50.0, 50),
    "media.upload.group": RateRule(50.0, 50),
    "media.prepare": RateRule(10.0, 10),
    "media.part_finish": RateRule(10.0, 10),
    "media_image.prepare": RateRule(5.0, 5),
    "media_image.complete": RateRule(5.0, 5),
    "media_image.list": RateRule(5.0, 5),
    "media_image.delete": RateRule(5.0, 5),
    "group.info": RateRule(0.5, 5),
    "group.bot_state": RateRule(0.5, 5),
    "group.member.get": RateRule(0.5, 5),
    "group.member.list": RateRule(1.0, 10),
    "group.member.batch_remove": RateRule(0.5, 5),
    "group.blacklist.get": RateRule(0.5, 5),
    "group.blacklist.set": RateRule(1.0, 10),
    "group.mute.get": RateRule(0.5, 5),
    "group.mute.set": RateRule(1.0, 10),
    "group.join.list": RateRule(0.5, 5),
    "group.join.approve": RateRule(1.0, 10),
    "group.strategy.list": RateRule(1.0, 10),
    "group.strategy.write": RateRule(1.0, 10),
    "group.strategy.execute": RateRule(1.0, 10),
    "group.strategy.whitelist": RateRule(1.0, 10),
    "bot.me": RateRule(50.0, 50),
    "bot.share_link": RateRule(50.0, 50),
    "bot.menu.read": RateRule(0.5, 5),
    "bot.menu.write": RateRule(5.0 / 60.0, 2),
    "bot.panel.read": RateRule(0.5, 5),
    "bot.panel.write": RateRule(10.0 / 60.0, 2),
    "bot.panel.target": RateRule(1.0, 10),
    "interaction.respond": RateRule(50.0, 50),
}

# Official active-message limits per single relationship (user or group).
DEFAULT_RELATION_RULES: Mapping[str, RateRule] = {
    "message.active.c2c": RateRule(20.0 / 60.0, 20),
    "message.active.group": RateRule(20.0 / 60.0, 20),
}


class RateLimitRegistry:
    """Lazily-created token buckets keyed by route and optional relation."""

    def __init__(
        self,
        rules: Mapping[str, RateRule] | None = None,
        relation_rules: Mapping[str, RateRule] | None = None,
        *,
        enabled: bool = True,
        relation_enabled: bool = True,
        max_buckets: int = 10_000,
    ) -> None:
        if max_buckets < 1:
            raise ValueError("max_buckets must be positive")
        self._rules = dict(rules or DEFAULT_RULES)
        self._relation_rules = dict(relation_rules or DEFAULT_RELATION_RULES)
        self._enabled = enabled
        self._relation_enabled = relation_enabled
        self._max_buckets = max_buckets
        self._buckets: OrderedDict[tuple[str, str | None], TokenBucket] = OrderedDict()

    def rule_for(self, route: str) -> RateRule | None:
        """Return the configured rule for ``route``, if any."""

        return self._rules.get(route)

    async def acquire(
        self,
        route: str,
        *,
        relation_scope: str | None = None,
        relation_key: str | None = None,
    ) -> None:
        """Acquire permission for one API call.

        Args:
            route: Logical route name such as ``message.send.group``.
            relation_scope: Optional active-message scope
                (``message.active.c2c`` or ``message.active.group``).
            relation_key: User or group OpenID used for the relation bucket.
        """

        if self._enabled:
            rule = self._rules.get(route)
            if rule is not None:
                await self._bucket(route, None, rule).acquire()

        if self._relation_enabled and relation_scope is not None and relation_key is not None:
            rule = self._relation_rules.get(relation_scope)
            if rule is not None:
                await self._bucket(relation_scope, relation_key, rule).acquire()

    def _bucket(self, scope: str, key: str | None, rule: RateRule) -> TokenBucket:
        bucket_key = (scope, key)
        bucket = self._buckets.get(bucket_key)
        if bucket is None:
            bucket = TokenBucket(rule)
            self._buckets[bucket_key] = bucket
            if len(self._buckets) > self._max_buckets:
                self._buckets.popitem(last=False)
        else:
            self._buckets.move_to_end(bucket_key)
        return bucket

    def reset(self) -> None:
        """Clear every bucket; intended for tests and reconnect resets."""

        self._buckets.clear()


__all__ = [
    "DEFAULT_RELATION_RULES",
    "DEFAULT_RULES",
    "RateLimitRegistry",
    "RateRule",
    "TokenBucket",
]
