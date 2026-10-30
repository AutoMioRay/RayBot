"""Outgoing payload models.

Every model converts to a plain dictionary through :meth:`Payload.to_dict`,
which removes ``None`` values recursively so optional fields are omitted.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from datetime import datetime
from enum import Enum
from typing import Any

from .base import (
    as_bool,
    as_int,
    as_sequence,
    as_str,
    format_rfc3339,
)


def _compact(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Payload):
        return value.to_dict()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return format_rfc3339(value)
    if isinstance(value, Mapping):
        return {
            str(key): compacted
            for key, item in value.items()
            if (compacted := _compact(item)) is not None
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [compacted for item in value if (compacted := _compact(item)) is not None]
    return value


@dataclass(slots=True, kw_only=True)
class Payload:
    """Base class for serializable outgoing structures."""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready dictionary without ``None`` values."""

        result: dict[str, Any] = {}
        for item in fields(self):
            compacted = _compact(getattr(self, item.name))
            if compacted is not None:
                result[item.name] = compacted
        return result


@dataclass(slots=True, kw_only=True)
class Permission(Payload):
    """Who may click a keyboard button."""

    type: int = 2
    specify_user_ids: Sequence[str] | None = None
    specify_role_ids: Sequence[str] | None = None


@dataclass(slots=True, kw_only=True)
class Modal(Payload):
    """A secondary confirmation dialog for a keyboard button."""

    content: str
    confirm_text: str | None = None
    cancel_text: str | None = None


@dataclass(slots=True, kw_only=True)
class RenderData(Payload):
    """Visual definition of a keyboard button."""

    label: str
    visited_label: str | None = None
    style: int | None = None


@dataclass(slots=True, kw_only=True)
class ButtonAction(Payload):
    """What happens when a keyboard button is clicked.

    ``type`` 0 opens a URL, 1 calls the bot backend, 2 inserts or sends a
    command in the chat input box.
    """

    type: int
    permission: Permission | None = None
    data: str | None = None
    click_limit: int | None = None
    unsupport_tips: str | None = None
    enter: bool | None = None
    reply: bool | None = None
    anchor: int | None = None
    modal: Modal | None = None


@dataclass(slots=True, kw_only=True)
class KeyboardButton(Payload):
    """One button inside a keyboard row."""

    id: str
    render_data: RenderData | None = None
    action: ButtonAction | None = None
    group_id: str | None = None


@dataclass(slots=True, kw_only=True)
class KeyboardRow(Payload):
    """A horizontal row of keyboard buttons."""

    buttons: Sequence[KeyboardButton] | None = None


@dataclass(slots=True, kw_only=True)
class KeyboardContent(Payload):
    """Custom keyboard layout."""

    rows: Sequence[KeyboardRow] | None = None


@dataclass(slots=True, kw_only=True)
class Keyboard(Payload):
    """Inline keyboard, either a platform template or a custom layout."""

    id: str | None = None
    content: KeyboardContent | None = None


@dataclass(slots=True, kw_only=True)
class MediaInfo(Payload):
    """Rich-media reference returned by an upload endpoint."""

    file_info: str


@dataclass(slots=True, kw_only=True)
class MemberMuteChange(Payload):
    """One member-level mute operation.

    ``op`` is ``add``, ``update`` or ``del``.  ``mute_expire_at`` may be an
    RFC3339 string, a ``datetime`` or a Unix timestamp.
    """

    op: str
    member_openid: str
    mute_expire_at: str | datetime | int | float | None = None


@dataclass(slots=True, kw_only=True)
class MessageReference(Payload):
    """Quote a previous message in a reply."""

    message_id: str


@dataclass(slots=True, kw_only=True)
class InputNotify(Payload):
    """C2C "typing" indicator (``msg_type=6``)."""

    input_type: int = 1
    input_second: int = 60


@dataclass(slots=True, kw_only=True)
class MessageMarkdown(Payload):
    """Markdown content or a Markdown template invocation."""

    content: str | None = None
    template_id: int | None = None
    custom_template_id: str | None = None
    params: Sequence[Mapping[str, Any]] | None = None
    force_verify_image_resource: bool | None = None


@dataclass(slots=True, kw_only=True)
class Switch(Payload):
    """A toggle in the global C2C custom menu."""

    switch_id: str
    default: bool = False

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Switch:
        return cls(
            switch_id=as_str(data.get("switch_id")),
            default=as_bool(data.get("default")),
        )


@dataclass(slots=True, kw_only=True)
class SubMenuItem(Payload):
    """A second-level custom-menu entry."""

    name: str
    type: str
    send_message: str | None = None
    link: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SubMenuItem:
        return cls(
            name=as_str(data.get("name")),
            type=as_str(data.get("type")),
            send_message=as_str(data.get("send_message")) or None,
            link=as_str(data.get("link")) or None,
        )


@dataclass(slots=True, kw_only=True)
class MenuItem(Payload):
    """A first-level C2C custom-menu entry."""

    name: str
    type: str
    sub_menu_items: Sequence[SubMenuItem] | None = None
    send_message: str | None = None
    link: str | None = None
    switch: Switch | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> MenuItem:
        switch_raw = data.get("switch")
        return cls(
            name=as_str(data.get("name")),
            type=as_str(data.get("type")),
            sub_menu_items=as_sequence(data.get("sub_menu_items"), SubMenuItem.from_dict) or None,
            send_message=as_str(data.get("send_message")) or None,
            link=as_str(data.get("link")) or None,
            switch=Switch.from_dict(switch_raw) if isinstance(switch_raw, Mapping) else None,
        )


@dataclass(slots=True, kw_only=True)
class Menu(Payload):
    """The complete C2C custom menu."""

    items: Sequence[MenuItem]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Menu:
        return cls(items=as_sequence(data.get("items"), MenuItem.from_dict))


@dataclass(slots=True, kw_only=True)
class PanelItem(Payload):
    """One command or link inside a command panel."""

    name: str | None = None
    desc: str | None = None
    type: str | None = None
    only_admin: bool | None = None
    link: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> PanelItem:
        only_admin = data.get("only_admin")
        return cls(
            name=as_str(data.get("name")) or None,
            desc=as_str(data.get("desc")) or None,
            type=as_str(data.get("type")) or None,
            only_admin=as_bool(only_admin) if only_admin is not None else None,
            link=as_str(data.get("link")) or None,
        )


@dataclass(slots=True, kw_only=True)
class Panel(Payload):
    """A command panel configuration."""

    items: Sequence[PanelItem] | None = None
    remark: str | None = None
    version: int | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Panel:
        version = data.get("version")
        return cls(
            items=as_sequence(data.get("items"), PanelItem.from_dict) or None,
            remark=as_str(data.get("remark")) or None,
            version=as_int(version) if version is not None else None,
        )


def command_button(
    label: str,
    data: str,
    *,
    id: str | None = None,
    style: int = 1,
    permission_type: int = 2,
    enter: bool = False,
    reply: bool = False,
    modal: Modal | None = None,
) -> KeyboardButton:
    """Build a button that inserts or sends a command.

    Args:
        label: Button text, at most 10 characters.
        data: Command text sent to the bot.
        id: Stable button identifier; defaults to ``label``.
        style: 0 grey outline, 1 blue outline, 3 white/red, 4 blue/white.
        permission_type: 0 specified users, 1 administrators, 2 everyone.
        enter: Send the command immediately (C2C only).
        reply: Send the command as a quoted reply.
        modal: Optional secondary confirmation.
    """

    return KeyboardButton(
        id=id or label,
        render_data=RenderData(label=label, style=style),
        action=ButtonAction(
            type=2,
            permission=Permission(type=permission_type),
            data=data,
            enter=enter,
            reply=reply,
            modal=modal,
        ),
    )


def link_button(
    label: str,
    url: str,
    *,
    id: str | None = None,
    style: int = 1,
) -> KeyboardButton:
    """Build a button that opens a URL."""

    return KeyboardButton(
        id=id or label,
        render_data=RenderData(label=label, style=style),
        action=ButtonAction(type=0, data=url, permission=Permission(type=2)),
    )


def keyboard(*rows: KeyboardRow) -> Keyboard:
    """Assemble a custom keyboard from rows."""

    return Keyboard(content=KeyboardContent(rows=list(rows)))


__all__ = [
    "ButtonAction",
    "InputNotify",
    "Keyboard",
    "KeyboardButton",
    "KeyboardContent",
    "KeyboardRow",
    "MediaInfo",
    "MemberMuteChange",
    "Menu",
    "MenuItem",
    "Panel",
    "PanelItem",
    "MessageMarkdown",
    "MessageReference",
    "Modal",
    "Payload",
    "Permission",
    "RenderData",
    "SubMenuItem",
    "Switch",
    "command_button",
    "keyboard",
    "link_button",
]
