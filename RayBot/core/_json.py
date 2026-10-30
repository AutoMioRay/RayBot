"""JSON codec with an optional orjson fast path.

``orjson`` (Rust) parses 5-10x faster than the standard library and accepts
``bytes`` directly, skipping a UTF-8 decode on the WebSocket receive path.  The
codec falls back to :mod:`json` when orjson is unavailable, so the rest of the
codebase never branches on the backend.

``loads`` accepts ``str`` or ``bytes``.  ``dumps`` always returns ``bytes`` in
compact form (UTF-8, minimal separators), which both ``websockets.send`` and
``httpx`` accept directly.
"""

from __future__ import annotations

from typing import Any

try:  # pragma: no cover - exercised indirectly through the fast-path tests
    import orjson as _orjson

    ORJSON_AVAILABLE = True

    def loads(data: str | bytes | bytearray) -> Any:
        """Deserialize JSON from ``str`` or ``bytes``."""

        return _orjson.loads(data)

    def dumps(obj: Any) -> bytes:
        """Serialize ``obj`` to compact UTF-8 JSON bytes."""

        return _orjson.dumps(obj)

except ImportError:  # pragma: no cover - fallback backend
    import json

    ORJSON_AVAILABLE = False

    def loads(data: str | bytes | bytearray) -> Any:
        """Deserialize JSON from ``str`` or ``bytes``."""

        return json.loads(data)

    def dumps(obj: Any) -> bytes:
        """Serialize ``obj`` to compact UTF-8 JSON bytes."""

        return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


__all__ = ["ORJSON_AVAILABLE", "dumps", "loads"]
