"""Model base classes and parsing helpers."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, ClassVar


def parse_rfc3339(value: Any) -> datetime | None:
    """Parse an RFC3339 timestamp into an aware :class:`datetime`.

    Returns ``None`` for empty or malformed values instead of failing an entire
    event parse, because timestamps are metadata rather than control data.
    """

    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def format_rfc3339(value: datetime | int | float | str) -> str:
    """Format a mute expiration value for the OpenAPI.

    Accepts an aware/naive ``datetime``, a Unix timestamp in seconds, or an
    already formatted string.  Naive datetimes and Unix timestamps are
    interpreted in the local timezone.
    """

    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        moment = datetime.fromtimestamp(value, tz=UTC).astimezone()
    elif isinstance(value, datetime):
        moment = value if value.tzinfo is not None else value.astimezone()
    else:
        raise TypeError(f"unsupported timestamp type: {type(value)!r}")
    return moment.isoformat(timespec="seconds")


def parse_ext(value: Any) -> dict[str, str]:
    """Convert ``MessageScene.ext`` entries into a key/value mapping."""

    result: dict[str, str] = {}
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return result
    for item in value:
        if isinstance(item, str) and "=" in item:
            key, raw = item.split("=", 1)
            result[key] = raw
        elif isinstance(item, Mapping):
            for key, raw in item.items():
                result[str(key)] = str(raw)
    return result


def as_sequence[T](value: Any, factory: Callable[[Mapping[str, Any]], T]) -> tuple[T, ...]:
    """Build a tuple of models from a JSON array, skipping malformed entries."""

    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(factory(item) for item in value if isinstance(item, Mapping))


def as_int(value: Any, default: int = 0) -> int:
    """Convert ``value`` to int, returning ``default`` on failure."""

    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def as_str(value: Any, default: str = "") -> str:
    """Convert ``value`` to str, using ``default`` for ``None``."""

    if value is None:
        return default
    return str(value)


def as_bool(value: Any, default: bool = False) -> bool:
    """Convert common boolean representations to bool."""

    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


def as_mapping(value: Any) -> dict[str, Any]:
    """Return a shallow dict copy when ``value`` is a mapping."""

    return dict(value) if isinstance(value, Mapping) else {}


@dataclass(slots=True, kw_only=True)
class Model:
    """Base class for inbound models.

    ``raw`` keeps the original payload so callers can read fields added by the
    platform before this library learns about them.
    """

    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)


@dataclass(slots=True, kw_only=True)
class Event(Model):
    """Base class for a dispatched gateway event."""

    event_name: ClassVar[str] = ""
    event_id: str | None = None
    seq: int | None = None


def meta(kwargs: Mapping[str, Any]) -> dict[str, Any]:
    """Extract event metadata passed through ``from_dict(**meta)``."""

    return {"event_id": kwargs.get("event_id"), "seq": kwargs.get("seq")}


__all__ = [
    "Event",
    "Model",
    "as_bool",
    "as_int",
    "as_mapping",
    "as_sequence",
    "as_str",
    "format_rfc3339",
    "meta",
    "parse_ext",
    "parse_rfc3339",
]
