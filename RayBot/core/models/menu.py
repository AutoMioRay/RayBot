"""Response models for the global menu and command panels."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from .base import Model, as_bool, as_int, as_sequence, as_str, parse_rfc3339
from .outbound import Menu, Panel


@dataclass(slots=True, kw_only=True)
class MenuInfo(Model):
    """The current global C2C menu and its version."""

    version: int = 0
    menu: Menu | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> MenuInfo:
        menu_raw = data.get("menu")
        return cls(
            version=as_int(data.get("version")),
            menu=Menu.from_dict(menu_raw) if isinstance(menu_raw, Mapping) else None,
            raw=data,
        )


@dataclass(slots=True, kw_only=True)
class PanelRecord(Model):
    """One command panel returned by the list endpoint."""

    panel_id: str = ""
    scope: str = ""
    target_type: str = ""
    panel: Panel | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    version: int = 0

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> PanelRecord:
        panel_raw = data.get("panel")
        return cls(
            panel_id=as_str(data.get("panel_id")),
            scope=as_str(data.get("scope")),
            target_type=as_str(data.get("target_type")),
            panel=Panel.from_dict(panel_raw) if isinstance(panel_raw, Mapping) else None,
            created_at=parse_rfc3339(data.get("created_at")),
            updated_at=parse_rfc3339(data.get("updated_at")),
            version=as_int(data.get("version")),
            raw=data,
        )


@dataclass(slots=True, kw_only=True)
class PanelPage(Model):
    """One page of command panels."""

    records: tuple[PanelRecord, ...] = ()
    next_cursor: str = ""
    is_end: bool = False

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> PanelPage:
        return cls(
            records=as_sequence(data.get("records"), PanelRecord.from_dict),
            next_cursor=as_str(data.get("next_cursor")),
            is_end=as_bool(data.get("is_end")),
            raw=data,
        )


@dataclass(slots=True, kw_only=True)
class PanelDetail(Model):
    """Full configuration of one command panel."""

    panel_id: str = ""
    scope: str = ""
    target_type: str = ""
    panel: Panel | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    version: int = 0
    user_openids: tuple[str, ...] = ()
    group_openids: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> PanelDetail:
        panel_raw = data.get("panel")
        user_openids = data.get("user_openids")
        group_openids = data.get("group_openids")
        return cls(
            panel_id=as_str(data.get("panel_id")),
            scope=as_str(data.get("scope")),
            target_type=as_str(data.get("target_type")),
            panel=Panel.from_dict(panel_raw) if isinstance(panel_raw, Mapping) else None,
            created_at=parse_rfc3339(data.get("created_at")),
            updated_at=parse_rfc3339(data.get("updated_at")),
            version=as_int(data.get("version")),
            user_openids=_strings(user_openids),
            group_openids=_strings(group_openids),
            raw=data,
        )


@dataclass(slots=True, kw_only=True)
class PanelCreateResult(Model):
    """Result of creating a panel."""

    panel_id: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> PanelCreateResult:
        return cls(panel_id=as_str(data.get("panel_id")), raw=data)


@dataclass(slots=True, kw_only=True)
class PanelVersion(Model):
    """Version returned after updating a panel."""

    version: int = 0

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> PanelVersion:
        return cls(version=as_int(data.get("version")), raw=data)


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(as_str(item) for item in value)


__all__ = [
    "MenuInfo",
    "PanelCreateResult",
    "PanelDetail",
    "PanelPage",
    "PanelRecord",
    "PanelVersion",
]
