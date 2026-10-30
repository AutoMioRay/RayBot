"""Typed events other than message and interaction events, plus the registry."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, ClassVar

from .._json import dumps as _json_dumps
from .base import Event, Model, as_int, as_str, meta
from .common import User
from .group import AutoApproved, JoinRequest
from .interaction import InteractionEvent
from .messages import C2CMessage, ChatMessage, GroupAllMessage, GroupAtMessage


@dataclass(slots=True, kw_only=True)
class FriendAuthor(Model):
    union_openid: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> FriendAuthor:
        return cls(union_openid=as_str(data.get("union_openid")), raw=data)


@dataclass(slots=True, kw_only=True)
class GroupOperationEvent(Event):
    """Shared shape for robot add/remove and message-switch events."""

    event_name: ClassVar[str] = ""
    timestamp: int = 0
    group_openid: str = ""
    op_member_openid: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], **kwargs: Any) -> GroupOperationEvent:
        return cls(
            timestamp=as_int(data.get("timestamp")),
            group_openid=as_str(data.get("group_openid")),
            op_member_openid=as_str(data.get("op_member_openid")),
            raw=data,
            **meta(kwargs),
        )


@dataclass(slots=True, kw_only=True)
class GroupAddRobot(GroupOperationEvent):
    event_name: ClassVar[str] = "GROUP_ADD_ROBOT"


@dataclass(slots=True, kw_only=True)
class GroupDelRobot(GroupOperationEvent):
    event_name: ClassVar[str] = "GROUP_DEL_ROBOT"


@dataclass(slots=True, kw_only=True)
class GroupMsgReject(GroupOperationEvent):
    event_name: ClassVar[str] = "GROUP_MSG_REJECT"


@dataclass(slots=True, kw_only=True)
class GroupMsgReceive(GroupOperationEvent):
    event_name: ClassVar[str] = "GROUP_MSG_RECEIVE"


@dataclass(slots=True, kw_only=True)
class GroupMemberAdd(Event):
    event_name: ClassVar[str] = "GROUP_MEMBER_ADD"
    timestamp: int = 0
    group_openid: str = ""
    member_openid: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], **kwargs: Any) -> GroupMemberAdd:
        return cls(
            timestamp=as_int(data.get("timestamp")),
            group_openid=as_str(data.get("group_openid")),
            member_openid=as_str(data.get("member_openid")),
            raw=data,
            **meta(kwargs),
        )


@dataclass(slots=True, kw_only=True)
class GroupMemberRemove(Event):
    event_name: ClassVar[str] = "GROUP_MEMBER_REMOVE"
    timestamp: int = 0
    group_openid: str = ""
    member_openid: str = ""
    user_openid: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], **kwargs: Any) -> GroupMemberRemove:
        return cls(
            timestamp=as_int(data.get("timestamp")),
            group_openid=as_str(data.get("group_openid")),
            member_openid=as_str(data.get("member_openid")),
            user_openid=as_str(data.get("user_openid")),
            raw=data,
            **meta(kwargs),
        )


@dataclass(slots=True, kw_only=True)
class GroupJoinRequest(Event):
    """A user asked to join a group.

    The complete payload is available as :attr:`request`; frequently used
    fields are exposed as properties.
    """

    event_name: ClassVar[str] = "GROUP_JOIN_REQUEST"
    request: JoinRequest = field(default_factory=JoinRequest)

    @property
    def group_openid(self) -> str:
        return self.request.group_openid

    @property
    def join_request_id(self) -> str:
        return self.request.join_request_id

    @property
    def member_openid(self) -> str:
        return self.request.member_openid

    @property
    def username(self) -> str:
        return self.request.username

    @property
    def apply_source(self) -> str:
        return self.request.apply_source

    @property
    def risk_tips(self) -> str:
        return self.request.risk_tips

    @property
    def verify_message(self) -> str:
        info = self.request.verify_info
        return info.verify_message if info else ""

    @property
    def auto_approved(self) -> AutoApproved | None:
        return self.request.auto_approved

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], **kwargs: Any) -> GroupJoinRequest:
        return cls(request=JoinRequest.from_dict(data), raw=data, **meta(kwargs))


@dataclass(slots=True, kw_only=True)
class C2CMsgReject(Event):
    event_name: ClassVar[str] = "C2C_MSG_REJECT"
    openid: str = ""
    timestamp: int = 0

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], **kwargs: Any) -> C2CMsgReject:
        return cls(
            openid=as_str(data.get("openid")),
            timestamp=as_int(data.get("timestamp")),
            raw=data,
            **meta(kwargs),
        )


@dataclass(slots=True, kw_only=True)
class C2CMsgReceive(Event):
    event_name: ClassVar[str] = "C2C_MSG_RECEIVE"
    openid: str = ""
    timestamp: int = 0

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], **kwargs: Any) -> C2CMsgReceive:
        return cls(
            openid=as_str(data.get("openid")),
            timestamp=as_int(data.get("timestamp")),
            raw=data,
            **meta(kwargs),
        )


@dataclass(slots=True, kw_only=True)
class FriendAdd(Event):
    event_name: ClassVar[str] = "FRIEND_ADD"
    openid: str = ""
    timestamp: int = 0
    scene: int = 0
    scene_param: str = ""
    author: FriendAuthor | None = None
    short_code: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], **kwargs: Any) -> FriendAdd:
        author_raw = data.get("author")
        return cls(
            openid=as_str(data.get("openid")),
            timestamp=as_int(data.get("timestamp")),
            scene=as_int(data.get("scene")),
            scene_param=as_str(data.get("scene_param")),
            author=FriendAuthor.from_dict(author_raw) if isinstance(author_raw, Mapping) else None,
            short_code=as_str(data.get("short_code")),
            raw=data,
            **meta(kwargs),
        )


@dataclass(slots=True, kw_only=True)
class FriendDel(Event):
    event_name: ClassVar[str] = "FRIEND_DEL"
    openid: str = ""
    timestamp: int = 0
    author: FriendAuthor | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], **kwargs: Any) -> FriendDel:
        author_raw = data.get("author")
        return cls(
            openid=as_str(data.get("openid")),
            timestamp=as_int(data.get("timestamp")),
            author=FriendAuthor.from_dict(author_raw) if isinstance(author_raw, Mapping) else None,
            raw=data,
            **meta(kwargs),
        )


@dataclass(slots=True, kw_only=True)
class ReadyEvent(Event):
    """First event after a successful Identify."""

    event_name: ClassVar[str] = "READY"
    version: int = 1
    session_id: str = ""
    user: User = field(default_factory=User)
    shard: tuple[int, int] = (0, 0)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], **kwargs: Any) -> ReadyEvent:
        user_raw = data.get("user")
        shard_raw = data.get("shard")
        shard = (0, 0)
        if isinstance(shard_raw, (list, tuple)) and len(shard_raw) >= 2:
            shard = (as_int(shard_raw[0]), as_int(shard_raw[1]))
        return cls(
            version=as_int(data.get("version"), 1),
            session_id=as_str(data.get("session_id")),
            user=User.from_dict(user_raw) if isinstance(user_raw, Mapping) else User(),
            shard=shard,
            raw=data,
            **meta(kwargs),
        )


@dataclass(slots=True, kw_only=True)
class ResumedEvent(Event):
    """Emitted after the gateway has replayed missed events."""

    event_name: ClassVar[str] = "RESUMED"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], **kwargs: Any) -> ResumedEvent:
        return cls(raw=data if isinstance(data, Mapping) else {}, **meta(kwargs))


@dataclass(slots=True, kw_only=True)
class UnknownEvent(Event):
    """An event whose type is not modeled by this library."""

    name: str = ""
    data: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], **kwargs: Any) -> UnknownEvent:
        return cls(
            name=as_str(kwargs.get("name")),
            data=data,
            raw=data,
            **meta(kwargs),
        )


EVENT_REGISTRY: dict[str, type[Event]] = {
    C2CMessage.event_name: C2CMessage,
    GroupAtMessage.event_name: GroupAtMessage,
    GroupAllMessage.event_name: GroupAllMessage,
    InteractionEvent.event_name: InteractionEvent,
    GroupAddRobot.event_name: GroupAddRobot,
    GroupDelRobot.event_name: GroupDelRobot,
    GroupMsgReject.event_name: GroupMsgReject,
    GroupMsgReceive.event_name: GroupMsgReceive,
    GroupMemberAdd.event_name: GroupMemberAdd,
    GroupMemberRemove.event_name: GroupMemberRemove,
    GroupJoinRequest.event_name: GroupJoinRequest,
    C2CMsgReject.event_name: C2CMsgReject,
    C2CMsgReceive.event_name: C2CMsgReceive,
    FriendAdd.event_name: FriendAdd,
    FriendDel.event_name: FriendDel,
    ReadyEvent.event_name: ReadyEvent,
    ResumedEvent.event_name: ResumedEvent,
}


def parse_event(
    name: str,
    data: Mapping[str, Any] | None,
    *,
    event_id: str | None = None,
    seq: int | None = None,
) -> Event:
    """Convert a raw ``d`` object into a typed event.

    Unknown event names are preserved as :class:`UnknownEvent` so a new
    platform event never crashes the dispatcher.
    """

    payload = dict(data) if isinstance(data, Mapping) else {}
    model = EVENT_REGISTRY.get(name)
    if model is None:
        return UnknownEvent(name=name, data=payload, raw=payload, event_id=event_id, seq=seq)
    return model.from_dict(payload, event_id=event_id, seq=seq)


def event_dedup_key(event: Event) -> str:
    """Return a stable key used to suppress duplicate deliveries.

    Message events prefer ``message_scene.ext.msg_idx`` because the same
    ``msg_id`` may be pushed more than once.  Otherwise the envelope event id
    or the sequence number is used.
    """

    if isinstance(event, ChatMessage) and event.msg_idx:
        return f"{event.event_name}:{event.msg_idx}"
    if isinstance(event, ChatMessage) and event.id:
        return f"{event.event_name}:{event.id}"
    if event.event_id:
        return event.event_id
    if event.seq is not None:
        return f"{event.event_name}:{event.seq}"
    try:
        payload = _json_dumps(event.raw)
    except (TypeError, ValueError):
        payload = repr(event.raw).encode("utf-8", "replace")
    digest = hashlib.sha1(payload, usedforsecurity=False).hexdigest()
    return f"{event.event_name}:{digest}"


__all__ = [
    "C2CMsgReceive",
    "C2CMsgReject",
    "EVENT_REGISTRY",
    "FriendAdd",
    "FriendAuthor",
    "FriendDel",
    "GroupAddRobot",
    "GroupDelRobot",
    "GroupJoinRequest",
    "GroupMemberAdd",
    "GroupMemberRemove",
    "GroupMsgReceive",
    "GroupMsgReject",
    "GroupOperationEvent",
    "ReadyEvent",
    "ResumedEvent",
    "UnknownEvent",
    "event_dedup_key",
    "parse_event",
]
