"""Asynchronous event bus with bounded backpressure."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from ..models.base import Event

logger = logging.getLogger(__name__)

Handler = Callable[[Any], Awaitable[None] | None]
ErrorHandler = Callable[[Event, Handler, Exception], Awaitable[None] | None]


@dataclass(slots=True)
class Subscription:
    handler: Handler
    priority: int = 0
    once: bool = False


class EventBus:
    """Dispatch gateway events to handlers through a fixed worker pool.

    Events are queued and consumed by ``concurrency`` workers.  Handlers for a
    single event run in priority order; handlers for different events run in
    parallel up to the worker count.  Exceptions never stop the bus: they are
    routed to the error handler and logged.

    Args:
        concurrency: Number of worker tasks consuming the queue.
        queue_size: Maximum number of queued events (backpressure bound).
        overflow: What :meth:`publish` does when the queue is full.
            ``"block"`` awaits capacity (never loses events, but stalls the
            gateway receive loop under sustained flooding);
            ``"drop"`` discards the event, counts it and logs a warning, which
            keeps the receive loop and heartbeats flowing at the cost of lost
            deliveries.
    """

    def __init__(
        self,
        *,
        concurrency: int = 64,
        queue_size: int = 2048,
        overflow: str = "block",
    ) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be positive")
        if queue_size < 1:
            raise ValueError("queue_size must be positive")
        if overflow not in {"block", "drop"}:
            raise ValueError("overflow must be 'block' or 'drop'")
        self._concurrency = concurrency
        self._queue: asyncio.Queue[Event | None] = asyncio.Queue(maxsize=queue_size)
        self._subscriptions: dict[str, list[Subscription]] = {}
        self._all: list[Subscription] = []
        self._merged: dict[str, tuple[Subscription, ...]] = {}
        self._workers: list[asyncio.Task[None]] = []
        self._error_handler: ErrorHandler | None = None
        self._started = False
        self._stopping = False
        self._overflow = overflow
        self._published = 0
        self._processed = 0
        self._dropped = 0
        self._drop_warned = 0

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    @property
    def overflow_policy(self) -> str:
        return self._overflow

    @property
    def stats(self) -> Mapping[str, int]:
        """Counters for lightweight throughput observation."""

        return {
            "published": self._published,
            "processed": self._processed,
            "dropped": self._dropped,
            "queued": self._queue.qsize(),
            "workers": len(self._workers),
        }

    @property
    def running(self) -> bool:
        return self._started and not self._stopping

    def start(self) -> None:
        """Start the worker pool. Safe to call more than once."""

        if self._started:
            if self._stopping:
                raise RuntimeError("event bus is stopping")
            return
        self._started = True
        self._stopping = False
        loop = asyncio.get_running_loop()
        self._workers = [
            loop.create_task(self._worker(), name=f"qqbot-event-worker-{index}")
            for index in range(self._concurrency)
        ]

    async def stop(self, *, drain: bool = True) -> None:
        """Stop the workers, optionally waiting for queued events first.

        When called from inside a handler, draining and waiting for all workers
        would deadlock.  In that case the current worker is excluded and the
        remaining queue is not drained.
        """

        if not self._started:
            return
        current = asyncio.current_task()
        inside_worker = current is not None and current in self._workers
        if drain and not inside_worker:
            await self._queue.join()
        self._stopping = True
        for _ in self._workers:
            await self._queue.put(None)
        waiting = [worker for worker in self._workers if worker is not current]
        if waiting:
            await asyncio.gather(*waiting, return_exceptions=True)
        self._workers.clear()
        self._started = False
        self._stopping = False

    async def publish(self, event: Event) -> None:
        """Queue an event, applying backpressure when the queue is full.

        With ``overflow="drop"`` a full queue discards the event instead of
        awaiting capacity; the drop is counted and logged periodically.
        """

        if not self._started:
            self.start()
        if self._stopping:
            raise RuntimeError("event bus is stopping")
        if self._overflow == "drop" and self._queue.full():
            self._dropped += 1
            if self._dropped - self._drop_warned >= 100 or self._drop_warned == 0:
                logger.warning(
                    "event bus queue is full; %s event(s) dropped so far",
                    self._dropped,
                )
                self._drop_warned = self._dropped
            return
        await self._queue.put(event)
        self._published += 1

    def publish_nowait(self, event: Event) -> bool:
        """Queue an event only if capacity is available.

        Returns:
            ``True`` when queued, ``False`` when the queue is full.
        """

        if not self._started:
            self.start()
        if self._stopping:
            raise RuntimeError("event bus is stopping")
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            return False
        self._published += 1
        return True

    async def drain(self) -> None:
        """Wait until every queued event has been processed."""

        await self._queue.join()

    def subscribe(
        self, event_name: str, handler: Handler, *, priority: int = 0, once: bool = False
    ) -> Callable[[], None]:
        """Register a handler for one event name.

        Returns:
            A callable that removes the subscription.
        """

        subscription = Subscription(handler=handler, priority=priority, once=once)
        bucket = self._subscriptions.setdefault(event_name, [])
        bucket.append(subscription)
        bucket.sort(key=lambda item: item.priority, reverse=True)
        self._merged.pop(event_name, None)

        def unsubscribe() -> None:
            entries = self._subscriptions.get(event_name)
            if entries and subscription in entries:
                entries.remove(subscription)
                if not entries:
                    self._subscriptions.pop(event_name, None)
                self._merged.pop(event_name, None)

        return unsubscribe

    def subscribe_all(
        self, handler: Handler, *, priority: int = 0, once: bool = False
    ) -> Callable[[], None]:
        """Register a handler for every event name."""

        subscription = Subscription(handler=handler, priority=priority, once=once)
        self._all.append(subscription)
        self._all.sort(key=lambda item: item.priority, reverse=True)
        self._merged.clear()

        def unsubscribe() -> None:
            if subscription in self._all:
                self._all.remove(subscription)
                self._merged.clear()

        return unsubscribe

    def on(
        self, event_name: str, *, priority: int = 0, once: bool = False
    ) -> Callable[[Handler], Handler]:
        """Decorator form of :meth:`subscribe`."""

        def decorator(handler: Handler) -> Handler:
            self.subscribe(event_name, handler, priority=priority, once=once)
            return handler

        return decorator

    def on_error(self, handler: ErrorHandler) -> ErrorHandler:
        """Set the handler invoked when a subscriber raises."""

        self._error_handler = handler
        return handler

    async def _worker(self) -> None:
        while True:
            event = await self._queue.get()
            try:
                if event is None:
                    return
                await self._dispatch(event)
            finally:
                self._processed += 1
                self._queue.task_done()

    def _subscriptions_for(self, name: str) -> tuple[Subscription, ...]:
        """Return the merged, priority-ordered subscriptions for ``name``.

        The result is cached per event name; every mutation invalidates the
        affected entries.  Building the list once per subscription change (not
        once per dispatched event) keeps the hot path allocation-free.
        """

        cached = self._merged.get(name)
        if cached is None:
            merged = list(self._subscriptions.get(name, ())) + list(self._all)
            merged.sort(key=lambda item: item.priority, reverse=True)
            cached = tuple(merged)
            self._merged[name] = cached
        return cached

    async def _dispatch(self, event: Event) -> None:
        name = getattr(event, "event_name", "") or getattr(event, "name", "")
        subscriptions = self._subscriptions_for(name)
        if not subscriptions:
            return
        for subscription in subscriptions:
            await self._invoke(subscription, event)

    async def _invoke(self, subscription: Subscription, event: Event) -> None:
        if subscription.once:
            self._remove(subscription)
        try:
            result = subscription.handler(event)
            if inspect.isawaitable(result):
                await result
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - handler isolation
            logger.exception(
                "handler %r failed for event %s",
                getattr(subscription.handler, "__name__", subscription.handler),
                getattr(event, "event_name", type(event).__name__),
            )
            if self._error_handler is not None:
                try:
                    result = self._error_handler(event, subscription.handler, exc)
                    if inspect.isawaitable(result):
                        await result
                except Exception:  # noqa: BLE001 - error handlers must not kill workers
                    logger.exception("event error handler failed")

    def _remove(self, subscription: Subscription) -> None:
        for name, bucket in self._subscriptions.items():
            if subscription in bucket:
                bucket.remove(subscription)
                self._merged.pop(name, None)
                return
        if subscription in self._all:
            self._all.remove(subscription)
            self._merged.clear()


__all__ = ["ErrorHandler", "EventBus", "Handler", "Subscription"]
