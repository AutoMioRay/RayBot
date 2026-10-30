"""Shared inbound structures: users, scenes, attachments and responses."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .base import (
    Model,
    as_bool,
    as_int,
    as_mapping,
    as_sequence,
    as_str,
    parse_ext,
    parse_rfc3339,
)


@dataclass(slots=True, kw_only=True)
class User(Model):
    """A user, group member or robot."""

    id: str = ""
    username: str = ""
    bot: bool = False
    union_openid: str = ""
    union_user_account: str = ""
    user_openid: str = ""
    member_openid: str = ""
    member_role: str = ""

    @property
    def openid(self) -> str:
        """Best available identifier for the current scenario."""

        return self.user_openid or self.member_openid or self.id

    @property
    def is_admin(self) -> bool:
        return self.member_role in {"admin", "owner"}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> User:
        return cls(
            id=as_str(data.get("id")),
            username=as_str(data.get("username")),
            bot=as_bool(data.get("bot")),
            union_openid=as_str(data.get("union_openid")),
            union_user_account=as_str(data.get("union_user_account")),
            user_openid=as_str(data.get("user_openid")),
            member_openid=as_str(data.get("member_openid")),
            member_role=as_str(data.get("member_role")),
            raw=data,
        )


@dataclass(slots=True, kw_only=True)
class MessageScene(Model):
    """Context attached to a message, including references and auth tokens."""

    source: str = "default"
    ext: Mapping[str, str] = field(default_factory=dict)

    @property
    def msg_idx(self) -> str:
        """Platform message index used for de-duplication."""

        return self.ext.get("msg_idx", "")

    @property
    def ref_msg_idx(self) -> str:
        """Index of the quoted message, when the message is a reply."""

        return self.ext.get("ref_msg_idx", "")

    @property
    def auth_token(self) -> str:
        return self.ext.get("auth_token", "")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> MessageScene:
        return cls(
            source=as_str(data.get("source"), "default"),
            ext=parse_ext(data.get("ext")),
            raw=data,
        )


@dataclass(slots=True, kw_only=True)
class MessageAttachment(Model):
    """An image, voice clip, video or file attached to a message."""

    url: str = ""
    filename: str = ""
    width: int = 0
    height: int = 0
    size: int = 0
    content_type: str = ""
    voice_wav_url: str = ""
    asr_refer_text: str = ""

    @property
    def is_image(self) -> bool:
        return self.content_type.startswith("image/")

    @property
    def is_voice(self) -> bool:
        return self.content_type == "voice"

    @property
    def is_video(self) -> bool:
        return self.content_type == "video/mp4"

    @property
    def is_file(self) -> bool:
        return self.content_type == "file"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> MessageAttachment:
        return cls(
            url=as_str(data.get("url")),
            filename=as_str(data.get("filename")),
            width=as_int(data.get("width")),
            height=as_int(data.get("height")),
            size=as_int(data.get("size")),
            content_type=as_str(data.get("content_type")),
            voice_wav_url=as_str(data.get("voice_wav_url")),
            asr_refer_text=as_str(data.get("asr_refer_text")),
            raw=data,
        )


@dataclass(slots=True, kw_only=True)
class ArkData(Model):
    """Structured card (ARK) content received from users."""

    prompt: str = ""
    ark_type: str = ""
    ark_name: str = ""
    fields: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ArkData:
        return cls(
            prompt=as_str(data.get("prompt")),
            ark_type=as_str(data.get("ark_type")),
            ark_name=as_str(data.get("ark_name")),
            fields=as_mapping(data.get("fields")),
            raw=data,
        )


@dataclass(slots=True, kw_only=True)
class MsgElement(Model):
    """A nested message element, used by quoted and merged messages."""

    msg_idx: str = ""
    author: User | None = None
    message_type: int = 0
    content: str = ""
    attachments: tuple[MessageAttachment, ...] = ()
    ark_data: ArkData | None = None
    msg_elements: tuple[MsgElement, ...] = ()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> MsgElement:
        author_raw = data.get("author")
        ark_raw = data.get("ark_data")
        return cls(
            msg_idx=as_str(data.get("msg_idx")),
            author=User.from_dict(author_raw) if isinstance(author_raw, Mapping) else None,
            message_type=as_int(data.get("message_type")),
            content=as_str(data.get("content")),
            attachments=as_sequence(data.get("attachments"), MessageAttachment.from_dict),
            ark_data=ArkData.from_dict(ark_raw) if isinstance(ark_raw, Mapping) else None,
            msg_elements=as_sequence(data.get("msg_elements"), MsgElement.from_dict),
            raw=data,
        )


@dataclass(slots=True, kw_only=True)
class MessageExtInfo(Model):
    """Reference index returned by send-message endpoints."""

    ref_idx: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> MessageExtInfo:
        return cls(ref_idx=as_str(data.get("ref_idx")), raw=data)


@dataclass(slots=True, kw_only=True)
class MessageResponse(Model):
    """Response of sending, streaming or uploading a message."""

    id: str = ""
    timestamp: datetime | None = None
    ext_info: MessageExtInfo | None = None
    remain_msg_len: int | None = None
    file_uuid: str = ""
    file_info: str = ""
    ttl: int | None = None
    raw_url: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> MessageResponse:
        ext_raw = data.get("ext_info")
        return cls(
            id=as_str(data.get("id")),
            timestamp=parse_rfc3339(data.get("timestamp")),
            ext_info=MessageExtInfo.from_dict(ext_raw) if isinstance(ext_raw, Mapping) else None,
            remain_msg_len=as_int(data["remain_msg_len"])
            if data.get("remain_msg_len") is not None
            else None,
            file_uuid=as_str(data.get("file_uuid")),
            file_info=as_str(data.get("file_info")),
            ttl=as_int(data["ttl"]) if data.get("ttl") is not None else None,
            raw_url=as_str(data.get("raw_url")),
            raw=data,
        )


@dataclass(slots=True, kw_only=True)
class UploadPart(Model):
    """One presigned part returned by ``upload_prepare``."""

    index: int = 0
    presigned_url: str = ""
    block_size: int = 0

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> UploadPart:
        return cls(
            index=as_int(data.get("index")),
            presigned_url=as_str(data.get("presigned_url")),
            block_size=as_int(data.get("block_size")),
            raw=data,
        )


@dataclass(slots=True, kw_only=True)
class UploadConfig(Model):
    """Server-provided concurrency and retry settings for chunked uploads."""

    concurrency: int = 1
    retry_timeout: int = 300
    retry_delay: int = 1

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> UploadConfig:
        return cls(
            concurrency=max(1, as_int(data.get("concurrency"), 1)),
            retry_timeout=as_int(data.get("retry_timeout"), 300),
            retry_delay=as_int(data.get("retry_delay"), 1),
            raw=data,
        )


@dataclass(slots=True, kw_only=True)
class UploadPrepareResult(Model):
    """Result of ``upload_prepare`` for chunked rich-media upload."""

    upload_id: str = ""
    block_size: int = 0
    parts: tuple[UploadPart, ...] = ()
    upload_config: UploadConfig = field(default_factory=UploadConfig)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> UploadPrepareResult:
        config_raw = data.get("upload_config")
        return cls(
            upload_id=as_str(data.get("upload_id")),
            block_size=as_int(data.get("block_size")),
            parts=as_sequence(data.get("parts"), UploadPart.from_dict),
            upload_config=UploadConfig.from_dict(config_raw)
            if isinstance(config_raw, Mapping)
            else UploadConfig(),
            raw=data,
        )


@dataclass(slots=True, kw_only=True)
class MaterialImage(Model):
    """An image uploaded through the ``media-images`` material API."""

    image_id: str = ""
    url: str = ""
    ttl: int = 0
    preview_url: str = ""
    file_name: str = ""
    created_at: int = 0
    expires_at: int = 0

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> MaterialImage:
        return cls(
            image_id=as_str(data.get("image_id")),
            url=as_str(data.get("url")),
            ttl=as_int(data.get("ttl")),
            preview_url=as_str(data.get("preview_url")),
            file_name=as_str(data.get("file_name")),
            created_at=as_int(data.get("created_at")),
            expires_at=as_int(data.get("expires_at")),
            raw=data,
        )


@dataclass(slots=True, kw_only=True)
class MaterialImagePage(Model):
    """One page of material images."""

    images: tuple[MaterialImage, ...] = ()
    next_cursor: str = ""
    total: int = 0

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> MaterialImagePage:
        return cls(
            images=as_sequence(data.get("images"), MaterialImage.from_dict),
            next_cursor=as_str(data.get("next_cursor")),
            total=as_int(data.get("total")),
            raw=data,
        )


@dataclass(slots=True, kw_only=True)
class BotProfile(Model):
    """The current robot's profile (``GET /users/@me``)."""

    id: str = ""
    username: str = ""
    avatar: str = ""
    bot: bool = False
    union_openid: str = ""
    union_user_account: str = ""
    share_url: str = ""
    welcome_msg: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> BotProfile:
        return cls(
            id=as_str(data.get("id")),
            username=as_str(data.get("username")),
            avatar=as_str(data.get("avatar")),
            bot=as_bool(data.get("bot")),
            union_openid=as_str(data.get("union_openid")),
            union_user_account=as_str(data.get("union_user_account")),
            share_url=as_str(data.get("share_url")),
            welcome_msg=as_str(data.get("welcome_msg")),
            raw=data,
        )


@dataclass(slots=True, kw_only=True)
class SessionStartLimit(Model):
    """Gateway session quota returned by ``/gateway/bot``."""

    total: int = 0
    remaining: int = 0
    reset_after: int = 0
    max_concurrency: int = 1

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SessionStartLimit:
        return cls(
            total=as_int(data.get("total")),
            remaining=as_int(data.get("remaining")),
            reset_after=as_int(data.get("reset_after")),
            max_concurrency=max(1, as_int(data.get("max_concurrency"), 1)),
            raw=data,
        )


@dataclass(slots=True, kw_only=True)
class GatewayInfo(Model):
    """WebSocket endpoint and sharding recommendation."""

    url: str = ""
    shards: int = 1
    session_start_limit: SessionStartLimit = field(default_factory=SessionStartLimit)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> GatewayInfo:
        limit_raw = data.get("session_start_limit")
        return cls(
            url=as_str(data.get("url")),
            shards=max(1, as_int(data.get("shards"), 1)),
            session_start_limit=SessionStartLimit.from_dict(limit_raw)
            if isinstance(limit_raw, Mapping)
            else SessionStartLimit(),
            raw=data,
        )


__all__ = [
    "ArkData",
    "BotProfile",
    "GatewayInfo",
    "MaterialImage",
    "MaterialImagePage",
    "MessageAttachment",
    "MessageExtInfo",
    "MessageResponse",
    "MessageScene",
    "MsgElement",
    "SessionStartLimit",
    "UploadConfig",
    "UploadPart",
    "UploadPrepareResult",
    "User",
]
