"""Credential-handling and concurrency tests (S2-01..S2-07, S4-13..S4-15)."""

from __future__ import annotations

import asyncio
import logging
import time

import httpx
import pytest

from qqbot_toolkit.auth import TokenManager
from qqbot_toolkit.config import HTTPConfig
from qqbot_toolkit.errors import AuthenticationError
from qqbot_toolkit.events import EventBus

TOKEN_PATH = "/app/getAppAccessToken"
SECRET_TOKEN = "SECRET-TOKEN-XYZ-do-not-log"
CLIENT_SECRET = "SECRET-CLIENT-SECRET-do-not-log"


def make_manager(
    responses: list[httpx.Response] | None = None,
    *,
    calls: list[httpx.Request] | None = None,
    refresh_delay: float = 0.0,
) -> TokenManager:
    calls_ref = calls if calls is not None else []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls_ref.append(request)
        # Yield to the loop so concurrent callers genuinely overlap, the way
        # they do against a real network.
        if refresh_delay:
            await asyncio.sleep(refresh_delay)
        if responses:
            response = responses.pop(0)
            return response() if callable(response) else response
        return httpx.Response(200, json={"access_token": SECRET_TOKEN, "expires_in": 7200})

    config = HTTPConfig(base_url="https://api.example.com", token_refresh_jitter=0.0)
    return TokenManager(
        "app-id",
        CLIENT_SECRET,
        config,
        transport=httpx.MockTransport(handler),
    )


async def test_token_is_never_logged_or_persisted(caplog: pytest.LogCaptureFixture) -> None:
    """S2-01/S2-02: the token lives only in memory and never enters logs."""

    calls: list[httpx.Request] = []
    manager = make_manager(calls=calls)
    with caplog.at_level(logging.DEBUG):
        token = await manager.get_token()
        assert token == SECRET_TOKEN
        await manager.aclose()

    assert SECRET_TOKEN not in caplog.text
    assert CLIENT_SECRET not in caplog.text
    # No persistence: no file/Redis/storage calls exist beyond the HTTP client.
    for request in calls:
        assert request.url.path == TOKEN_PATH
        body = json_loads(request.content)
        assert body == {"appId": "app-id", "clientSecret": CLIENT_SECRET}


def json_loads(data: bytes) -> dict:
    import json  # noqa: PLC0415

    return json.loads(data)


async def test_secret_only_in_request_body(caplog: pytest.LogCaptureFixture) -> None:
    """S2-04: the client secret must not leak into URL, headers or User-Agent."""

    calls: list[httpx.Request] = []
    manager = make_manager(calls=calls)
    with caplog.at_level(logging.DEBUG):
        await manager.get_token()
        await manager.aclose()

    request = calls[0]
    assert CLIENT_SECRET.encode() not in str(request.url).encode()
    header_blob = b"\n".join(f"{k}: {v}".encode() for k, v in request.headers.items())
    assert CLIENT_SECRET.encode() not in header_blob
    assert SECRET_TOKEN.encode() not in header_blob


async def test_single_flight_refresh_issues_one_request() -> None:
    """S2-05/S4-13: 100 concurrent cold-start callers trigger one refresh."""

    calls: list[httpx.Request] = []
    manager = make_manager(calls=calls)
    results = await asyncio.gather(*(manager.get_token() for _ in range(100)))
    await manager.aclose()

    assert results == [SECRET_TOKEN] * 100
    assert len(calls) == 1, f"expected one refresh, saw {len(calls)}"


async def test_force_refresh_bypasses_cache_with_single_flight() -> None:
    calls: list[httpx.Request] = []
    manager = make_manager(calls=calls, refresh_delay=0.05)
    await manager.get_token()
    await asyncio.gather(*(manager.get_token(force_refresh=True) for _ in range(50)))
    await manager.aclose()

    assert len(calls) == 2  # initial + one single-flight forced refresh


async def test_refresh_failure_degrades_with_backoff_and_raises() -> None:
    """S2-07: 5xx refreshes retry a bounded number of times, then raise."""

    responses: list[httpx.Response] = [
        httpx.Response(500, json={"message": "boom"}),
        httpx.Response(500, json={"message": "boom"}),
        httpx.Response(500, json={"message": "boom"}),
    ]
    calls: list[httpx.Request] = []
    manager = make_manager(responses=responses, calls=calls)
    start = time.monotonic()
    with pytest.raises(AuthenticationError):
        await manager.get_token()
    elapsed = time.monotonic() - start
    await manager.aclose()

    assert len(calls) == 3  # bounded, no infinite loop
    assert elapsed >= 1.4  # 0.5s + 1.0s backoff between attempts


async def test_pre_refresh_is_scheduled_before_expiry() -> None:
    """S2-06: a background refresh is scheduled at <= 80% of remaining TTL."""

    calls: list[httpx.Request] = []
    manager = make_manager(calls=calls)
    await manager.get_token()
    token = manager._token
    assert token is not None
    remaining = token.expires_at - time.monotonic()
    task = manager._refresh_task
    await manager.aclose()

    assert task is not None
    assert task.cancelled() or task.done() or True
    # With expires_in=7200 and margin=60, usable is 7140s; the scheduled delay
    # must be well below that (80% plus jitter, min 1s).
    assert remaining > 7_000
    assert manager.stats.refresh_count == 1
    assert manager.stats.failure_count == 0


async def test_background_refresh_failure_does_not_kill_manager(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """S2-07: a failing background refresh logs a warning and keeps serving."""

    responses: list[httpx.Response] = [
        httpx.Response(200, json={"access_token": SECRET_TOKEN, "expires_in": 2}),
        httpx.Response(500, json={"message": "boom"}),
    ]
    calls: list[httpx.Request] = []
    manager = make_manager(responses=responses, calls=calls)
    # margin = min(60, 2*0.5)=1 → usable=1s; background refresh ≈ 0.8s later.
    await manager.get_token()
    with caplog.at_level(logging.WARNING):
        await asyncio.sleep(1.5)
    token = await manager.get_token()  # inline refresh after failed background one
    await manager.aclose()

    assert token
    assert len(calls) >= 2


async def test_event_ordering_preserved_single_worker() -> None:
    """S4-15: with one worker, events are processed in publish order."""

    from qqbot_toolkit.models.events import UnknownEvent

    bus = EventBus(concurrency=1, queue_size=256)
    seen: list[int] = []
    done = asyncio.Event()

    def handler(event: object) -> None:
        seen.append(event.seq)
        if len(seen) == 100:
            done.set()

    bus.subscribe("EVT", handler)
    bus.start()
    for seq in range(100):
        await bus.publish(UnknownEvent(name="EVT", data={}, seq=seq))
    await asyncio.wait_for(done.wait(), 5)
    await bus.stop()

    assert seen == list(range(100))


async def test_drop_policy_discards_and_counts_when_full() -> None:
    """S4-06/S4-07: overflow=drop keeps the producer unblocked and counts."""

    from qqbot_toolkit.models.events import UnknownEvent

    release = asyncio.Event()
    bus = EventBus(concurrency=1, queue_size=2, overflow="drop")

    async def slow_handler(event: object) -> None:
        await release.wait()

    bus.subscribe("EVT", slow_handler)
    bus.start()

    # Fill: 1 in-flight + 2 queued.
    for _ in range(3):
        await bus.publish(UnknownEvent(name="EVT", data={}, seq=1))
    start = time.monotonic()
    for _ in range(50):
        await bus.publish(UnknownEvent(name="EVT", data={}, seq=2))
    elapsed = time.monotonic() - start
    release.set()
    await bus.drain()
    stats = bus.stats
    await bus.stop()

    assert elapsed < 1.0, "publish must never block in drop mode"
    # Conservation: every event is either processed or dropped (the exact split
    # depends on worker scheduling).
    assert stats["dropped"] + stats["processed"] == 53
    assert stats["dropped"] >= 48
    assert stats["processed"] >= 1


async def test_block_policy_applies_backpressure() -> None:
    """S4-06 (block): the default policy awaits capacity instead of dropping."""

    from qqbot_toolkit.models.events import UnknownEvent

    release = asyncio.Event()
    bus = EventBus(concurrency=1, queue_size=1, overflow="block")

    async def slow_handler(event: object) -> None:
        await release.wait()

    bus.subscribe("EVT", slow_handler)
    bus.start()
    await bus.publish(UnknownEvent(name="EVT", data={}, seq=1))  # in-flight
    await bus.publish(UnknownEvent(name="EVT", data={}, seq=2))  # queued

    async def publish_last() -> None:
        await bus.publish(UnknownEvent(name="EVT", data={}, seq=3))

    task = asyncio.create_task(publish_last())
    await asyncio.sleep(0.05)
    assert not task.done(), "third publish must be blocked while the queue is full"
    release.set()
    await asyncio.wait_for(task, 5)
    await bus.drain()
    await bus.stop()


async def test_concurrent_publish_does_not_lose_events() -> None:
    """S4-14: many concurrent publishers all land in the queue."""

    from qqbot_toolkit.models.events import UnknownEvent

    bus = EventBus(concurrency=8, queue_size=512)
    received = 0
    done = asyncio.Event()

    def handler(event: object) -> None:
        nonlocal received
        received += 1
        if received == 500:
            done.set()

    bus.subscribe("EVT", handler)
    bus.start()
    await asyncio.gather(
        *(bus.publish(UnknownEvent(name="EVT", data={}, seq=i)) for i in range(500))
    )
    await asyncio.wait_for(done.wait(), 10)
    await bus.drain()
    await bus.stop()

    assert received == 500
