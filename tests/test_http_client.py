from __future__ import annotations

import httpx
import pytest

from RayBot.core.config import HTTPConfig
from RayBot.core.errors import APIError
from RayBot.core.http import APIClient

from .conftest import FakeTokens


def config(**overrides) -> HTTPConfig:
    values = {
        "max_retries": 0,
        "enforce_rate_limits": False,
        "enforce_relation_limits": False,
        "retry_base_delay": 0.0,
        "retry_max_delay": 0.0,
    }
    values.update(overrides)
    return HTTPConfig(**values)


async def test_authorization_and_json_body_are_sent() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization")
        seen["content_type"] = request.headers.get("Content-Type")
        seen["body"] = request.content
        return httpx.Response(200, json={"ok": True})

    client = APIClient(FakeTokens(), config(), transport=httpx.MockTransport(handler))
    result = await client.post("/v2/test", json={"a": None, "b": 1})
    assert result == {"ok": True}
    assert seen["auth"] == "QQBot test-token"
    assert "application/json" in str(seen["content_type"])
    assert seen["body"] == b'{"b":1}'
    await client.aclose()


async def test_business_error_raises_api_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "err_code": 40034005,
                "message": "reply msg_id expired",
                "trace_id": "trace-1",
            },
            headers={"X-Tps-trace-ID": "trace-header"},
        )

    client = APIClient(FakeTokens(), config(), transport=httpx.MockTransport(handler))
    with pytest.raises(APIError) as info:
        await client.get("/v2/test")
    assert info.value.err_code == 40034005
    assert info.value.trace_id == "trace-header"
    assert info.value.status == 200
    await client.aclose()


async def test_retry_on_server_error() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(500, json={"err_code": 50001, "message": "temporary"})
        return httpx.Response(200, json={"ok": True})

    client = APIClient(FakeTokens(), config(max_retries=1), transport=httpx.MockTransport(handler))
    assert await client.get("/v2/test") == {"ok": True}
    assert calls == 2
    await client.aclose()


async def test_retry_after_header_is_honored() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={"err_code": 1100100})
        return httpx.Response(200, json={"ok": True})

    client = APIClient(FakeTokens(), config(max_retries=1), transport=httpx.MockTransport(handler))
    assert await client.get("/v2/test") == {"ok": True}
    assert calls == 2
    await client.aclose()


async def test_401_refreshes_token_once() -> None:
    tokens = FakeTokens()
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(401, json={"message": "unauthorized"})
        return httpx.Response(200, json={"ok": True})

    client = APIClient(tokens, config(), transport=httpx.MockTransport(handler))
    assert await client.get("/v2/test") == {"ok": True}
    assert tokens.invalidated == ["test-token"]
    assert calls == 2
    await client.aclose()


async def test_empty_204_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    client = APIClient(FakeTokens(), config(), transport=httpx.MockTransport(handler))
    assert await client.delete("/v2/test") is None
    await client.aclose()


def test_permission_error_codes_are_classified() -> None:
    assert APIError("no interface permission", err_code=40012010).is_auth_error
    assert APIError("not group admin", err_code=40011030).is_auth_error
    assert not APIError("target cannot be muted", err_code=40103004).is_auth_error
