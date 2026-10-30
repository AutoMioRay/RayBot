"""Low-level authenticated HTTP client for the QQ OpenAPI."""

from __future__ import annotations

import asyncio
import email.utils
import logging
import random
import time
from collections.abc import Mapping
from typing import Any

import httpx

from .._json import dumps as _json_dumps
from .._json import loads as _json_loads
from ..auth import TokenManager
from ..config import HTTPConfig
from ..errors import APIError, AuthenticationError, error_from_body
from .ratelimit import RateLimitRegistry

logger = logging.getLogger(__name__)

JSON_HEADERS = {
    "Content-Type": "application/json; charset=utf-8",
    "Accept": "application/json",
}


class APIClient:
    """Authenticated, rate-limited JSON client.

    A single instance is shared by every API group.  The underlying
    :class:`httpx.AsyncClient` owns a keep-alive connection pool, so concurrent
    requests reuse sockets instead of reconnecting.
    """

    def __init__(
        self,
        token_manager: TokenManager,
        config: HTTPConfig | None = None,
        *,
        limiter: RateLimitRegistry | None = None,
        http_client: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._tokens = token_manager
        self._config = config or HTTPConfig()
        self._limiter = limiter or RateLimitRegistry(
            enabled=self._config.enforce_rate_limits,
            relation_enabled=self._config.enforce_relation_limits,
        )
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(
            base_url=self._config.normalized_base_url,
            timeout=httpx.Timeout(self._config.timeout, connect=self._config.connect_timeout),
            limits=httpx.Limits(
                max_connections=self._config.max_connections,
                max_keepalive_connections=self._config.max_keepalive_connections,
            ),
            headers={"User-Agent": self._config.user_agent},
            http2=self._config.http2,
            trust_env=self._config.trust_env,
            follow_redirects=True,
            transport=transport,
        )

    @property
    def config(self) -> HTTPConfig:
        return self._config

    @property
    def limiter(self) -> RateLimitRegistry:
        return self._limiter

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        route: str | None = None,
        relation_scope: str | None = None,
        relation_key: str | None = None,
        request_timeout: float | None = None,
        max_retries: int | None = None,
    ) -> Any:
        """Perform one JSON request and return the decoded response body.

        Args:
            method: HTTP method.
            path: Path beginning with ``/`` or an absolute URL.
            json: JSON body. ``None`` values are removed so optional fields are
                omitted rather than sent as ``null``.
            params: Query parameters; ``None`` values are removed.
            headers: Additional headers.
            route: Rate-limit route name.
            relation_scope: Active-message bucket scope, if applicable.
            relation_key: User or group OpenID for the relation bucket.
            request_timeout: Override the configured request timeout.
            max_retries: Override ``http.max_retries``.

        Returns:
            Parsed JSON when the response has a JSON body, otherwise text, or
            ``None`` for an empty body.

        Raises:
            APIError: When the platform reports a business or HTTP error.
            AuthenticationError: When the access token is rejected.
        """

        if route:
            await self._limiter.acquire(
                route,
                relation_scope=relation_scope,
                relation_key=relation_key,
            )

        retries = self._config.max_retries if max_retries is None else max_retries
        attempt = 0
        reauth_attempted = False
        request_headers = dict(JSON_HEADERS)
        if headers:
            request_headers.update(headers)
        clean_params = (
            {key: value for key, value in params.items() if value is not None} if params else None
        )
        clean_json = (
            {key: value for key, value in json.items() if value is not None}
            if json is not None
            else None
        )
        # Serialize the body once so retries reuse the exact same bytes instead
        # of re-encoding on every attempt.  ``content=`` skips httpx's internal
        # json.dumps; the Content-Type header is already part of JSON_HEADERS.
        body = _json_dumps(clean_json) if clean_json is not None else None

        while True:
            token = await self._tokens.get_token()
            request_headers["Authorization"] = f"QQBot {token}"
            debug_enabled = logger.isEnabledFor(logging.DEBUG)
            started = time.perf_counter() if debug_enabled else 0.0
            try:
                response = await self._client.request(
                    method,
                    path,
                    content=body,
                    params=clean_params,
                    headers=request_headers,
                    timeout=request_timeout,
                )
            except httpx.RequestError as exc:
                if attempt >= retries:
                    raise APIError(
                        f"HTTP request failed: {exc.__class__.__name__}",
                        method=method.upper(),
                        path=path,
                    ) from exc
                delay = self._backoff(attempt)
                logger.warning(
                    "request transport error, retrying in %.2fs: %s %s (%s)",
                    delay,
                    method.upper(),
                    path,
                    exc.__class__.__name__,
                )
                attempt += 1
                await asyncio.sleep(delay)
                continue

            if debug_enabled:
                elapsed_ms = (time.perf_counter() - started) * 1000
                logger.debug(
                    "%s %s -> %s %.1fms", method.upper(), path, response.status_code, elapsed_ms
                )

            if response.status_code == 401 and not reauth_attempted:
                reauth_attempted = True
                await self._tokens.invalidate(token)
                logger.warning("access token rejected, refreshing and retrying once")
                continue

            if response.status_code in {429, 500, 502, 503, 504} and attempt < retries:
                delay = self._retry_delay(response, attempt)
                logger.warning(
                    "HTTP %s, retrying in %.2fs: %s %s",
                    response.status_code,
                    delay,
                    method.upper(),
                    path,
                )
                attempt += 1
                await asyncio.sleep(delay)
                continue

            return self._decode(response, method=method, path=path)

    async def get(self, path: str, **kwargs: Any) -> Any:
        """Send a GET request."""

        return await self.request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> Any:
        """Send a POST request."""

        return await self.request("POST", path, **kwargs)

    async def put(self, path: str, **kwargs: Any) -> Any:
        """Send a PUT request."""

        return await self.request("PUT", path, **kwargs)

    async def patch(self, path: str, **kwargs: Any) -> Any:
        """Send a PATCH request."""

        return await self.request("PATCH", path, **kwargs)

    async def delete(self, path: str, **kwargs: Any) -> Any:
        """Send a DELETE request."""

        return await self.request("DELETE", path, **kwargs)

    def _decode(self, response: httpx.Response, *, method: str, path: str) -> Any:
        trace_id = response.headers.get("X-Tps-trace-ID") or response.headers.get("X-Tps-Trace-Id")
        body = _parse_body(response)

        if not 200 <= response.status_code < 300:
            if isinstance(body, dict):
                raise error_from_body(
                    body,
                    status=response.status_code,
                    method=method.upper(),
                    path=path,
                    trace_id=trace_id,
                )
            message = (
                f"request failed with HTTP {response.status_code}"
                if not body
                else f"request failed with HTTP {response.status_code}: {str(body)[:300]}"
            )
            exc_type = AuthenticationError if response.status_code == 401 else APIError
            raise exc_type(
                message,
                status=response.status_code,
                trace_id=trace_id,
                method=method.upper(),
                path=path,
                body=body,
            )

        if isinstance(body, dict):
            err_code = body.get("err_code")
            if err_code not in (None, 0, "0"):
                raise error_from_body(
                    body,
                    status=response.status_code,
                    method=method.upper(),
                    path=path,
                    trace_id=trace_id,
                )
        return body

    def _retry_delay(self, response: httpx.Response, attempt: int) -> float:
        value = response.headers.get("Retry-After")
        if value:
            value = value.strip()
            try:
                return max(0.0, float(value))
            except ValueError:
                parsed = email.utils.parsedate_to_datetime(value)
                if parsed is not None:
                    return max(0.0, parsed.timestamp() - time.time())
        return self._backoff(attempt)

    def _backoff(self, attempt: int) -> float:
        base = min(
            self._config.retry_max_delay,
            self._config.retry_base_delay * (2**attempt),
        )
        # Jitter prevents synchronized retry waves; not a security primitive.
        return base + random.uniform(0.0, self._config.retry_base_delay)  # noqa: S311  # nosec B311

    async def aclose(self) -> None:
        """Close the internally owned HTTP client."""

        if self._owns_client:
            await self._client.aclose()


def _parse_body(response: httpx.Response) -> Any:
    if response.status_code == 204 or not response.content:
        return None
    content_type = response.headers.get("Content-Type", "")
    if "json" in content_type or response.content.lstrip()[:1] in (b"{", b"["):
        try:
            # orjson accepts bytes directly, skipping the str decode that
            # response.text/response.json() would perform.
            return _json_loads(response.content)
        except (ValueError, UnicodeDecodeError):
            return response.text
    return response.text


__all__ = ["APIClient"]
