"""Gateway payload envelope."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..constants import OpCode
from ..errors import PayloadError


@dataclass(slots=True, frozen=True)
class GatewayPayload:
    """The common envelope used by WebSocket deliveries."""

    op: int
    d: Any = None
    s: int | None = None
    t: str | None = None
    id: str | None = None

    @property
    def is_dispatch(self) -> bool:
        return self.op == OpCode.DISPATCH

    @property
    def heartbeat_interval(self) -> float | None:
        """Heartbeat interval in seconds from an ``op=10`` Hello payload."""

        if self.op != OpCode.HELLO or not isinstance(self.d, Mapping):
            return None
        raw = self.d.get("heartbeat_interval")
        if raw is None:
            return None
        try:
            return float(raw) / 1000.0
        except (TypeError, ValueError):
            return None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> GatewayPayload:
        if not isinstance(data, Mapping):
            raise PayloadError("gateway payload must be a JSON object")
        op = data.get("op")
        if op is None:
            raise PayloadError("gateway payload is missing 'op'")
        try:
            op_value = int(op)
        except (TypeError, ValueError) as exc:
            raise PayloadError(f"invalid opcode: {op!r}") from exc
        seq = data.get("s")
        return cls(
            op=op_value,
            d=data.get("d"),
            s=int(seq) if seq is not None else None,
            t=str(data["t"]) if data.get("t") is not None else None,
            id=str(data["id"]) if data.get("id") is not None else None,
        )


__all__ = ["GatewayPayload"]
