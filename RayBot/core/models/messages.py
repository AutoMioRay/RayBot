"""Inbound single-chat and group-chat message events."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, ClassVar

from .base import Event, as_int, as_sequence, as_str, meta, parse_rfc3339
from .common import (
    ArkData,
    MessageAttachment,
    MessageScene,
    MsgElement,
    User,
)


@dataclass(slots=True, kw_only=True)
class ChatMessage(Event):
    """Fields shared by C2C and group message events."""

    event_name: ClassVar[str] = ""
    id: str = ""
    author: User = field(default_factory=User)
    content: str = ""
    timestamp: datetime | None = None
    message_type: int = 0
    message_scene: MessageScene | None = None
    attachments: tuple[MessageAttachment, ...] = ()
    mentions: tuple[User, ...] = ()
    ark_data: ArkData | None = None
    msg_elements: tuple[MsgElement, ...] = ()

    @property
    def is_quote(self) -> bool:
        return self.message_type == 103

    @property
    def is_card(self) -> bool:
        return self.message_type == 3

    @property
    def msg_idx(self) -> str:
        """Stable platform index, preferred over ``id`` for de-duplication."""

        return self.message_scene.msg_idx if self.message_scene else ""

    @property
    def ref_msg_idx(self) -> str:
        return self.message_scene.ref_msg_idx if self.message_scene else ""

    @property
    def auth_token(self) -> str:
        return self.message_scene.auth_token if self.message_scene else ""

    @property
    def quoted(self) -> MsgElement | None:
        """The quoted message element for a reply message, if present."""

        if not self.is_quote:
            return None
        for element in self.msg_elements:
            if element.content:
                return element
        return self.msg_elements[0] if self.msg_elements else None

    def attachments_of(self, content_type_prefix: str) -> tuple[MessageAttachment, ...]:
        """Return attachments whose content type starts with ``content_type_prefix``."""

        return tuple(
            item for item in self.attachments if item.content_type.startswith(content_type_prefix)
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], **kwargs: Any) -> ChatMessage:
        author_raw = data.get("author")
        scene_raw = data.get("message_scene")
        ark_raw = data.get("ark_data")
        return cls(
            id=as_str(data.get("id")),
            author=User.from_dict(author_raw) if isinstance(author_raw, Mapping) else User(),
            content=as_str(data.get("content")),
            timestamp=parse_rfc3339(data.get("timestamp")),
            message_type=as_int(data.get("message_type")),
            message_scene=MessageScene.from_dict(scene_raw)
            if isinstance(scene_raw, Mapping)
            else None,
            attachments=as_sequence(data.get("attachments"), MessageAttachment.from_dict),
            mentions=as_sequence(data.get("mentions"), User.from_dict),
            ark_data=ArkData.from_dict(ark_raw) if isinstance(ark_raw, Mapping) else None,
            msg_elements=as_sequence(data.get("msg_elements"), MsgElement.from_dict),
            raw=data,
            **meta(kwargs),
        )


@dataclass(slots=True, kw_only=True)
class C2CMessage(ChatMessage):
    """A message sent directly to the robot."""

    event_name: ClassVar[str] = "C2C_MESSAGE_CREATE"

    @property
    def user_openid(self) -> str:
        return self.author.user_openid or self.author.id

    @property
    def sender_name(self) -> str:
        return self.author.username or self.user_openid


@dataclass(slots=True, kw_only=True)
class GroupMessage(ChatMessage):
    """Base for group messages. Use the concrete event subclasses below."""

    group_openid: str = ""

    @property
    def member_openid(self) -> str:
        return self.author.member_openid or self.author.id

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], **kwargs: Any) -> GroupMessage:
        message = super(GroupMessage, cls).from_dict(data, **kwargs)
        return replace(message, group_openid=as_str(data.get("group_openid")))


@dataclass(slots=True, kw_only=True)
class GroupAtMessage(GroupMessage):
    """A group message that mentions the robot.

    ``content`` already has the leading @-robot prefix removed by QQ.
    """

    event_name: ClassVar[str] = "GROUP_AT_MESSAGE_CREATE"


@dataclass(slots=True, kw_only=True)
class GroupAllMessage(GroupMessage):
    """A group message received because the robot enabled full-message mode."""

    event_name: ClassVar[str] = "GROUP_MESSAGE_CREATE"


__all__ = [
    "C2CMessage",
    "ChatMessage",
    "GroupAllMessage",
    "GroupAtMessage",
    "GroupMessage",
]
