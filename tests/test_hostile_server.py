"""L5 hostile-server simulations and log-hygiene checks (S5-01..S5-07, S2-02/03)."""

from __future__ import annotations

import asyncio
import contextlib
import datetime
import ipaddress
import json
import logging
import ssl
import tempfile
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.x509.oid import NameOID
from websockets.asyncio.server import serve

from qqbot_toolkit.config import GatewayConfig
from qqbot_toolkit.errors import GatewayError
from qqbot_toolkit.events import EventBus
from qqbot_toolkit.gateway.ws import GatewayClient
from qqbot_toolkit.models import GatewayInfo, SessionStartLimit

from .ws_helpers import ScriptedServer, hello, ready

SECRET_TOKEN = "SECRET-WS-TOKEN-VALUE"


class FakeTokens:
    async def get_token(self, *, force_refresh: bool = False) -> str:
        return SECRET_TOKEN


class FakeGatewayAPI:
    def __init__(self, url: str) -> None:
        self.url = url

    async def get(self) -> GatewayInfo:
        return GatewayInfo(
            url=self.url,
            shards=1,
            session_start_limit=SessionStartLimit(max_concurrency=1),
        )


def tiny_config(**overrides: object) -> GatewayConfig:
    defaults: dict[str, object] = {
        "reconnect_initial_delay": 0.01,
        "reconnect_max_delay": 0.02,
        "open_timeout": 2.0,
        "heartbeat_min_interval": 0.05,
        "heartbeat_max_interval": 0.2,
    }
    defaults.update(overrides)
    return GatewayConfig(**defaults)  # type: ignore[arg-type]


async def test_hostile_frames_do_not_crash_the_client() -> None:
    """S5-01/S5-03/S5-04: garbage payloads degrade to warnings, then a valid
    event still flows through."""

    async def handler(ws, server: ScriptedServer) -> None:
        await server.send(ws, hello())
        await server.recv(ws)
        await server.send(ws, ready())
        # Hostile frames: malformed JSON, wrong envelope types, unknown opcode,
        # opcode as string, null dispatch, hostile heartbeat.
        await server.send(ws, "{not json")
        await server.send(ws, "[1, 2, 3]")
        await server.send(ws, '"just a string"')
        await server.send(ws, json.dumps({"op": "not-a-number"}))
        await server.send(ws, json.dumps({"op": 31337, "d": {"x": 1}}))
        await server.send(ws, json.dumps({"op": 0, "t": None, "d": None}))
        await server.send(ws, json.dumps({"op": 1, "d": {"evil": True}}))
        await server.send(ws, b"\xff\xfe binary garbage")
        # Then a legitimate dispatch.
        await server.send(
            ws,
            {
                "op": 0,
                "s": 2,
                "t": "C2C_MESSAGE_CREATE",
                "id": "evt-ok",
                "d": {"id": "m1", "author": {"user_openid": "U"}, "content": "still alive"},
            },
        )
        with contextlib.suppress(Exception):
            await ws.wait_closed()

    async with ScriptedServer(handler) as server:
        bus = EventBus(concurrency=2)
        bus.start()
        contents: list[str] = []
        done = asyncio.Event()

        def on_message(event: object) -> None:
            contents.append(getattr(event, "content", ""))
            done.set()

        bus.subscribe("C2C_MESSAGE_CREATE", on_message)
        client = GatewayClient(FakeTokens(), FakeGatewayAPI(server.url), tiny_config(), bus)
        task = asyncio.create_task(client.run())
        try:
            await asyncio.wait_for(done.wait(), 10)
        finally:
            await client.stop()
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.wait_for(task, 5)
            await bus.stop()

    assert contents == ["still alive"]
    # Invalid: broken JSON, non-object, string, op-as-string, invalid UTF-8.
    # Unknown opcodes and nameless dispatches parse fine by design.
    assert client.stats["invalid_payloads"] == 5
    assert client.stats["events_dispatched"] >= 2  # READY + message


async def test_oversized_frame_is_rejected_and_client_recovers() -> None:
    """S5-02: a frame beyond max_size closes the connection (code 1009) and the
    client reconnects instead of dying or OOMing."""

    sent_huge = asyncio.Event()

    async def handler(ws, server: ScriptedServer) -> None:
        await server.send(ws, hello())
        await server.recv(ws)
        if server.connections == 1:
            await server.send(ws, "X" * (64 * 1024))  # 64 KiB > 16 KiB limit
            with contextlib.suppress(Exception):
                await ws.wait_closed()
            return
        await server.send(ws, ready())
        sent_huge.set()

    async with ScriptedServer(handler) as server:
        bus = EventBus(concurrency=2)
        bus.start()
        client = GatewayClient(
            FakeTokens(),
            FakeGatewayAPI(server.url),
            tiny_config(max_message_size=16 * 1024),
            bus,
        )
        task = asyncio.create_task(client.run())
        try:
            await asyncio.wait_for(sent_huge.wait(), 10)
        finally:
            await client.stop()
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.wait_for(task, 5)
            await bus.stop()

    assert server.connections >= 2


def _self_signed_cert() -> tuple[Path, Path]:
    """Create a throwaway self-signed certificate (test-only)."""

    key = ed25519.Ed25519PrivateKey.generate()
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .sign(key, None)  # Ed25519 signs without a digest algorithm
    )
    tmpdir = tempfile.mkdtemp()
    cert_path = Path(tmpdir) / "cert.pem"
    key_path = Path(tmpdir) / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


async def test_wss_rejects_self_signed_certificate() -> None:
    """S3-02/S3-03: a MITM with a self-signed certificate must not be able to
    complete a handshake and receive the Identify token."""

    cert_path, key_path = _self_signed_cert()
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_context.load_cert_chain(Path(cert_path), Path(key_path))

    received_token = False

    async def handler(ws) -> None:
        nonlocal received_token
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=5)
            if "SECRET-WS-TOKEN-VALUE" in str(raw):
                received_token = True
        except Exception as exc:  # noqa: BLE001 - any failure means the MITM failed
            logging.getLogger(__name__).debug("MITM handler error: %s", type(exc).__name__)

    server = await serve(handler, "127.0.0.1", 0, ssl=ssl_context)
    port = server.sockets[0].getsockname()[1]
    bus = EventBus(concurrency=2)
    bus.start()
    client = GatewayClient(
        FakeTokens(),
        FakeGatewayAPI(f"wss://127.0.0.1:{port}"),
        tiny_config(reconnect_max_attempts=2),
        bus,
    )
    with pytest.raises(GatewayError) as excinfo:
        await client.run()
    await bus.stop()
    server.close()
    await server.wait_closed()

    assert excinfo.value.fatal
    assert not received_token, "the self-signed server must never see the token"


async def test_token_never_appears_in_logs_during_hostile_run(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """S2-02: even hostile traffic must not push the token into the logs."""

    async def handler(ws, server: ScriptedServer) -> None:
        # Accept the connection, read the Identify, then drop it without ever
        # sending READY.  Successful connections reset the reconnect counter,
        # so a reconnect limit is only reachable through failing connections.
        await server.send(ws, hello())
        await server.recv(ws)
        await ws.close(code=1000)

    async with ScriptedServer(handler) as server:
        bus = EventBus(concurrency=2)
        bus.start()
        client = GatewayClient(
            FakeTokens(),
            FakeGatewayAPI(server.url),
            tiny_config(reconnect_max_attempts=1),
            bus,
        )
        with caplog.at_level(logging.DEBUG):
            with contextlib.suppress(GatewayError):
                await asyncio.wait_for(client.run(), 5)
        await bus.stop()

    assert SECRET_TOKEN not in caplog.text
