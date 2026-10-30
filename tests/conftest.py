"""Shared test helpers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

import httpx

from qqbot_toolkit import BotConfig, HTTPConfig

TOKEN_PATH = "/app/getAppAccessToken"


def token_response() -> httpx.Response:
    return httpx.Response(200, json={"access_token": "test-token", "expires_in": 7200})


def json_response(payload: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload)


def api_transport(callback: Callable[[httpx.Request], httpx.Response]) -> httpx.MockTransport:
    """Transport that serves the token endpoint and delegates everything else."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == TOKEN_PATH:
            return token_response()
        return callback(request)

    return httpx.MockTransport(handler)


def make_config(**http_overrides: Any) -> BotConfig:
    http = replace(
        HTTPConfig(),
        enforce_rate_limits=False,
        enforce_relation_limits=False,
        max_retries=0,
        retry_base_delay=0.0,
        retry_max_delay=0.0,
        **http_overrides,
    )
    return BotConfig(app_id="app", client_secret="secret", http=http)


class FakeTokens:
    """Token provider used by HTTP-client unit tests."""

    def __init__(self, value: str = "test-token") -> None:
        self.value = value
        self.invalidated: list[str | None] = []

    async def get_token(self, *, force_refresh: bool = False) -> str:
        return self.value

    async def invalidate(self, token: str | None = None) -> None:
        self.invalidated.append(token)
