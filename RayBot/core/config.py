"""Immutable configuration objects."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any
from urllib.parse import urlsplit

from .constants import (
    API_BASE_URL,
    DEFAULT_INTENTS,
    __version__,
)
from .errors import ConfigurationError
from .net import is_loopback_host


@dataclass(slots=True, frozen=True)
class HTTPConfig:
    """HTTP transport, retry and rate-limit settings."""

    base_url: str = API_BASE_URL
    timeout: float = 30.0
    connect_timeout: float = 10.0
    max_connections: int = 200
    max_keepalive_connections: int = 50
    max_retries: int = 2
    retry_base_delay: float = 0.4
    retry_max_delay: float = 8.0
    token_refresh_margin: float = 60.0
    user_agent: str = f"RayBot/{__version__}"
    enforce_rate_limits: bool = True
    enforce_relation_limits: bool = True
    http2: bool = False
    trust_env: bool = True
    allow_insecure_http: bool = False
    token_background_refresh: bool = True
    token_refresh_jitter: float = 0.1

    def __post_init__(self) -> None:
        parsed = urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ConfigurationError("http.base_url must be an absolute http:// or https:// URL")
        if parsed.username or parsed.password:
            raise ConfigurationError("http.base_url must not contain credentials")
        if (
            parsed.scheme == "http"
            and not self.allow_insecure_http
            and not is_loopback_host(parsed.hostname)
        ):
            raise ConfigurationError(
                "http.base_url must use https://; set http.allow_insecure_http=True "
                "only for trusted local endpoints"
            )
        if self.timeout <= 0 or self.connect_timeout <= 0:
            raise ConfigurationError("HTTP timeouts must be positive")
        if self.max_retries < 0:
            raise ConfigurationError("http.max_retries cannot be negative")
        if self.max_connections < 1:
            raise ConfigurationError("http.max_connections must be at least 1")
        if self.token_refresh_margin < 0:
            raise ConfigurationError("http.token_refresh_margin cannot be negative")
        if not 0.0 <= self.token_refresh_jitter <= 1.0:
            raise ConfigurationError("http.token_refresh_jitter must be between 0 and 1")

    @property
    def normalized_base_url(self) -> str:
        return self.base_url.rstrip("/")


@dataclass(slots=True, frozen=True)
class GatewayConfig:
    """WebSocket gateway and dispatch settings."""

    endpoint: str | None = None
    intents: int = int(DEFAULT_INTENTS)
    shard: tuple[int, int] = (0, 1)
    shard_count: int | None = None
    auto_shard: bool = False
    dispatch_concurrency: int = 64
    dispatch_queue_size: int = 2048
    dispatch_overflow: str = "block"
    dedup_ttl: float = 600.0
    dedup_max_size: int = 20_000
    reconnect_initial_delay: float = 1.0
    reconnect_max_delay: float = 60.0
    reconnect_max_attempts: int | None = None
    heartbeat_timeout_factor: float = 1.5
    heartbeat_min_interval: float = 1.0
    heartbeat_max_interval: float = 300.0
    open_timeout: float = 10.0
    close_timeout: float = 5.0
    max_message_size: int = 16 * 1024 * 1024
    proxy: str | bool | None = None
    allowed_gateway_hosts: tuple[str, ...] = ("qq.com",)
    allow_insecure_gateway_ws: bool = False
    properties: Mapping[str, str] = field(
        default_factory=lambda: {
            "$os": "python",
            "$browser": "RayBot",
            "$device": "RayBot",
        }
    )

    def __post_init__(self) -> None:
        shard_id, shard_total = self.shard
        if shard_total < 1 or not 0 <= shard_id < shard_total:
            raise ConfigurationError("gateway.shard must satisfy 0 <= id < count")
        if self.shard_count is not None and self.shard_count < 1:
            raise ConfigurationError("gateway.shard_count must be positive")
        if self.dispatch_concurrency < 1:
            raise ConfigurationError("gateway.dispatch_concurrency must be positive")
        if self.dispatch_queue_size < 1:
            raise ConfigurationError("gateway.dispatch_queue_size must be positive")
        if self.dispatch_overflow not in {"block", "drop"}:
            raise ConfigurationError("gateway.dispatch_overflow must be 'block' or 'drop'")
        if self.reconnect_initial_delay <= 0:
            raise ConfigurationError("gateway.reconnect_initial_delay must be positive")
        if self.reconnect_max_delay < self.reconnect_initial_delay:
            raise ConfigurationError(
                "gateway.reconnect_max_delay cannot be smaller than the initial delay"
            )
        if self.heartbeat_min_interval <= 0:
            raise ConfigurationError("gateway.heartbeat_min_interval must be positive")
        if self.heartbeat_max_interval < self.heartbeat_min_interval:
            raise ConfigurationError(
                "gateway.heartbeat_max_interval cannot be smaller than heartbeat_min_interval"
            )
        if any(not str(host).strip() for host in self.allowed_gateway_hosts):
            raise ConfigurationError("gateway.allowed_gateway_hosts contains an empty entry")


@dataclass(slots=True, frozen=True)
class BotConfig:
    """Top-level bot configuration."""

    app_id: str
    client_secret: str = field(repr=False)
    http: HTTPConfig = field(default_factory=HTTPConfig)
    gateway: GatewayConfig = field(default_factory=GatewayConfig)

    def __post_init__(self) -> None:
        _validate_credential("app_id", self.app_id, max_length=64)
        _validate_credential("client_secret", self.client_secret, max_length=256)

    @classmethod
    def from_env(cls, prefix: str = "QQBOT_") -> BotConfig:
        """Load credentials from environment variables.

        Recognized variables are ``QQBOT_APP_ID``, ``QQBOT_CLIENT_SECRET`` and
        optionally ``QQBOT_BASE_URL``.
        """

        app_id = os.getenv(f"{prefix}APP_ID", "")
        secret = os.getenv(f"{prefix}CLIENT_SECRET", "")
        base_url = os.getenv(f"{prefix}BASE_URL")
        http = replace(HTTPConfig(), base_url=base_url) if base_url else HTTPConfig()
        return cls(app_id=app_id, client_secret=secret, http=http)

    def with_overrides(self, **changes: Any) -> BotConfig:
        """Return a copy with selected fields replaced.

        Nested sections are replaced as whole objects; use :func:`dataclasses.replace`
        on the section first when only one nested value changes.
        """

        return replace(self, **changes)


def _validate_credential(name: str, value: str, *, max_length: int) -> None:
    """Reject empty, oversized or control-character-laden credentials.

    Control characters (including newlines) in credentials would otherwise be
    forwarded verbatim into JSON bodies and log lines.
    """

    if not value:
        raise ConfigurationError(f"{name} is required")
    if len(value) > max_length:
        raise ConfigurationError(f"{name} exceeds the maximum length of {max_length}")
    if value != value.strip():
        raise ConfigurationError(f"{name} must not start or end with whitespace")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise ConfigurationError(f"{name} must not contain control characters")


__all__ = ["BotConfig", "GatewayConfig", "HTTPConfig"]
