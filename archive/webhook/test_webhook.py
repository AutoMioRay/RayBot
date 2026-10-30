from __future__ import annotations

import json
import time

import pytest
from aiohttp.test_utils import TestClient, TestServer

from qqbot_toolkit.config import WebhookConfig
from qqbot_toolkit.errors import ConfigurationError
from qqbot_toolkit.events import EventBus
from qqbot_toolkit.gateway.signature import sign_bytes
from qqbot_toolkit.gateway.webhook import WebhookServer

SECRET = "DG5g3B4j9X2KOErG"
PATH = "/qqbot"


async def test_callback_url_validation_returns_signature() -> None:
    bus = EventBus(concurrency=1)
    bus.start()
    server = WebhookServer(WebhookConfig(port=8080), bus, SECRET)
    client = TestClient(TestServer(server.create_app()))

    async with client:
        response = await client.post(
            PATH,
            json={"op": 13, "d": {"plain_token": "token", "event_ts": "1725442341"}},
        )
        assert response.status == 200
        body = await response.json()
        assert body["plain_token"] == "token"
        assert len(body["signature"]) == 128

    await bus.stop()


async def test_dispatch_event_is_acknowledged_and_handled() -> None:
    bus = EventBus(concurrency=1)
    bus.start()
    seen: list[str] = []
    bus.subscribe("C2C_MESSAGE_CREATE", lambda event: seen.append(event.content))
    server = WebhookServer(
        WebhookConfig(port=8080, verify_signature=False, dispatch_before_ack=True),
        bus,
        SECRET,
    )
    client = TestClient(TestServer(server.create_app()))

    payload = {
        "op": 0,
        "s": 1,
        "t": "C2C_MESSAGE_CREATE",
        "id": "event-1",
        "d": {
            "id": "message-1",
            "author": {"user_openid": "U"},
            "content": "hello",
            "message_type": 0,
        },
    }
    async with client:
        response = await client.post(PATH, json=payload)
        assert response.status == 200
        assert await response.json() == {"op": 12, "d": {}}

    await bus.drain()
    await bus.stop()
    assert seen == ["hello"]


async def test_invalid_signature_is_rejected() -> None:
    bus = EventBus(concurrency=1)
    bus.start()
    server = WebhookServer(WebhookConfig(port=8080, verify_signature=True), bus, SECRET)
    client = TestClient(TestServer(server.create_app()))
    payload = {"op": 0, "t": "C2C_MESSAGE_CREATE", "d": {}}

    async with client:
        response = await client.post(
            PATH,
            json=payload,
            headers={
                "X-Signature-Ed25519": "00" * 64,
                "X-Signature-Timestamp": "1725442341",
            },
        )
        assert response.status == 401

    await bus.stop()


async def test_valid_signature_is_accepted() -> None:
    bus = EventBus(concurrency=1)
    bus.start()
    seen: list[str] = []
    bus.subscribe("C2C_MESSAGE_CREATE", lambda event: seen.append(event.content))
    server = WebhookServer(
        WebhookConfig(port=8080, verify_signature=True, dispatch_before_ack=True),
        bus,
        SECRET,
    )
    client = TestClient(TestServer(server.create_app()))
    payload = {
        "op": 0,
        "t": "C2C_MESSAGE_CREATE",
        "d": {
            "id": "message-2",
            "author": {"user_openid": "U"},
            "content": "signed",
            "message_type": 0,
        },
    }
    body = json.dumps(payload, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    signature = sign_bytes(SECRET, timestamp.encode() + body)

    async with client:
        response = await client.post(
            PATH,
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Signature-Ed25519": signature,
                "X-Signature-Timestamp": timestamp,
            },
        )
        assert response.status == 200

    await bus.drain()
    await bus.stop()
    assert seen == ["signed"]


async def test_allowed_ips_rejects_other_sources() -> None:
    bus = EventBus(concurrency=1)
    bus.start()
    server = WebhookServer(
        WebhookConfig(port=8080, verify_signature=False, allowed_ips=("10.0.0.0/8",)),
        bus,
        SECRET,
    )
    client = TestClient(TestServer(server.create_app()))
    async with client:
        response = await client.post(
            PATH, json={"op": 13, "d": {"plain_token": "x", "event_ts": "1"}}
        )
        assert response.status == 403
    await bus.stop()


async def test_allowed_ips_accepts_loopback() -> None:
    bus = EventBus(concurrency=1)
    bus.start()
    server = WebhookServer(
        WebhookConfig(port=8080, verify_signature=False, allowed_ips=("127.0.0.1",)),
        bus,
        SECRET,
    )
    client = TestClient(TestServer(server.create_app()))
    async with client:
        response = await client.post(
            PATH, json={"op": 13, "d": {"plain_token": "x", "event_ts": "1"}}
        )
        assert response.status == 200
    await bus.stop()


async def test_forwarded_for_requires_trusted_proxy() -> None:
    with pytest.raises(ConfigurationError):
        WebhookConfig(trust_forwarded_for=True)

    bus = EventBus(concurrency=1)
    bus.start()
    server = WebhookServer(
        WebhookConfig(
            port=8080,
            verify_signature=False,
            trust_forwarded_for=True,
            trusted_proxies=("127.0.0.1",),
            allowed_ips=("10.0.0.0/8",),
        ),
        bus,
        SECRET,
    )
    client = TestClient(TestServer(server.create_app()))
    async with client:
        accepted = await client.post(
            PATH,
            json={"op": 13, "d": {"plain_token": "x", "event_ts": "1"}},
            headers={"X-Forwarded-For": "10.1.2.3"},
        )
        assert accepted.status == 200
        rejected = await client.post(
            PATH,
            json={"op": 13, "d": {"plain_token": "x", "event_ts": "1"}},
            headers={"X-Forwarded-For": "192.168.1.1"},
        )
        assert rejected.status == 403
    await bus.stop()


async def test_validation_endpoint_can_be_disabled_at_runtime() -> None:
    bus = EventBus(concurrency=1)
    bus.start()
    server = WebhookServer(
        WebhookConfig(port=8080, verify_signature=False, validation_enabled=False),
        bus,
        SECRET,
    )
    client = TestClient(TestServer(server.create_app()))
    async with client:
        disabled = await client.post(
            PATH, json={"op": 13, "d": {"plain_token": "x", "event_ts": "1"}}
        )
        assert disabled.status == 403

        server.set_validation_enabled(True)
        enabled = await client.post(
            PATH, json={"op": 13, "d": {"plain_token": "x", "event_ts": "1"}}
        )
        assert enabled.status == 200
    await bus.stop()


async def test_stale_timestamp_is_rejected() -> None:
    bus = EventBus(concurrency=1)
    bus.start()
    server = WebhookServer(
        WebhookConfig(port=8080, verify_signature=True, max_timestamp_skew=300),
        bus,
        SECRET,
    )
    client = TestClient(TestServer(server.create_app()))
    payload = {"op": 0, "t": "C2C_MESSAGE_CREATE", "d": {}}
    body = json.dumps(payload, separators=(",", ":")).encode()
    async with client:
        stale_ts = str(int(time.time()) - 3600)
        stale_sig = sign_bytes(SECRET, stale_ts.encode() + body)
        stale = await client.post(
            PATH,
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Signature-Ed25519": stale_sig,
                "X-Signature-Timestamp": stale_ts,
            },
        )
        assert stale.status == 401

        fresh_ts = str(int(time.time()))
        fresh_sig = sign_bytes(SECRET, fresh_ts.encode() + body)
        fresh = await client.post(
            PATH,
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Signature-Ed25519": fresh_sig,
                "X-Signature-Timestamp": fresh_ts,
            },
        )
        assert fresh.status == 200
    await bus.stop()


async def test_signature_is_checked_before_json_parse() -> None:
    bus = EventBus(concurrency=1)
    bus.start()
    server = WebhookServer(WebhookConfig(port=8080, verify_signature=True), bus, SECRET)
    client = TestClient(TestServer(server.create_app()))
    async with client:
        response = await client.post(
            PATH,
            data=b"{not-json",
            headers={
                "Content-Type": "application/json",
                "X-Signature-Ed25519": "00" * 64,
                "X-Signature-Timestamp": str(int(time.time())),
            },
        )
        assert response.status == 401
    await bus.stop()


async def test_rate_limit_returns_429() -> None:
    bus = EventBus(concurrency=1)
    bus.start()
    server = WebhookServer(
        WebhookConfig(
            port=8080,
            verify_signature=False,
            rate_limit_per_second=1,
            rate_limit_burst=1,
        ),
        bus,
        SECRET,
    )
    client = TestClient(TestServer(server.create_app()))
    async with client:
        first = await client.post(PATH, json={"op": 13, "d": {"plain_token": "x", "event_ts": "1"}})
        assert first.status == 200
        second = await client.post(
            PATH, json={"op": 13, "d": {"plain_token": "x", "event_ts": "1"}}
        )
        assert second.status == 429
    await bus.stop()


async def test_require_tls_rejects_start_without_context() -> None:
    bus = EventBus(concurrency=1)
    server = WebhookServer(WebhookConfig(host="0.0.0.0", require_tls=True), bus, SECRET)
    with pytest.raises(ConfigurationError):
        await server.start()
