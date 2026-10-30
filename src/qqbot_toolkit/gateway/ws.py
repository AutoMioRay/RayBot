"""WebSocket gateway client with heartbeat, resume and sharding."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
from collections.abc import Mapping
from typing import Any

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, WebSocketException

from .._json import dumps, loads
from ..api.gateway import GatewayAPI
from ..auth import TokenManager
from ..config import GatewayConfig
from ..constants import (
    FATAL_CLOSE_CODES,
    IDENTIFY_REQUIRED_CLOSE_CODES,
    RESUME_ALLOWED_CLOSE_CODES,
    OpCode,
)
from ..errors import GatewayError, PayloadError
from ..events.bus import EventBus
from ..events.dedup import Deduplicator
from ..events.payload import GatewayPayload
from ..models.common import GatewayInfo
from ..models.events import event_dedup_key, parse_event
from ..net import is_trusted_gateway_url

logger = logging.getLogger(__name__)


class _Reconnect(Exception):
    def __init__(self, resume: bool, reason: str) -> None:
        super().__init__(reason)
        self.resume = resume
        self.reason = reason


class _Fatal(Exception):
    def __init__(self, reason: str, code: int | None = None) -> None:
        super().__init__(reason)
        self.code = code


class GatewayClient:
    """One WebSocket connection for a single shard.

    Responsibilities:
        * fetch the WSS URL and open the connection;
        * perform Identify or Resume;
        * send heartbeats and detect a missing ACK;
        * reconnect with exponential backoff, resuming the session when allowed;
        * parse dispatched events and hand them to the event bus.
    """

    def __init__(
        self,
        token_manager: TokenManager,
        gateway_api: GatewayAPI,
        config: GatewayConfig,
        bus: EventBus,
        deduplicator: Deduplicator | None = None,
        *,
        shard: tuple[int, int] | None = None,
        connect_gate: asyncio.Semaphore | None = None,
        gateway_info: GatewayInfo | None = None,
    ) -> None:
        self._tokens = token_manager
        self._gateway_api = gateway_api
        self._config = config
        self._bus = bus
        self._dedup = deduplicator
        self._shard = shard or config.shard
        self._gate = connect_gate
        self._gate_held = False
        self._gateway_info = gateway_info

        self._session_id: str | None = None
        self._seq: int | None = None
        self._attempt = 0
        self._closed = False
        self._stop_event = asyncio.Event()
        self._ack = asyncio.Event()
        self._ack.set()
        self._ws: ClientConnection | None = None
        self._events_received = 0
        self._events_dispatched = 0
        self._duplicates_ignored = 0
        self._invalid_payloads = 0

    @property
    def shard(self) -> tuple[int, int]:
        return self._shard

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def stats(self) -> Mapping[str, int]:
        """Connection counters for lightweight latency/health observation."""

        return {
            "events_received": self._events_received,
            "events_dispatched": self._events_dispatched,
            "duplicates_ignored": self._duplicates_ignored,
            "invalid_payloads": self._invalid_payloads,
        }

    async def run(self) -> None:
        """Run until :meth:`stop` is called or a fatal error occurs.

        Raises:
            GatewayError: On a fatal close code, invalid configuration, or when
                the reconnect limit is exhausted.
        """

        while not self._closed:
            resume = True
            reason = "connection closed"
            try:
                await self._connect_once()
            except _Fatal as exc:
                raise GatewayError(str(exc), close_code=exc.code, fatal=True) from exc
            except _Reconnect as exc:
                resume = exc.resume
                reason = exc.reason
            except asyncio.CancelledError:
                raise
            except ConnectionClosed as exc:
                code = _close_code(exc)
                if code in FATAL_CLOSE_CODES:
                    raise GatewayError(
                        f"gateway closed the connection: {exc.reason or 'fatal close code'}",
                        close_code=code,
                        fatal=True,
                    ) from exc
                if code in IDENTIFY_REQUIRED_CLOSE_CODES:
                    resume = False
                elif code in RESUME_ALLOWED_CLOSE_CODES:
                    resume = True
                else:
                    resume = self._session_id is not None and self._seq is not None
                reason = f"connection closed with code {code}"
            except (OSError, WebSocketException) as exc:
                resume = self._session_id is not None and self._seq is not None
                reason = f"{type(exc).__name__}: {exc}"

            if self._closed:
                break
            if not resume:
                self._session_id = None
                self._seq = None

            self._attempt += 1
            limit = self._config.reconnect_max_attempts
            if limit is not None and self._attempt > limit:
                raise GatewayError(
                    f"reconnect limit reached after {self._attempt - 1} retries: {reason}",
                    fatal=True,
                )

            delay = self._backoff_delay()
            logger.warning(
                "gateway shard %s/%s disconnected: %s; reconnecting in %.2fs (attempt %s)",
                self._shard[0],
                self._shard[1],
                reason,
                delay,
                self._attempt,
            )
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop_event.wait(), timeout=delay)

    async def stop(self) -> None:
        """Close the connection and stop the reconnect loop."""

        self._closed = True
        self._stop_event.set()
        ws = self._ws
        if ws is not None:
            with contextlib.suppress(Exception):
                await ws.close()

    async def _connect_once(self) -> None:
        # The gateway endpoint has a low rate limit.  Fetch it once per client
        # and reuse the URL for every Resume; the WSS endpoint is stable for the
        # lifetime of the process.
        if self._gateway_info is None:
            self._gateway_info = await self._gateway_api.get()
        info = self._gateway_info
        if not info.url:
            raise _Fatal("gateway endpoint returned an empty URL")
        trusted, reason = is_trusted_gateway_url(
            info.url,
            allowed_host_suffixes=self._config.allowed_gateway_hosts,
            allow_insecure_ws=self._config.allow_insecure_gateway_ws,
        )
        if not trusted:
            # A manipulated gateway URL would receive the access token inside
            # the Identify payload, so this fails closed instead of connecting.
            raise _Fatal(f"gateway URL rejected: {reason}")

        if self._gate is not None:
            await self._gate.acquire()
            self._gate_held = True

        options: dict[str, Any] = {
            "ping_interval": None,
            "open_timeout": self._config.open_timeout,
            "close_timeout": self._config.close_timeout,
            "max_size": self._config.max_message_size,
            "logger": logger,
        }
        if self._config.proxy is not None:
            options["proxy"] = self._config.proxy

        try:
            async with connect(info.url, **options) as ws:
                self._ws = ws
                hello = await asyncio.wait_for(ws.recv(), timeout=self._config.open_timeout)
                payload = self._decode(hello)
                if payload is None or payload.op != OpCode.HELLO:
                    raise _Reconnect(False, "first gateway payload was not Hello")
                interval = payload.heartbeat_interval or 45.0
                # A hostile or broken server must not be able to squeeze the
                # heartbeat loop (flooding) or stretch it beyond the platform
                # TTL (silent disconnects); QQ uses ~45s.
                interval = min(
                    max(interval, self._config.heartbeat_min_interval),
                    self._config.heartbeat_max_interval,
                )

                await self._authenticate(ws)
                heartbeat = asyncio.create_task(
                    self._heartbeat(ws, interval),
                    name=f"qqbot-heartbeat-{self._shard[0]}",
                )
                try:
                    while True:
                        message = await ws.recv()
                        decoded = self._decode(message)
                        if decoded is not None:
                            await self._handle(decoded, ws)
                finally:
                    heartbeat.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await heartbeat
        finally:
            self._ws = None
            self._release_gate()

    async def _authenticate(self, ws: ClientConnection) -> None:
        token = f"QQBot {await self._tokens.get_token()}"
        if self._session_id is not None and self._seq is not None:
            await self._send(
                ws,
                {
                    "op": OpCode.RESUME,
                    "d": {
                        "token": token,
                        "session_id": self._session_id,
                        "seq": self._seq,
                    },
                },
            )
            logger.info(
                "gateway shard %s/%s resuming session at seq %s",
                self._shard[0],
                self._shard[1],
                self._seq,
            )
            return

        await self._send(
            ws,
            {
                "op": OpCode.IDENTIFY,
                "d": {
                    "token": token,
                    "intents": int(self._config.intents),
                    "shard": [self._shard[0], self._shard[1]],
                    "properties": dict(self._config.properties),
                },
            },
        )
        logger.info(
            "gateway shard %s/%s identifying, intents=%s",
            self._shard[0],
            self._shard[1],
            int(self._config.intents),
        )

    async def _heartbeat(self, ws: ClientConnection, interval: float) -> None:
        while True:
            await asyncio.sleep(interval)
            self._ack.clear()
            try:
                await self._send(ws, {"op": OpCode.HEARTBEAT, "d": self._seq})
            except (ConnectionClosed, WebSocketException):
                return
            try:
                await asyncio.wait_for(
                    self._ack.wait(),
                    timeout=interval * self._config.heartbeat_timeout_factor,
                )
            except TimeoutError:
                logger.warning(
                    "gateway shard %s/%s heartbeat ACK timed out",
                    self._shard[0],
                    self._shard[1],
                )
                with contextlib.suppress(Exception):
                    await ws.close(code=4000, reason="heartbeat timeout")
                return

    async def _handle(self, payload: GatewayPayload, ws: ClientConnection) -> None:
        if payload.op == OpCode.DISPATCH:
            await self._dispatch(payload)
        elif payload.op == OpCode.HEARTBEAT:
            await self._send(ws, {"op": OpCode.HEARTBEAT, "d": self._seq})
        elif payload.op == OpCode.HEARTBEAT_ACK:
            self._ack.set()
        elif payload.op == OpCode.RECONNECT:
            raise _Reconnect(True, "server requested a reconnect")
        elif payload.op == OpCode.INVALID_SESSION:
            # d=true allows resuming the session after a fresh connection;
            # d=false means the session is gone and a full Identify is required.
            resumable = bool(payload.d)
            if resumable and self._session_id is not None and self._seq is not None:
                raise _Reconnect(True, "invalid session (resumable)")
            self._session_id = None
            self._seq = None
            raise _Reconnect(False, f"invalid session (resumable={resumable})")

    async def _dispatch(self, payload: GatewayPayload) -> None:
        if payload.s is not None:
            self._seq = payload.s
        name = payload.t or ""
        if not name:
            logger.debug("dispatch payload without an event name was ignored")
            return

        self._events_received += 1
        if name == "READY":
            data = payload.d if isinstance(payload.d, Mapping) else {}
            session_id = data.get("session_id")
            if session_id:
                self._session_id = str(session_id)
            self._attempt = 0
            self._release_gate()
        elif name == "RESUMED":
            self._attempt = 0
            self._release_gate()

        event = parse_event(
            name,
            payload.d if isinstance(payload.d, Mapping) else None,
            event_id=payload.id,
            seq=payload.s,
        )
        # READY and RESUMED are connection lifecycle signals, not replayable
        # events.  Their sequence numbers restart after Identify and must not be
        # suppressed by the delivery de-duplicator.
        if (
            self._dedup is not None
            and name not in {"READY", "RESUMED"}
            and self._dedup.is_duplicate(event_dedup_key(event))
        ):
            self._duplicates_ignored += 1
            logger.debug("duplicate event ignored: %s", name)
            return
        await self._bus.publish(event)
        self._events_dispatched += 1

    def _decode(self, message: str | bytes) -> GatewayPayload | None:
        try:
            data = loads(message)
            return GatewayPayload.from_dict(data)
        except (UnicodeDecodeError, ValueError, RecursionError, PayloadError) as exc:
            # RecursionError covers deeply nested JSON from the stdlib parser;
            # orjson raises a JSONDecodeError (a ValueError) on its depth limit.
            self._invalid_payloads += 1
            logger.warning("invalid gateway payload ignored: %s", exc)
            return None

    async def _send(self, ws: ClientConnection, payload: Mapping[str, Any]) -> None:
        await ws.send(dumps(payload))

    def _release_gate(self) -> None:
        if self._gate_held and self._gate is not None:
            self._gate_held = False
            self._gate.release()

    def _backoff_delay(self) -> float:
        exponent = min(self._attempt - 1, 10)
        base = min(
            self._config.reconnect_max_delay,
            self._config.reconnect_initial_delay * (2**exponent),
        )
        # Jitter avoids thundering-herd reconnects; not a security primitive.
        return base * random.uniform(0.8, 1.2)  # noqa: S311  # nosec B311


def _close_code(exc: ConnectionClosed) -> int | None:
    """Return the close code without the deprecated ``ConnectionClosed.code``."""

    received = getattr(exc, "rcvd", None)
    if received is not None:
        return received.code
    sent = getattr(exc, "sent", None)
    if sent is not None:
        return sent.code
    return None


class ShardManager:
    """Create and supervise one :class:`GatewayClient` per shard."""

    def __init__(
        self,
        token_manager: TokenManager,
        gateway_api: GatewayAPI,
        config: GatewayConfig,
        bus: EventBus,
        deduplicator: Deduplicator | None = None,
    ) -> None:
        self._tokens = token_manager
        self._gateway_api = gateway_api
        self._config = config
        self._bus = bus
        self._dedup = deduplicator
        self._clients: list[GatewayClient] = []
        self._task: asyncio.Task[None] | None = None

    @property
    def clients(self) -> tuple[GatewayClient, ...]:
        return tuple(self._clients)

    async def run(self) -> None:
        """Discover the shard count and run every shard until stopped."""

        info = await self._gateway_api.get()
        if self._config.shard_count is not None:
            count = self._config.shard_count
        elif self._config.auto_shard:
            count = info.shards
        else:
            count = 1
        count = max(1, count)

        gate = asyncio.Semaphore(info.session_start_limit.max_concurrency) if count > 1 else None
        self._clients = [
            GatewayClient(
                self._tokens,
                self._gateway_api,
                self._config,
                self._bus,
                self._dedup,
                shard=(index, count),
                connect_gate=gate,
                gateway_info=info,
            )
            for index in range(count)
        ]
        logger.info("starting gateway with %s shard(s)", count)
        try:
            await asyncio.gather(*(client.run() for client in self._clients))
        finally:
            self._clients.clear()

    def start(self) -> asyncio.Task[None]:
        """Start :meth:`run` in a background task and return it."""

        if self._task is not None and not self._task.done():
            return self._task
        self._task = asyncio.create_task(self.run(), name="qqbot-gateway")
        self._task.add_done_callback(_log_supervisor_result)
        return self._task

    async def stop(self) -> None:
        """Stop every shard and wait for the supervisor task."""

        for client in self._clients:
            with contextlib.suppress(Exception):
                await client.stop()
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


def _log_supervisor_result(task: asyncio.Task[None]) -> None:
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        logger.error("gateway supervisor stopped: %s", error)


__all__ = ["GatewayClient", "ShardManager"]
