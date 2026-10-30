"""Exception hierarchy for the toolkit."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class QQBotError(Exception):
    """Base class for every error raised by :mod:`qqbot_toolkit`."""


class ConfigurationError(QQBotError):
    """Raised when a configuration value is missing or invalid."""


class APIError(QQBotError):
    """A failed OpenAPI call.

    QQ returns ``err_code`` inside the JSON body for business failures and may
    return a non-2xx HTTP status for transport or authentication failures.
    Both are retained so callers can make a decision without parsing strings.
    """

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        err_code: int | str | None = None,
        trace_id: str | None = None,
        method: str | None = None,
        path: str | None = None,
        body: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.err_code = err_code
        self.trace_id = trace_id
        self.method = method
        self.path = path
        self.body = body

    def __str__(self) -> str:
        parts = [self.message]
        if self.method and self.path:
            parts.append(f"{self.method} {self.path}")
        if self.status is not None:
            parts.append(f"http_status={self.status}")
        if self.err_code is not None:
            parts.append(f"err_code={self.err_code}")
        if self.trace_id:
            parts.append(f"trace_id={self.trace_id}")
        return " | ".join(parts)

    @property
    def is_rate_limited(self) -> bool:
        return self.status == 429 or self.err_code in {
            1100100,
            20028,
            40034100,
            40054005,
        }

    @property
    def is_auth_error(self) -> bool:
        return self.status == 401 or self.err_code in {
            11241,
            11243,
            11251,
            11253,
            11254,
            11262,
            11265,
            40011030,
            40012010,
            40034105,
        }

    @property
    def is_retryable(self) -> bool:
        return self.status in {429, 500, 502, 503, 504} or (
            isinstance(self.err_code, int) and 500 <= self.err_code < 600
        )


class AuthenticationError(APIError):
    """Raised when an access token cannot be obtained or is rejected."""


class GatewayError(QQBotError):
    """Raised when the gateway connection enters an unrecoverable state."""

    def __init__(
        self,
        message: str,
        *,
        close_code: int | None = None,
        fatal: bool = False,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.close_code = close_code
        self.fatal = fatal

    def __str__(self) -> str:
        if self.close_code is None:
            return self.message
        return f"{self.message} | close_code={self.close_code}"


class PayloadError(QQBotError):
    """Raised when a gateway payload cannot be parsed."""


def error_from_body(
    body: Mapping[str, Any],
    *,
    status: int,
    method: str,
    path: str,
    trace_id: str | None,
) -> APIError:
    """Build the most specific :class:`APIError` for a failed response."""

    err_code = body.get("err_code", body.get("code"))
    message = str(body.get("message") or body.get("msg") or f"request failed with HTTP {status}")
    exc_type = AuthenticationError if status == 401 else APIError
    return exc_type(
        message,
        status=status,
        err_code=err_code,
        trace_id=trace_id or body.get("trace_id"),
        method=method,
        path=path,
        body=body,
    )
