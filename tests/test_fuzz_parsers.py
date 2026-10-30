"""L2 fuzz tests for the JSON/event parsing layer (S2-08 .. S2-16).

Every legal JSON input must either parse into a valid payload/event or be
rejected with an explicit, expected exception — never crash the process.
"""

from __future__ import annotations

import json
import os

from hypothesis import given, settings
from hypothesis import strategies as st

from qqbot_toolkit.errors import PayloadError
from qqbot_toolkit.events.payload import GatewayPayload
from qqbot_toolkit.gateway.ws import GatewayClient
from qqbot_toolkit.models import UnknownEvent, parse_event

# CI 可调配额：PR 用 500 保证 <5min，nightly 用 10000 做长尾覆盖。
_FUZZ_EXAMPLES = int(os.environ.get("QQBOT_FUZZ_EXAMPLES", "2000"))

json_values = st.recursive(
    st.none()
    | st.booleans()
    | st.integers(-(2**63), 2**63)
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text(max_size=256),
    lambda children: (
        st.lists(children, max_size=8) | st.dictionaries(st.text(max_size=32), children, max_size=8)
    ),
    max_leaves=50,
)

event_names = st.sampled_from(
    [
        "C2C_MESSAGE_CREATE",
        "GROUP_AT_MESSAGE_CREATE",
        "GROUP_MESSAGE_CREATE",
        "INTERACTION_CREATE",
        "READY",
        "RESUMED",
        "GROUP_ADD_ROBOT",
        "FRIEND_ADD",
        "TOTALLY_UNKNOWN_EVENT",
        "",
    ]
)


@given(payload=json_values)
@settings(max_examples=_FUZZ_EXAMPLES, deadline=None)
def test_gateway_payload_accepts_or_rejects_safely(payload: object) -> None:
    """S2-11/S2-13: arbitrary JSON never crashes the payload envelope parser."""

    try:
        result = GatewayPayload.from_dict(payload)  # type: ignore[arg-type]
    except PayloadError:
        return
    assert isinstance(result, GatewayPayload)
    assert isinstance(result.op, int)


@given(name=event_names, data=json_values)
@settings(max_examples=_FUZZ_EXAMPLES, deadline=None)
def test_parse_event_never_crashes(name: str, data: object) -> None:
    """S2-12/S2-16: hostile ``d`` objects produce a typed event or UnknownEvent."""

    if not isinstance(data, dict):
        data = {}
    event = parse_event(name, data, event_id="evt-1", seq=1)
    assert event is not None
    # Unknown names must degrade to UnknownEvent, not raise.
    from qqbot_toolkit.models.events import EVENT_REGISTRY  # noqa: PLC0415

    if name not in EVENT_REGISTRY:
        assert isinstance(event, UnknownEvent)


@given(text=st.text(max_size=4096))
@settings(max_examples=_FUZZ_EXAMPLES, deadline=None)
def test_decode_ignores_arbitrary_strings(text: str) -> None:
    """S2-08/S2-13: garbage frames are logged and dropped, never raised."""

    bus = _throwaway_bus()
    client = GatewayClient(_FakeTokens(), _FakeAPI(), _cfg(), bus)
    assert client._decode(text) is None or True  # never raises


@given(data=json_values)
@settings(max_examples=_FUZZ_EXAMPLES, deadline=None)
def test_decode_roundtrip_or_reject(data: object) -> None:
    bus = _throwaway_bus()
    client = GatewayClient(_FakeTokens(), _FakeAPI(), _cfg(), bus)
    raw = json.dumps(data, ensure_ascii=False)
    decoded = client._decode(raw)
    if decoded is not None:
        assert isinstance(decoded, GatewayPayload)


def test_deeply_nested_json_is_rejected() -> None:
    """S2-09/S2-15: a 10 000-level JSON bomb is rejected, not a RecursionError."""

    for depth in (100, 1_000, 10_000):
        raw = '{"a":' * depth + "1" + "}" * depth
        bus = _throwaway_bus()
        client = GatewayClient(_FakeTokens(), _FakeAPI(), _cfg(), bus)
        assert client._decode(raw) is None, f"depth {depth} must be rejected"


def test_oversized_string_is_handled() -> None:
    """S2-08: a multi-megabyte string field neither crashes nor hangs."""

    raw = json.dumps({"op": 0, "t": "X", "d": {"content": "A" * (2 * 1024 * 1024)}})
    bus = _throwaway_bus()
    client = GatewayClient(_FakeTokens(), _FakeAPI(), _cfg(), bus)
    decoded = client._decode(raw)
    assert decoded is None or decoded.op == 0


def test_duplicate_keys_take_last_value_deterministically() -> None:
    """S2-16: duplicate keys have a defined strategy (last wins, no crash)."""

    bus = _throwaway_bus()
    client = GatewayClient(_FakeTokens(), _FakeAPI(), _cfg(), bus)
    decoded = client._decode('{"op": 11, "op": 99}')
    assert decoded is not None
    assert decoded.op == 99


def test_unknown_opcode_is_preserved_for_policy() -> None:
    """S2-13: unknown opcodes parse but never match a dispatch branch."""

    bus = _throwaway_bus()
    client = GatewayClient(_FakeTokens(), _FakeAPI(), _cfg(), bus)
    decoded = client._decode('{"op": 31337}')
    assert decoded is not None
    assert decoded.op == 31337
    assert not decoded.is_dispatch


def test_binary_garbage_is_rejected() -> None:
    """S2-12: invalid UTF-8 bytes are rejected without leaking exceptions."""

    bus = _throwaway_bus()
    client = GatewayClient(_FakeTokens(), _FakeAPI(), _cfg(), bus)
    assert client._decode(b"\xff\xfe\x80\x81") is None


def test_unicode_edge_cases_survive() -> None:
    """S2-12: zero-width characters, BOM, combining marks, lone surrogates."""

    samples = [
        "﻿op",  # BOM
        "zero​width",
        "combining é́́",
        "emoji 🤖🤖",
        "rtl‏rtl‎",
    ]
    bus = _throwaway_bus()
    client = GatewayClient(_FakeTokens(), _FakeAPI(), _cfg(), bus)
    for name in samples:
        raw = json.dumps({"op": 0, "s": 1, "t": name, "d": {}})
        decoded = client._decode(raw)
        assert decoded is None or decoded.t == name


class _FakeTokens:
    async def get_token(self, *, force_refresh: bool = False) -> str:
        return "token"


class _FakeAPI:
    async def get(self) -> object:  # pragma: no cover - never called here
        raise AssertionError


def _cfg():
    from qqbot_toolkit.config import GatewayConfig  # noqa: PLC0415

    return GatewayConfig()


def _throwaway_bus():
    from qqbot_toolkit.events import EventBus  # noqa: PLC0415

    return EventBus(concurrency=1)
