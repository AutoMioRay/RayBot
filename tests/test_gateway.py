from __future__ import annotations

import asyncio
import contextlib
import json

import pytest
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from RayBot.core.config import GatewayConfig
from RayBot.core.errors import ConfigurationError
from RayBot.core.events import EventBus
from RayBot.core.gateway.ws import GatewayClient
from RayBot.core.models import GatewayInfo, SessionStartLimit


class FakeTokens:
    async def get_token(self, *, force_refresh: bool = False) -> str:
        return "token"


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


async def test_gateway_identifies_and_dispatches_typed_event() -> None:
    received: asyncio.Event = asyncio.Event()
    contents: list[str] = []
    identify_payload: dict = {}

    async def handler(ws) -> None:
        await ws.send(json.dumps({"op": 10, "d": {"heartbeat_interval": 60000}}))
        identify_payload.update(json.loads(await ws.recv()))
        await ws.send(
            json.dumps(
                {
                    "op": 0,
                    "s": 1,
                    "t": "READY",
                    "d": {
                        "version": 1,
                        "session_id": "session-1",
                        "user": {"id": "bot", "username": "bot", "bot": True},
                        "shard": [0, 1],
                    },
                }
            )
        )
        await ws.send(
            json.dumps(
                {
                    "op": 0,
                    "s": 2,
                    "t": "C2C_MESSAGE_CREATE",
                    "id": "event-1",
                    "d": {
                        "id": "message-1",
                        "author": {"user_openid": "U", "username": "tester"},
                        "content": "hello",
                        "message_type": 0,
                        "message_scene": {"ext": ["msg_idx=REF1"]},
                    },
                }
            )
        )
        with contextlib.suppress(ConnectionClosed):
            await ws.wait_closed()

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        bus = EventBus(concurrency=2, queue_size=8)
        bus.start()

        def on_message(event) -> None:
            contents.append(event.content)
            received.set()

        bus.subscribe("C2C_MESSAGE_CREATE", on_message)
        gateway_api = FakeGatewayAPI(f"ws://127.0.0.1:{port}")
        client = GatewayClient(
            FakeTokens(),
            gateway_api,
            GatewayConfig(reconnect_initial_delay=0.01, open_timeout=2.0),
            bus,
        )
        task = asyncio.create_task(client.run())
        try:
            await asyncio.wait_for(received.wait(), timeout=5)
        finally:
            await client.stop()
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=5)
            await bus.drain()
            await bus.stop()

    assert contents == ["hello"]
    assert identify_payload["op"] == 2
    assert identify_payload["d"]["token"] == "QQBot token"
    assert identify_payload["d"]["shard"] == [0, 1]


async def test_decode_ignores_malformed_json() -> None:
    bus = EventBus(concurrency=1)
    bus.start()
    client = GatewayClient(FakeTokens(), FakeGatewayAPI("ws://127.0.0.1:1"), GatewayConfig(), bus)
    assert client._decode("{not-json") is None
    assert client._decode('{"op": 11}') is not None
    await bus.stop()


def test_config_rejects_invalid_shard() -> None:
    with pytest.raises(ConfigurationError):
        GatewayConfig(shard=(2, 2))


async def test_gateway_url_is_fetched_once_across_reconnects() -> None:
    connections = 0
    resumed = asyncio.Event()

    async def handler(ws) -> None:
        nonlocal connections
        connections += 1
        await ws.send(json.dumps({"op": 10, "d": {"heartbeat_interval": 60000}}))
        if connections == 1:
            identify = json.loads(await ws.recv())
            assert identify["op"] == 2
            await ws.send(
                json.dumps(
                    {
                        "op": 0,
                        "s": 1,
                        "t": "READY",
                        "d": {
                            "version": 1,
                            "session_id": "session-resume",
                            "user": {"id": "bot", "username": "bot", "bot": True},
                            "shard": [0, 1],
                        },
                    }
                )
            )
            await ws.close(code=4009)
            return

        resume = json.loads(await ws.recv())
        assert resume["op"] == 6
        assert resume["d"]["session_id"] == "session-resume"
        await ws.send(json.dumps({"op": 0, "s": 2, "t": "RESUMED", "d": ""}))
        with contextlib.suppress(ConnectionClosed):
            await ws.wait_closed()

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        bus = EventBus(concurrency=2, queue_size=8)
        bus.start()
        bus.subscribe("RESUMED", lambda event: resumed.set())
        gateway_api = FakeGatewayAPI(f"ws://127.0.0.1:{port}")
        client = GatewayClient(
            FakeTokens(),
            gateway_api,
            GatewayConfig(
                reconnect_initial_delay=0.01,
                reconnect_max_attempts=3,
                open_timeout=2.0,
            ),
            bus,
        )
        task = asyncio.create_task(client.run())
        try:
            await asyncio.wait_for(resumed.wait(), timeout=5)
        finally:
            await client.stop()
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=5)
            await bus.drain()
            await bus.stop()

    assert connections == 2
    assert gateway_api.calls == 1
