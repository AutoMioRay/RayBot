"""Access-token acquisition and caching."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

import httpx

from ._json import loads as _json_loads
from .config import HTTPConfig
from .errors import AuthenticationError

logger = logging.getLogger(__name__)

# API path, not a credential.
TOKEN_PATH = "/app/getAppAccessToken"  # noqa: S105  # nosec B105


@dataclass(slots=True, frozen=True)
class AccessToken:
    """A cached access token with its expiration timestamp."""

    value: str
    expires_at: float
    expires_in: int


@dataclass(slots=True, frozen=True)
class TokenStats:
    """Per-process token refresh counters.

    ``last_refresh_at`` uses ``time.monotonic()`` and is intended for latency
    calculations, not wall-clock display.
    """

    refresh_count: int = 0
    failure_count: int = 0
    last_refresh_at: float | None = None
    last_error: str | None = None


class TokenManager:
    """Fetch and cache ``access_token``.

    The manager is safe for concurrent use: a single refresh runs while every
    other coroutine waits on the same lock, avoiding a token stampede when many
    API calls start simultaneously.
    """

    def __init__(
        self,
        app_id: str,
        client_secret: str,
        config: HTTPConfig | None = None,
        *,
        http_client: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._app_id = app_id
        self._client_secret = client_secret
        self._config = config or HTTPConfig()
        self._token: AccessToken | None = None
        self._token_obtained_at = 0.0
        self._lock = asyncio.Lock()
        self._refresh_task: asyncio.Task[None] | None = None
        self._closed = False
        self._refresh_count = 0
        self._failure_count = 0
        self._last_refresh_at: float | None = None
        self._last_error: str | None = None
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(self._config.timeout, connect=self._config.connect_timeout),
            transport=transport,
            trust_env=self._config.trust_env,
            headers={"User-Agent": self._config.user_agent},
        )

    @property
    def token(self) -> str | None:
        """The cached token value, or ``None`` when no valid token exists."""

        token = self._token
        if token is None or time.monotonic() >= token.expires_at:
            return None
        return token.value

    async def get_token(self, *, force_refresh: bool = False) -> str:
        """Return a valid access token, refreshing it when necessary.

        Args:
            force_refresh: Ignore the cached value and request a new token.

        Raises:
            AuthenticationError: If the platform rejects the credentials or
                returns a response without ``access_token``.
        """

        if self._closed:
            raise RuntimeError("token manager is closed")
        requested_at = time.monotonic()
        if not force_refresh:
            cached = self.token
            if cached is not None:
                return cached

        async with self._lock:
            if self._closed:
                raise RuntimeError("token manager is closed")
            if not force_refresh:
                cached = self.token
                if cached is not None:
                    return cached
            # Single-flight for concurrent forced refreshes as well: if another
            # caller finished a refresh after this request started, reuse that
            # result instead of hammering the token endpoint once per caller.
            token = self._token
            if token is not None and self._token_obtained_at >= requested_at:
                return token.value
            return await self._refresh()

    async def invalidate(self, token: str | None = None) -> None:
        """Drop the cached token.

        Args:
            token: When given, the cache is cleared only if it still holds this
                value. This prevents a slow request from discarding a newer
                token that another coroutine just obtained.
        """

        async with self._lock:
            if token is None or (self._token and self._token.value == token):
                self._token = None

    @property
    def stats(self) -> TokenStats:
        """Return a snapshot of token refresh counters."""

        return TokenStats(
            refresh_count=self._refresh_count,
            failure_count=self._failure_count,
            last_refresh_at=self._last_refresh_at,
            last_error=self._last_error,
        )

    async def _refresh(self) -> str:
        try:
            value = await self._do_refresh()
        except Exception as exc:
            self._failure_count += 1
            self._last_error = str(exc)
            raise
        self._refresh_count += 1
        self._last_refresh_at = time.monotonic()
        self._last_error = None
        self._schedule_background_refresh()
        return value

    async def _do_refresh(self) -> str:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = await self._client.post(
                    f"{self._config.normalized_base_url}{TOKEN_PATH}",
                    json={"appId": self._app_id, "clientSecret": self._client_secret},
                    headers={"Content-Type": "application/json; charset=utf-8"},
                )
            except httpx.RequestError as exc:
                last_error = exc
                if attempt < 2:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                raise AuthenticationError("failed to reach the access-token endpoint") from exc

            body = _parse_body(response)
            if response.status_code >= 500 and attempt < 2:
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            if response.status_code == 429 and attempt < 2:
                await asyncio.sleep(1.0 * (attempt + 1))
                continue

            if response.status_code >= 400:
                raise _auth_error_from_body(body, response.status_code, "token request failed")
            if not isinstance(body, dict):
                raise AuthenticationError(
                    "access-token endpoint returned a non-object body",
                    status=response.status_code,
                    body=body,
                )
            value = body.get("access_token")
            if not value:
                raise _auth_error_from_body(
                    body, response.status_code, "access_token missing in response"
                )

            try:
                expires_in = int(body.get("expires_in", 7200))
            except (TypeError, ValueError):
                expires_in = 7200

            # Refresh early, but never throw away more than half of a short TTL.
            margin = min(self._config.token_refresh_margin, expires_in * 0.5)
            usable = max(float(expires_in) - margin, 1.0)
            self._token = AccessToken(
                value=str(value),
                expires_at=time.monotonic() + usable,
                expires_in=expires_in,
            )
            self._token_obtained_at = time.monotonic()
            logger.info("access token refreshed, expires_in=%ss", expires_in)
            return self._token.value

        raise AuthenticationError("failed to obtain an access token") from last_error

    def _schedule_background_refresh(self) -> None:
        if not self._config.token_background_refresh or self._closed:
            return
        token = self._token
        if token is None:
            return
        current = asyncio.current_task()
        previous = self._refresh_task
        if previous is not None and not previous.done() and previous is not current:
            previous.cancel()
        remaining = max(0.0, token.expires_at - time.monotonic())
        delay = max(1.0, remaining * 0.8)
        # Jitter avoids synchronized refresh storms; not a security primitive.
        delay *= 1.0 + random.uniform(0.0, self._config.token_refresh_jitter)  # noqa: S311  # nosec B311
        self._refresh_task = asyncio.create_task(
            self._background_refresh(delay), name="qqbot-token-refresh"
        )

    async def _background_refresh(self, delay: float) -> None:
        self._refresh_task = None
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        if self._closed:
            return
        try:
            await self.get_token(force_refresh=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("background access token refresh failed: %s", exc)
            if not self._closed:
                self._refresh_task = asyncio.create_task(
                    self._background_refresh(30.0),
                    name="qqbot-token-refresh-retry",
                )

    async def aclose(self) -> None:
        """Cancel background refresh and close the internally owned client."""

        self._closed = True
        task = self._refresh_task
        self._refresh_task = None
        if task is not None and not task.done():
            task.cancel()
            if task is not asyncio.current_task():
                with suppress(asyncio.CancelledError):
                    await task
        if self._owns_client:
            await self._client.aclose()
        self._token = None


def _parse_body(response: httpx.Response) -> Any:
    if not response.content:
        return None
    try:
        return _json_loads(response.content)
    except (ValueError, UnicodeDecodeError):
        return response.text


def _auth_error_from_body(body: Any, status: int, fallback: str) -> AuthenticationError:
    if isinstance(body, dict):
        message = str(body.get("message") or body.get("msg") or fallback)
        code = body.get("code", body.get("err_code"))
        trace_id = body.get("trace_id")
    else:
        message = fallback if not body else f"{fallback}: {str(body)[:200]}"
        code = None
        trace_id = None
    return AuthenticationError(
        message,
        status=status,
        err_code=code,
        trace_id=trace_id,
        body=body,
    )


__all__ = ["AccessToken", "TokenManager", "TokenStats"]
