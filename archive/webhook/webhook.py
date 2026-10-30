"""HTTP callback server for QQ Webhook events."""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
import time
from collections import OrderedDict
from collections.abc import Mapping
from typing import Any

from aiohttp import web

from ..config import WebhookConfig
from ..constants import OpCode
from ..errors import ConfigurationError, PayloadError
from ..events.bus import EventBus
from ..events.dedup import Deduplicator
from ..events.payload import GatewayPayload
from ..models.events import event_dedup_key, parse_event
from ..net import (
    IPNetwork,
    ip_in_networks,
    is_loopback_host,
    parse_ip,
    parse_networks,
    resolve_client_ip,
)
from .signature import (
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    validation_response,
    verify_webhook_signature,
)

logger = logging.getLogger(__name__)

FORWARDED_FOR_HEADER = "X-Forwarded-For"


class _IPRateLimiter:
    """Small per-IP token bucket used before reading request bodies."""

    __slots__ = ("_rate", "_burst", "_max_ips", "_buckets")

    def __init__(self, rate: float, burst: int, max_ips: int) -> None:
        self._rate = rate
        self._burst = burst
        self._max_ips = max_ips
        self._buckets: OrderedDict[str, tuple[float, float]] = OrderedDict()

    def allow(self, key: str | None) -> bool:
        if self._rate <= 0 or self._burst < 1:
            return True
        bucket_key = key or "unknown"
        now = time.monotonic()
        tokens, updated = self._buckets.get(bucket_key, (float(self._burst), now))
        tokens = min(float(self._burst), tokens + (now - updated) * self._rate)
        allowed = tokens >= 1.0
        if allowed:
            tokens -= 1.0
        self._buckets[bucket_key] = (tokens, now)
        self._buckets.move_to_end(bucket_key)
        while len(self._buckets) > self._max_ips:
            self._buckets.popitem(last=False)
        return allowed


class WebhookServer:
    """Receive QQ callbacks over HTTP.

    Security controls, in the order they run:

    1. per-IP rate limiting (optional);
    2. inbound source-IP allowlist (optional but strongly recommended);
    3. Ed25519 signature verification before JSON parsing;
    4. timestamp freshness check (replay reduction);
    5. callback-validation toggle (``op=13``).

    Events are queued on the shared :class:`EventBus`, so WebSocket and Webhook
    deliveries use identical handlers.
    """

    def __init__(
        self,
        config: WebhookConfig,
        bus: EventBus,
        client_secret: str,
        deduplicator: Deduplicator | None = None,
    ) -> None:
        self._config = config
        self._bus = bus
        self._secret = client_secret
        self._dedup = deduplicator
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._background: set[asyncio.Task[None]] = set()
        self._allowed_networks: tuple[IPNetwork, ...] = parse_networks(config.allowed_ips)
        self._trusted_networks: tuple[IPNetwork, ...] = parse_networks(config.trusted_proxies)
        self._limiter = _IPRateLimiter(
            config.rate_limit_per_second,
            config.rate_limit_burst,
            config.rate_limit_max_ips,
        )
        self._validation_enabled = config.validation_enabled

    @property
    def validation_enabled(self) -> bool:
        """Whether ``op=13`` callback validation is currently accepted."""

        return self._validation_enabled

    def set_validation_enabled(self, enabled: bool) -> None:
        """Enable or disable the ``op=13`` validation endpoint at runtime.

        Disable it after the callback URL has been configured.  Re-enable it
        only when the console needs to validate the URL again.
        """

        self._validation_enabled = enabled

    def create_app(self) -> web.Application:
        """Build the aiohttp application for embedding in an existing server."""

        app = web.Application(client_max_size=self._config.max_body_size)
        app.router.add_post(self._config.path, self._handle)
        if self._config.health_path:
            app.router.add_get(self._config.health_path, self._health)
        return app

    async def start(self, *, ssl_context: ssl.SSLContext | None = None) -> None:
        """Bind the configured host and port and start accepting callbacks.

        QQ requires the callback port to be 80, 443, 8080 or 8443.  When TLS is
        terminated by a reverse proxy, keep the server on HTTP and expose it
        through that proxy.

        Raises:
            ConfigurationError: If ``webhook.require_tls`` is true and no
                ``ssl_context`` is provided.
        """

        if self._runner is not None:
            return
        if self._config.require_tls and ssl_context is None:
            raise ConfigurationError(
                "webhook.require_tls is enabled but start() received no ssl_context"
            )
        if ssl_context is None and not is_loopback_host(self._config.host):
            logger.warning(
                "webhook is listening without TLS on %s:%s; terminate TLS at a "
                "reverse proxy or pass ssl_context",
                self._config.host,
                self._config.port,
            )
        if self._config.verify_signature and not self._config.allowed_ips:
            logger.warning(
                "webhook.allowed_ips is empty; any source IP can reach the callback. "
                "Configure an inbound allowlist or use WebSocket."
            )
        runner = web.AppRunner(self.create_app(), access_log=logger)
        await runner.setup()
        site = web.TCPSite(
            runner,
            host=self._config.host,
            port=self._config.port,
            ssl_context=ssl_context,
        )
        await site.start()
        self._runner = runner
        self._site = site
        logger.info(
            "webhook listening on %s:%s%s",
            self._config.host,
            self._config.port,
            self._config.path,
        )

    async def stop(self) -> None:
        """Stop accepting callbacks and release the listening socket."""

        if self._site is not None:
            await self._site.stop()
            self._site = None
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
        if self._background:
            tasks = list(self._background)
            done, pending = await asyncio.wait(tasks, timeout=5)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        self._background.clear()

    async def _health(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    async def _handle(self, request: web.Request) -> web.Response:
        client_ip = resolve_client_ip(
            request.remote,
            request.headers.get(FORWARDED_FOR_HEADER),
            trust_forwarded_for=self._config.trust_forwarded_for,
            trusted_proxies=self._trusted_networks,
        )
        if not self._limiter.allow(client_ip):
            logger.warning("webhook rate limit exceeded for %s", client_ip)
            return web.json_response({"message": "rate limited"}, status=429)
        if self._allowed_networks:
            parsed_ip = parse_ip(client_ip)
            if not ip_in_networks(parsed_ip, self._allowed_networks):
                logger.warning("rejected webhook request from %s: not in allowed_ips", client_ip)
                return web.json_response({"message": "source IP not allowed"}, status=403)

        raw = await request.read()
        signature = request.headers.get(SIGNATURE_HEADER, "")
        timestamp = request.headers.get(TIMESTAMP_HEADER, "")

        # Verify before parsing for signed requests.  This keeps malformed or
        # hostile JSON from consuming parsing work before authentication.
        verified = False
        if self._config.verify_signature and signature and timestamp:
            if not verify_webhook_signature(self._secret, signature, timestamp, raw):
                logger.warning("rejected webhook request with an invalid signature")
                return web.json_response({"message": "invalid signature"}, status=401)
            if not _timestamp_is_fresh(timestamp, self._config.max_timestamp_skew):
                logger.warning("rejected webhook request with a stale timestamp")
                return web.json_response({"message": "stale timestamp"}, status=401)
            verified = True

        try:
            decoded = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return web.json_response({"message": "invalid JSON"}, status=400)
        if not isinstance(decoded, Mapping):
            return web.json_response({"message": "payload must be an object"}, status=400)
        try:
            payload = GatewayPayload.from_dict(decoded)
        except PayloadError as exc:
            return web.json_response({"message": str(exc)}, status=400)

        if payload.op == OpCode.CALLBACK_VALIDATION:
            if not self._validation_enabled:
                logger.warning("rejected callback validation: op=13 is disabled")
                return web.json_response({"message": "callback validation is disabled"}, status=403)
            return self._validate(payload)

        if self._config.verify_signature and not verified:
            logger.warning("rejected unsigned webhook request")
            return web.json_response({"message": "missing signature"}, status=401)

        if payload.op == OpCode.DISPATCH:
            await self._dispatch(payload)

        if self._config.ack_with_op12:
            return web.json_response({"op": int(OpCode.HTTP_CALLBACK_ACK), "d": {}})
        return web.json_response({})

    def _validate(self, payload: GatewayPayload) -> web.Response:
        data: Mapping[str, Any] = payload.d if isinstance(payload.d, Mapping) else {}
        plain_token = str(data.get("plain_token", ""))
        event_ts = str(data.get("event_ts", ""))
        if not plain_token or not event_ts:
            return web.json_response(
                {"message": "callback validation payload is incomplete"}, status=400
            )
        return web.json_response(validation_response(self._secret, plain_token, event_ts))

    async def _dispatch(self, payload: GatewayPayload) -> None:
        name = payload.t or ""
        if not name:
            return
        event = parse_event(
            name,
            payload.d if isinstance(payload.d, Mapping) else None,
            event_id=payload.id,
            seq=payload.s,
        )
        if self._dedup is not None and self._dedup.is_duplicate(event_dedup_key(event)):
            logger.debug("duplicate webhook event ignored: %s", name)
            return

        if self._config.dispatch_before_ack:
            await self._bus.publish(event)
            return

        task = asyncio.create_task(self._bus.publish(event), name="qqbot-webhook-dispatch")
        self._background.add(task)
        task.add_done_callback(self._dispatch_done)

    def _dispatch_done(self, task: asyncio.Task[None]) -> None:
        self._background.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.error("failed to enqueue webhook event: %s", error)


def _timestamp_is_fresh(timestamp: str, skew: float) -> bool:
    """Return whether a Unix-seconds (or milliseconds) timestamp is fresh."""

    if skew <= 0:
        return True
    try:
        value = float(timestamp)
    except (TypeError, ValueError):
        return False
    if value > 1e11:
        value /= 1000.0
    return abs(time.time() - value) <= skew


__all__ = ["WebhookServer"]
