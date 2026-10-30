"""Interactive callback models (``INTERACTION_CREATE``)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar

from ..constants import InteractionType
from .base import Event, Model, as_int, as_str, meta, parse_ext, parse_rfc3339


@dataclass(slots=True, kw_only=True)
class AuthorizeData(Model):
    """Authorization details for ``USER_AUTHORIZE`` / ``GROUP_AUTHORIZE``."""

    opt_scene: str = ""
    scope: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AuthorizeData:
        return cls(
            opt_scene=as_str(data.get("opt_scene")),
            scope=as_str(data.get("scope")),
            raw=data,
        )


@dataclass(slots=True, kw_only=True)
class InteractionMessageScene(Model):
    """Extra scene flags for message-feedback interactions."""

    ext: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> InteractionMessageScene:
        return cls(ext=parse_ext(data.get("ext")), raw=data)


@dataclass(slots=True, kw_only=True)
class InteractionResolved(Model):
    """Resolved values of an interaction payload."""

    button_data: str = ""
    button_id: str = ""
    user_id: str = ""
    feature_id: str = ""
    message_id: str = ""
    feedback_opt: str = ""
    checked: int = 0
    action: str = ""
    message_scene: InteractionMessageScene | None = None
    authorize_data: AuthorizeData | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> InteractionResolved:
        scene_raw = data.get("message_scene")
        auth_raw = data.get("authorize_data")
        return cls(
            button_data=as_str(data.get("button_data")),
            button_id=as_str(data.get("button_id")),
            user_id=as_str(data.get("user_id")),
            feature_id=as_str(data.get("feature_id")),
            message_id=as_str(data.get("message_id")),
            feedback_opt=as_str(data.get("feedback_opt")),
            checked=as_int(data.get("checked")),
            action=as_str(data.get("action")),
            message_scene=InteractionMessageScene.from_dict(scene_raw)
            if isinstance(scene_raw, Mapping)
            else None,
            authorize_data=AuthorizeData.from_dict(auth_raw)
            if isinstance(auth_raw, Mapping)
            else None,
            raw=data,
        )


@dataclass(slots=True, kw_only=True)
class InteractionData(Model):
    """The ``data`` object of an interaction event."""

    type: int = 0
    resolved: InteractionResolved = field(default_factory=InteractionResolved)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> InteractionData:
        resolved_raw = data.get("resolved")
        return cls(
            type=as_int(data.get("type")),
            resolved=InteractionResolved.from_dict(resolved_raw)
            if isinstance(resolved_raw, Mapping)
            else InteractionResolved(),
            raw=data,
        )


@dataclass(slots=True, kw_only=True)
class InteractionEvent(Event):
    """A user interaction such as a message-button click.

    ``type`` 11 (message button) and 12 (quick menu) must be acknowledged via
    :meth:`qqbot_toolkit.api.interactions.InteractionsAPI.respond`; the client
    otherwise shows a loading state until timeout.

    Two identifiers are present:

    * ``id`` - the interaction ID used by ``PUT /interactions/{id}``;
    * ``event_id`` (from :class:`~qqbot_toolkit.models.base.Event`) - the outer
      envelope ID used as ``event_id`` when sending a passive reply.
    """

    event_name: ClassVar[str] = "INTERACTION_CREATE"
    id: str = ""
    type: int = 0
    scene: str = ""
    chat_type: int = 0
    timestamp: datetime | None = None
    guild_id: str = ""
    channel_id: str = ""
    user_openid: str = ""
    group_openid: str = ""
    group_member_openid: str = ""
    data: InteractionData = field(default_factory=InteractionData)
    version: int = 1
    application_id: str = ""

    @property
    def resolved(self) -> InteractionResolved:
        return self.data.resolved

    @property
    def requires_response(self) -> bool:
        """Whether the event type requires a ``PUT /interactions`` call."""

        return self.type in {
            InteractionType.INLINE_KEYBOARD,
            InteractionType.CALLBACK_COMMAND,
        }

    @property
    def button_data(self) -> str:
        return self.data.resolved.button_data

    @property
    def button_id(self) -> str:
        return self.data.resolved.button_id

    @property
    def target_openid(self) -> str:
        """User OpenID for C2C, group OpenID for group interactions."""

        return self.user_openid or self.group_openid

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], **kwargs: Any) -> InteractionEvent:
        data_raw = data.get("data")
        return cls(
            id=as_str(data.get("id")),
            type=as_int(data.get("type")),
            scene=as_str(data.get("scene")),
            chat_type=as_int(data.get("chat_type")),
            timestamp=parse_rfc3339(data.get("timestamp")),
            guild_id=as_str(data.get("guild_id")),
            channel_id=as_str(data.get("channel_id")),
            user_openid=as_str(data.get("user_openid")),
            group_openid=as_str(data.get("group_openid")),
            group_member_openid=as_str(data.get("group_member_openid")),
            data=InteractionData.from_dict(data_raw)
            if isinstance(data_raw, Mapping)
            else InteractionData(),
            version=as_int(data.get("version"), 1),
            application_id=as_str(data.get("application_id")),
            raw=data,
            **meta(kwargs),
        )


__all__ = [
    "AuthorizeData",
    "InteractionData",
    "InteractionEvent",
    "InteractionMessageScene",
    "InteractionResolved",
]
