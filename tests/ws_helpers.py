"""Programmable WebSocket gateway server for protocol-level security tests."""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

Handler = Callable[[ServerConnection, "ScriptedServer"], Awaitable[None]]


class ScriptedServer:
    """One listening WebSocket server with scripted per-connection behavior.

    ``handler`` runs for every incoming connection and drives the exchange:
    it receives the client frames via :meth:`recv` and can send arbitrary
    payloads (including deliberately malformed ones).
    """

    def __init__(self, handler: Handler) -> None:
        self._handler = handler
        self._server = None
        self.connections = 0
        self.received: list[Any] = []

    @property
    def url(self) -> str:
        assert self._server is not None and self._server.sockets
        port = self._server.sockets[0].getsockname()[1]
        return f"ws://127.0.0.1:{port}"

    async def __aenter__(self) -> ScriptedServer:
        self._server = await serve(self._serve, "127.0.0.1", 0)
        return self

    async def __aexit__(self, *exc: Any) -> None:
        assert self._server is not None
        self._server.close()
        await self._server.wait_closed()

    async def _serve(self, ws: ServerConnection) -> None:
        self.connections += 1
        await self._handler(ws, self)

    async def recv(self, ws: ServerConnection, limit: float = 5.0) -> Any:
        raw = await asyncio.wait_for(ws.recv(), limit)
        self.received.append(raw)
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return raw

    @staticmethod
    async def send(ws: ServerConnection, payload: Any) -> None:
        if isinstance(payload, (bytes, bytearray)):
            await ws.send(payload)
        elif isinstance(payload, str):
            await ws.send(payload)
        else:
            await ws.send(json.dumps(payload))

    @staticmethod
    async def hold_open(ws: ServerConnection, seconds: float = 30.0) -> None:
        with contextlib.suppress(ConnectionClosed, asyncio.CancelledError):
            await asyncio.sleep(seconds)


@contextlib.asynccontextmanager
async def scripted_gateway(handler: Handler) -> AsyncIterator[ScriptedServer]:
    async with ScriptedServer(handler) as server:
        yield server


def hello(interval_ms: int = 60_000) -> dict[str, Any]:
    return {"op": 10, "d": {"heartbeat_interval": interval_ms}}


def ready(session_id: str = "session-1", seq: int = 1) -> dict[str, Any]:
    return {
        "op": 0,
        "s": seq,
        "t": "READY",
        "d": {
            "version": 1,
            "session_id": session_id,
            "user": {"id": "bot", "username": "bot", "bot": True},
            "shard": [0, 1],
        },
    }
