from __future__ import annotations

import json

import httpx
import pytest

from RayBot.core.auth import AccessToken, TokenManager
from RayBot.core.config import HTTPConfig
from RayBot.core.errors import AuthenticationError

from .conftest import TOKEN_PATH


async def test_token_is_cached_between_calls() -> None:
    count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        assert request.url.path == TOKEN_PATH
        assert json.loads(request.content) == {"appId": "app", "clientSecret": "secret"}
        return httpx.Response(200, json={"access_token": "abc", "expires_in": 7200})

    manager = TokenManager(
        "app", "secret", HTTPConfig(max_retries=0), transport=httpx.MockTransport(handler)
    )
    assert await manager.get_token() == "abc"
    assert await manager.get_token() == "abc"
    assert count == 1
    await manager.aclose()


async def test_expired_token_is_refreshed() -> None:
    count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        return httpx.Response(200, json={"access_token": f"token-{count}", "expires_in": 7200})

    manager = TokenManager(
        "app", "secret", HTTPConfig(max_retries=0), transport=httpx.MockTransport(handler)
    )
    manager._token = AccessToken(value="expired", expires_at=0.0, expires_in=7200)
    assert await manager.get_token() == "token-1"
    assert await manager.get_token() == "token-1"
    assert count == 1
    await manager.aclose()


async def test_business_error_with_http_200_is_reported() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 100016, "message": "invalid appid or secret"})

    manager = TokenManager(
        "app", "wrong", HTTPConfig(max_retries=0), transport=httpx.MockTransport(handler)
    )
    with pytest.raises(AuthenticationError) as info:
        await manager.get_token()
    assert info.value.err_code == 100016
    await manager.aclose()


async def test_invalidate_only_clears_matching_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "abc", "expires_in": 7200})

    manager = TokenManager(
        "app", "secret", HTTPConfig(max_retries=0), transport=httpx.MockTransport(handler)
    )
    await manager.get_token()
    await manager.invalidate("other")
    assert await manager.get_token() == "abc"
    await manager.invalidate("abc")
    assert await manager.get_token() == "abc"
    await manager.aclose()


async def test_token_stats_and_background_task() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "abc", "expires_in": 7200})

    manager = TokenManager(
        "app",
        "secret",
        HTTPConfig(max_retries=0, token_background_refresh=True),
        transport=httpx.MockTransport(handler),
    )
    assert await manager.get_token() == "abc"
    assert manager.stats.refresh_count == 1
    assert manager.stats.failure_count == 0
    task = manager._refresh_task
    assert task is not None and not task.done()
    await manager.aclose()
    assert task.done()


async def test_background_refresh_can_be_disabled() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "abc", "expires_in": 7200})

    manager = TokenManager(
        "app",
        "secret",
        HTTPConfig(max_retries=0, token_background_refresh=False),
        transport=httpx.MockTransport(handler),
    )
    assert await manager.get_token() == "abc"
    assert manager._refresh_task is None
    await manager.aclose()


async def test_background_refresh_replaces_token() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"access_token": f"token-{calls}", "expires_in": 7200})

    manager = TokenManager(
        "app",
        "secret",
        HTTPConfig(max_retries=0, token_background_refresh=True),
        transport=httpx.MockTransport(handler),
    )
    assert await manager.get_token() == "token-1"
    await manager._background_refresh(0.01)
    assert await manager.get_token() == "token-2"
    assert manager.stats.refresh_count == 2
    await manager.aclose()
