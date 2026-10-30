"""L3 protocol-level security tests: handshake, heartbeat, resume, close codes.

Covers the WebSocket-side cases from the security test plan (S3-xx and parts of
S4-xx): close-code branch completeness, Resume/Identify fallbacks, heartbeat
intervals, and reconnect limits.  Each test drives a real client against a
local scripted server over plain ws:// (loopback is explicitly allowed).
"""

from __future__ import annotations

import asyncio
import contextlib
import time

import pytest
from websockets.exceptions import ConnectionClosed

from RayBot.core.config import GatewayConfig
from RayBot.core.errors import GatewayError
from RayBot.core.events import EventBus
from RayBot.core.gateway.ws import GatewayClient
from RayBot.core.models import GatewayInfo, SessionStartLimit
from RayBot.core.net import is_trusted_gateway_url

from .ws_helpers import ScriptedServer, hello, ready


class FakeTokens:
    async def get_token(self, *, force_refresh: bool = False) -> str:
        return "secret-token-value"


class FakeGatewayAPI:
    def __init__(self, url: str) -> None:
        self.url = url
        self.calls = 0

    async def get(self) -> GatewayInfo:
        self.calls += 1
        return GatewayInfo(
            url=self.url,
            shards=1,
            session_start_limit=SessionStartLimit(max_concurrency=1),
        )


def make_config(**overrides: object) -> GatewayConfig:
    defaults: dict[str, object] = {
        "reconnect_initial_delay": 0.01,
        "reconnect_max_delay": 0.02,
        "open_timeout": 2.0,
        # Tiny heartbeat bounds so hostile-interval scenarios run in
        # milliseconds instead of seconds.
        "heartbeat_min_interval": 0.05,
        "heartbeat_max_interval": 0.2,
        "heartbeat_timeout_factor": 1.5,
    }
    defaults.update(overrides)
    return GatewayConfig(**defaults)  # type: ignore[arg-type]


async def run_until(
    client: GatewayClient,
    event: asyncio.Event,
    *,
    limit: float = 5.0,
) -> None:
    task = asyncio.create_task(client.run())
    try:
        await asyncio.wait_for(event.wait(), limit)
    finally:
        await client.stop()
        with contextlib.suppress(asyncio.CancelledError, GatewayError, TimeoutError):
            await asyncio.wait_for(task, limit)


async def test_close_code_4004_is_fatal_and_stops_reconnecting() -> None:
    """S3-15: authentication failure must stop the loop with a fatal error."""

    async def handler(ws, server: ScriptedServer) -> None:
        await server.send(ws, hello())
        await server.recv(ws)
        await ws.close(code=4004, reason="invalid token")

    async with ScriptedServer(handler) as server:
        bus = EventBus(concurrency=2)
        bus.start()
        client = GatewayClient(FakeTokens(), FakeGatewayAPI(server.url), make_config(), bus)
        with pytest.raises(GatewayError) as excinfo:
            await client.run()
        await bus.stop()

    assert excinfo.value.fatal
    assert excinfo.value.close_code == 4004
    assert server.connections == 1, "client must not retry after an auth failure"


@pytest.mark.parametrize("code", [4914, 4915])
async def test_close_codes_4914_4915_are_fatal(code: int) -> None:
    """S3-17: sandbox/banned close codes must not reconnect forever."""

    async def handler(ws, server: ScriptedServer) -> None:
        await server.send(ws, hello())
        await server.recv(ws)
        await ws.close(code=code)

    async with ScriptedServer(handler) as server:
        bus = EventBus(concurrency=2)
        bus.start()
        client = GatewayClient(FakeTokens(), FakeGatewayAPI(server.url), make_config(), bus)
        with pytest.raises(GatewayError) as excinfo:
            await client.run()
        await bus.stop()

    assert excinfo.value.fatal
    assert server.connections == 1


async def test_close_code_4006_forces_full_identify() -> None:
    """S3-10/S3-18: after a dead session only Identify is allowed."""

    identified_again = asyncio.Event()
    saw_resume = False

    async def handler(ws, server: ScriptedServer) -> None:
        await server.send(ws, hello())
        first = await server.recv(ws)
        if server.connections == 1:
            assert first["op"] == 2
            await server.send(ws, ready("session-doomed"))
            await ws.close(code=4006)
            return
        # Any later connection must Identify again, never Resume.
        assert first["op"] == 2, f"expected Identify, got op={first['op']}"
        identified_again.set()

    async with ScriptedServer(handler) as server:
        bus = EventBus(concurrency=2)
        bus.start()
        client = GatewayClient(FakeTokens(), FakeGatewayAPI(server.url), make_config(), bus)
        await run_until(client, identified_again)
        await bus.stop()

    assert not saw_resume
    assert client.session_id is None


async def test_invalid_session_resumable_resumes_session() -> None:
    """S3-09 (resumable branch): op9 d=true keeps the session via Resume."""

    resumed = asyncio.Event()

    async def handler(ws, server: ScriptedServer) -> None:
        await server.send(ws, hello())
        first = await server.recv(ws)
        if server.connections == 1:
            assert first["op"] == 2
            await server.send(ws, ready("session-resume-me", seq=5))
            await server.send(
                ws,
                {
                    "op": 0,
                    "s": 6,
                    "t": "GROUP_ADD_ROBOT",
                    "id": "evt-1",
                    "d": {"group_openid": "G"},
                },
            )
            await server.send(ws, {"op": 9, "d": True})
            with contextlib.suppress(ConnectionClosed):
                await ws.wait_closed()
            return
        assert first["op"] == 6, f"expected Resume, got op={first['op']}"
        assert first["d"]["session_id"] == "session-resume-me"
        assert first["d"]["seq"] == 6
        await server.send(ws, {"op": 0, "s": 7, "t": "RESUMED", "d": ""})
        resumed.set()

    async with ScriptedServer(handler) as server:
        bus = EventBus(concurrency=2)
        bus.start()
        client = GatewayClient(FakeTokens(), FakeGatewayAPI(server.url), make_config(), bus)
        await run_until(client, resumed)
        await bus.stop()

    assert client.session_id == "session-resume-me"


async def test_invalid_session_fatal_requires_identify() -> None:
    """S3-09 (fatal branch): op9 d=false drops the session and re-Identifies."""

    identified_again = asyncio.Event()

    async def handler(ws, server: ScriptedServer) -> None:
        await server.send(ws, hello())
        first = await server.recv(ws)
        if server.connections == 1:
            assert first["op"] == 2
            await server.send(ws, ready("session-gone"))
            await server.send(ws, {"op": 9, "d": False})
            with contextlib.suppress(ConnectionClosed):
                await ws.wait_closed()
            return
        assert first["op"] == 2, "must Identify again after a non-resumable invalid session"
        identified_again.set()

    async with ScriptedServer(handler) as server:
        bus = EventBus(concurrency=2)
        bus.start()
        client = GatewayClient(FakeTokens(), FakeGatewayAPI(server.url), make_config(), bus)
        await run_until(client, identified_again)
        await bus.stop()


async def test_heartbeat_ack_timeout_triggers_reconnect() -> None:
    """S3-07: missing heartbeat ACKs must close and reconnect the shard."""

    reconnected = asyncio.Event()

    async def handler(ws, server: ScriptedServer) -> None:
        await server.send(ws, hello(interval_ms=50))  # clamped up to 0.05s
        await server.recv(ws)  # identify
        if server.connections == 1:
            # Never ACK heartbeats on the first connection.
            with contextlib.suppress(ConnectionClosed):
                await ws.wait_closed()
            return
        await server.send(ws, ready())
        reconnected.set()

    async with ScriptedServer(handler) as server:
        bus = EventBus(concurrency=2)
        bus.start()
        client = GatewayClient(FakeTokens(), FakeGatewayAPI(server.url), make_config(), bus)
        await run_until(client, reconnected, limit=10)
        await bus.stop()

    assert server.connections >= 2


async def test_hostile_heartbeat_interval_is_clamped() -> None:
    """S3-08: a manipulated heartbeat_interval cannot flood or stall the link."""

    heartbeat_times: list[float] = []
    saw_two_beats = asyncio.Event()

    async def handler(ws, server: ScriptedServer) -> None:
        # 1 ms interval would flood the server if unclamped; the client must
        # slow it to heartbeat_min_interval.
        await server.send(ws, hello(interval_ms=1))
        await server.recv(ws)
        await server.send(ws, ready())
        while len(heartbeat_times) < 3:
            frame = await server.recv(ws, limit=5)
            if isinstance(frame, dict) and frame.get("op") == 1:
                heartbeat_times.append(time.monotonic())
        saw_two_beats.set()

    async with ScriptedServer(handler) as server:
        bus = EventBus(concurrency=2)
        bus.start()
        client = GatewayClient(FakeTokens(), FakeGatewayAPI(server.url), make_config(), bus)
        await run_until(client, saw_two_beats, limit=15)
        await bus.stop()

    assert client.stats["events_dispatched"] >= 1  # READY went through
    gaps = [b - a for a, b in zip(heartbeat_times, heartbeat_times[1:], strict=False)]
    assert gaps, "expected at least two heartbeats"
    assert min(gaps) >= 0.04, f"heartbeats faster than the configured floor: {gaps}"
    assert max(gaps) <= 1.0, f"heartbeats unreasonably slow: {gaps}"


async def test_identify_carries_no_token_in_headers() -> None:
    """S3-05: the access token travels only inside the Identify payload."""

    request_headers: dict[str, str] = {}
    got_identify = asyncio.Event()

    async def handler(ws, server: ScriptedServer) -> None:
        request_headers.update(dict(ws.request.headers))
        await server.send(ws, hello())
        identify = await server.recv(ws)
        assert identify["op"] == 2
        assert identify["d"]["token"] == "QQBot secret-token-value"
        got_identify.set()

    async with ScriptedServer(handler) as server:
        bus = EventBus(concurrency=2)
        bus.start()
        client = GatewayClient(FakeTokens(), FakeGatewayAPI(server.url), make_config(), bus)
        await run_until(client, got_identify)
        await bus.stop()

    flattened = " ".join(f"{k}: {v}" for k, v in request_headers.items()).lower()
    assert "token" not in flattened
    assert "authorization" not in flattened
    assert "secret-token-value" not in flattened


async def test_reconnect_attempts_are_bounded() -> None:
    """S4-02: exhausted reconnect attempts stop with a fatal GatewayError."""

    async def handler(ws, server: ScriptedServer) -> None:  # pragma: no cover
        # Hold the connections open; __aexit__ waits for handlers, so keep this
        # short enough that teardown stays fast.
        await asyncio.sleep(2.0)

    async with ScriptedServer(handler) as server:
        bus = EventBus(concurrency=2)
        bus.start()
        client = GatewayClient(
            FakeTokens(),
            FakeGatewayAPI(server.url),
            make_config(reconnect_max_attempts=2, open_timeout=0.1),
            bus,
        )
        start = time.monotonic()
        with pytest.raises(GatewayError) as excinfo:
            await client.run()
        elapsed = time.monotonic() - start
        await bus.stop()

    assert excinfo.value.fatal
    assert "reconnect limit" in str(excinfo.value)
    assert server.connections == 3
    assert elapsed < 10


def test_reconnect_backoff_is_exponential_with_cap() -> None:
    """S4-01: 1x, 2x, 4x ... capped at reconnect_max_delay."""

    from RayBot.core.gateway.ws import GatewayClient as _GC  # noqa: PLC0415

    config = make_config(reconnect_initial_delay=1.0, reconnect_max_delay=8.0)
    bus = EventBus(concurrency=1)
    client = _GC(FakeTokens(), FakeGatewayAPI("ws://127.0.0.1:1"), config, bus)
    observed = []
    for attempt in range(1, 7):
        client._attempt = attempt
        delay = client._backoff_delay()
        expected_base = min(8.0, 1.0 * 2 ** (attempt - 1))
        assert expected_base * 0.8 <= delay <= expected_base * 1.2
        observed.append(delay)
    # Once capped, the base stays at 8s.
    assert max(observed) <= 8.0 * 1.2


def test_gateway_url_allowlist_matrix() -> None:
    """S5-05 (unit): scheme and host validation for gateway URLs."""

    official = ("qq.com",)

    def trusted(url: str, **kwargs: object) -> bool:
        kwargs.setdefault("allowed_host_suffixes", official)
        return is_trusted_gateway_url(url, **kwargs)[0]  # type: ignore[arg-type]

    # Official endpoint shape (suffix match on qq.com).
    assert trusted("wss://api.sgroup.qq.com/websocket")
    assert trusted("wss://sandbox.api.sgroup.qq.com/websocket")
    # Loopback is allowed for local test servers, ws or wss.
    assert trusted("ws://127.0.0.1:9000")
    assert trusted("wss://localhost:9000")
    # Anything else fails closed.
    assert not trusted("ws://192.168.1.10:9000")
    assert not trusted("wss://evil.example.com/websocket")
    assert not trusted("http://api.sgroup.qq.com/websocket")
    assert not trusted("wss://user:pass@api.sgroup.qq.com/websocket")
    assert not trusted("wss://qq.com.attacker.example/websocket")
    assert not trusted("wss://attacker.example/qq.com")
    # Extensions: allow_insecure_ws relaxes the scheme only — the host must
    # still match the allowlist (fail closed).
    assert trusted("wss://gateway.internal.example/ws", allowed_host_suffixes=("internal.example",))
    assert trusted("ws://api.sgroup.qq.com/websocket", allow_insecure_ws=True)
    assert not trusted("ws://10.0.0.5:9000", allow_insecure_ws=True)


async def test_malicious_gateway_url_fails_closed() -> None:
    """S5-05 (dynamic): a hostile API response must not receive the token."""

    class HostileAPI:
        async def get(self) -> GatewayInfo:
            return GatewayInfo(
                url="wss://attacker.example/websocket",
                shards=1,
                session_start_limit=SessionStartLimit(max_concurrency=1),
            )

    bus = EventBus(concurrency=2)
    bus.start()
    client = GatewayClient(FakeTokens(), HostileAPI(), make_config(), bus)
    with pytest.raises(GatewayError) as excinfo:
        await client.run()
    await bus.stop()

    assert excinfo.value.fatal
    assert "gateway URL rejected" in str(excinfo.value)
