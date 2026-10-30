"""Single-chat and group-chat message sending, recall and streaming."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import quote_plus

from ..constants import MessageType
from ..models.common import MessageResponse
from ..models.messages import C2CMessage, GroupMessage
from ..models.outbound import (
    InputNotify,
    Keyboard,
    MediaInfo,
    MessageMarkdown,
    MessageReference,
    Payload,
)
from .base import BaseAPI, segment


def _payload(value: Payload | Mapping[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, Payload):
        return value.to_dict()
    return dict(value)


def _as_markdown(value: MessageMarkdown | str | None) -> MessageMarkdown | None:
    if value is None or isinstance(value, MessageMarkdown):
        return value
    return MessageMarkdown(content=value)


def _as_media(value: MediaInfo | str | None) -> MediaInfo | None:
    if value is None or isinstance(value, MediaInfo):
        return value
    return MediaInfo(file_info=value)


def _as_reference(
    value: MessageReference | str | None,
) -> MessageReference | None:
    if value is None or isinstance(value, MessageReference):
        return value
    return MessageReference(message_id=value)


def _build_body(
    *,
    content: str | None,
    markdown: MessageMarkdown | str | None,
    media: MediaInfo | str | None,
    keyboard: Keyboard | Mapping[str, Any] | None,
    msg_id: str | None,
    event_id: str | None,
    msg_seq: int,
    message_reference: MessageReference | str | None,
    msg_type: int | None,
    input_notify: InputNotify | Mapping[str, Any] | None = None,
    is_wakeup: bool | None = None,
    allow_stream_fields: bool = False,
) -> dict[str, Any]:
    if msg_id is not None and not msg_id:
        raise ValueError("msg_id must not be empty")
    if event_id is not None and not event_id:
        raise ValueError("event_id must not be empty")
    if msg_seq < 1:
        raise ValueError("msg_seq must be at least 1")
    if msg_id and event_id:
        raise ValueError("msg_id and event_id are mutually exclusive")
    if is_wakeup and (msg_id or event_id):
        raise ValueError("is_wakeup is mutually exclusive with msg_id and event_id")
    if not allow_stream_fields and input_notify is not None:
        raise ValueError("input_notify is only supported in single-chat messages")

    markdown_model = _as_markdown(markdown)
    media_model = _as_media(media)
    reference_model = _as_reference(message_reference)

    if msg_type is None:
        if input_notify is not None:
            msg_type = MessageType.INPUT_NOTIFY
        elif media_model is not None:
            msg_type = MessageType.MEDIA
        elif markdown_model is not None:
            msg_type = MessageType.MARKDOWN
        else:
            msg_type = MessageType.TEXT
    msg_type = int(msg_type)

    if msg_type == MessageType.TEXT and content is None:
        raise ValueError("content is required when msg_type=0")
    if msg_type == MessageType.MARKDOWN and markdown_model is None:
        raise ValueError("markdown is required when msg_type=2")
    if msg_type == MessageType.MEDIA and media_model is None:
        raise ValueError("media is required when msg_type=7")
    if msg_type == MessageType.INPUT_NOTIFY and input_notify is None:
        raise ValueError("input_notify is required when msg_type=6")
    if markdown_model is not None and content is not None and content != "":
        raise ValueError("content must be empty when markdown is used")

    body: dict[str, Any] = {"msg_type": msg_type, "msg_seq": msg_seq}
    if content is not None:
        body["content"] = content
    markdown_payload = _payload(markdown_model)
    if markdown_payload is not None:
        body["markdown"] = markdown_payload
    media_payload = _payload(media_model)
    if media_payload is not None:
        body["media"] = media_payload
    keyboard_payload = _payload(keyboard)
    if keyboard_payload is not None:
        body["keyboard"] = keyboard_payload
    reference_payload = _payload(reference_model)
    if reference_payload is not None:
        body["message_reference"] = reference_payload
    if msg_id is not None:
        body["msg_id"] = msg_id
    if event_id is not None:
        body["event_id"] = event_id
    if is_wakeup is not None:
        body["is_wakeup"] = is_wakeup
    input_payload = _payload(input_notify)
    if input_payload is not None:
        body["input_notify"] = input_payload
    return body


def _is_active(msg_id: str | None, event_id: str | None, is_wakeup: bool | None) -> bool:
    return not msg_id and not event_id and not is_wakeup


class C2CAPI(BaseAPI):
    """Single-chat (C2C) message endpoints."""

    async def send(
        self,
        user_openid: str,
        *,
        content: str | None = None,
        markdown: MessageMarkdown | str | None = None,
        media: MediaInfo | str | None = None,
        keyboard: Keyboard | Mapping[str, Any] | None = None,
        msg_id: str | None = None,
        event_id: str | None = None,
        msg_seq: int = 1,
        message_reference: MessageReference | str | None = None,
        is_wakeup: bool | None = None,
        input_notify: InputNotify | Mapping[str, Any] | None = None,
        msg_type: int | None = None,
    ) -> MessageResponse:
        """Send a message to one user.

        Args:
            user_openid: Recipient OpenID.
            content: Plain text (``msg_type=0``).
            markdown: Markdown object or raw Markdown string (``msg_type=2``).
            media: Uploaded ``file_info`` or :class:`MediaInfo` (``msg_type=7``).
            keyboard: Inline keyboard attached to the message.
            msg_id: Message ID from an inbound event, for a passive reply.
            event_id: Event ID for passive replies to C2C events such as
                ``FRIEND_ADD``.
            msg_seq: Reply sequence number. Use a new value for each reply to
                the same ``msg_id``; repeating the same pair is rejected.
            message_reference: Quote an earlier message.
            is_wakeup: Mark the message as an interaction-recall message.
            input_notify: Typing indicator (``msg_type=6``).
            msg_type: Explicit message type; inferred from the content fields
                when omitted.

        Returns:
            The platform response containing the new message ID.

        Raises:
            ValueError: If the content fields do not match the message type.
            APIError: If the platform rejects the message.
        """

        body = _build_body(
            content=content,
            markdown=markdown,
            media=media,
            keyboard=keyboard,
            msg_id=msg_id,
            event_id=event_id,
            msg_seq=msg_seq,
            message_reference=message_reference,
            msg_type=msg_type,
            input_notify=input_notify,
            is_wakeup=is_wakeup,
            allow_stream_fields=True,
        )
        active = _is_active(msg_id, event_id, is_wakeup)
        data = await self._client.post(
            f"/v2/users/{segment(user_openid)}/messages",
            json=body,
            route="message.send.c2c",
            relation_scope="message.active.c2c" if active else None,
            relation_key=user_openid if active else None,
        )
        return MessageResponse.from_dict(data or {})

    async def send_text(self, user_openid: str, content: str, **kwargs: Any) -> MessageResponse:
        """Send plain text to one user."""

        return await self.send(user_openid, content=content, **kwargs)

    async def send_markdown(
        self, user_openid: str, markdown: MessageMarkdown | str, **kwargs: Any
    ) -> MessageResponse:
        """Send Markdown to one user."""

        return await self.send(user_openid, markdown=markdown, **kwargs)

    async def send_media(self, user_openid: str, file_info: str, **kwargs: Any) -> MessageResponse:
        """Send a previously uploaded rich-media file to one user."""

        return await self.send(user_openid, media=file_info, **kwargs)

    async def recall(self, user_openid: str, message_id: str) -> None:
        """Recall a message. Messages older than two minutes cannot be recalled."""

        await self._client.delete(
            f"/v2/users/{segment(user_openid)}/messages/{segment(message_id)}",
            route="message.recall.c2c",
        )

    async def send_stream(
        self,
        user_openid: str,
        *,
        content_raw: str,
        content_type: str = "markdown",
        input_state: int = 1,
        input_mode: str = "append",
        index: int = 0,
        stream_msg_id: str | None = None,
        msg_id: str | None = None,
        event_id: str | None = None,
        msg_seq: int = 1,
        is_wakeup: bool | None = None,
    ) -> MessageResponse:
        """Send one chunk of a streaming answer.

        The first chunk omits ``stream_msg_id``; the response ``id`` becomes the
        stream ID for every later chunk.  ``input_state=10`` marks the end.
        """

        if msg_id and event_id:
            raise ValueError("msg_id and event_id are mutually exclusive")
        if input_state not in {1, 10}:
            raise ValueError("input_state must be 1 (generating) or 10 (finished)")
        if input_mode not in {"append", "replace"}:
            raise ValueError("input_mode must be 'append' or 'replace'")
        if content_type not in {"text", "markdown"}:
            raise ValueError("content_type must be 'text' or 'markdown'")
        if msg_seq < 1:
            raise ValueError("msg_seq must be at least 1")
        body: dict[str, Any] = {
            "input_mode": input_mode,
            "input_state": input_state,
            "index": index,
            "content_type": content_type,
            "content_raw": content_raw,
            "msg_seq": msg_seq,
        }
        if stream_msg_id is not None:
            body["stream_msg_id"] = stream_msg_id
        if msg_id is not None:
            body["msg_id"] = msg_id
        if event_id is not None:
            body["event_id"] = event_id
        if is_wakeup is not None:
            body["is_wakeup"] = is_wakeup

        data = await self._client.post(
            f"/v2/users/{segment(user_openid)}/stream_messages",
            json=body,
            route="message.stream.c2c",
        )
        return MessageResponse.from_dict(data or {})

    def stream(
        self,
        user_openid: str,
        *,
        content_type: str = "markdown",
        input_mode: str = "append",
        msg_id: str | None = None,
        event_id: str | None = None,
        msg_seq: int = 1,
        is_wakeup: bool | None = None,
    ) -> C2CStreamSession:
        """Create a helper that tracks ``index`` and ``stream_msg_id``."""

        return C2CStreamSession(
            self,
            user_openid,
            content_type=content_type,
            input_mode=input_mode,
            msg_id=msg_id,
            event_id=event_id,
            msg_seq=msg_seq,
            is_wakeup=is_wakeup,
        )


class C2CStreamSession:
    """Stateful helper for the C2C streaming endpoint."""

    __slots__ = (
        "_api",
        "_user_openid",
        "_content_type",
        "_input_mode",
        "_msg_id",
        "_event_id",
        "_msg_seq",
        "_is_wakeup",
        "index",
        "stream_msg_id",
        "finished",
    )

    def __init__(
        self,
        api: C2CAPI,
        user_openid: str,
        *,
        content_type: str,
        input_mode: str,
        msg_id: str | None,
        event_id: str | None,
        msg_seq: int,
        is_wakeup: bool | None,
    ) -> None:
        self._api = api
        self._user_openid = user_openid
        self._content_type = content_type
        self._input_mode = input_mode
        self._msg_id = msg_id
        self._event_id = event_id
        self._msg_seq = msg_seq
        self._is_wakeup = is_wakeup
        self.index = 0
        self.stream_msg_id: str | None = None
        self.finished = False

    async def push(self, chunk: str) -> MessageResponse:
        """Send one chunk. In ``replace`` mode pass the full text so far."""

        if self.finished:
            raise RuntimeError("streaming session is already finished")
        response = await self._api.send_stream(
            self._user_openid,
            content_raw=chunk,
            content_type=self._content_type,
            input_state=1,
            input_mode=self._input_mode,
            index=self.index,
            stream_msg_id=self.stream_msg_id,
            msg_id=self._msg_id,
            event_id=self._event_id,
            msg_seq=self._msg_seq,
            is_wakeup=self._is_wakeup,
        )
        if self.stream_msg_id is None:
            self.stream_msg_id = response.id
        self.index += 1
        return response

    async def finish(self, final_chunk: str | None = None) -> MessageResponse:
        """Send the final state (``input_state=10``) and close the session."""

        if self.finished:
            raise RuntimeError("streaming session is already finished")
        response = await self._api.send_stream(
            self._user_openid,
            content_raw=final_chunk or "",
            content_type=self._content_type,
            input_state=10,
            input_mode=self._input_mode,
            index=self.index,
            stream_msg_id=self.stream_msg_id,
            msg_id=self._msg_id,
            event_id=self._event_id,
            msg_seq=self._msg_seq,
            is_wakeup=self._is_wakeup,
        )
        if self.stream_msg_id is None:
            self.stream_msg_id = response.id
        self.index += 1
        self.finished = True
        return response


class GroupAPI(BaseAPI):
    """Group message endpoints."""

    async def send(
        self,
        group_openid: str,
        *,
        content: str | None = None,
        markdown: MessageMarkdown | str | None = None,
        media: MediaInfo | str | None = None,
        keyboard: Keyboard | Mapping[str, Any] | None = None,
        msg_id: str | None = None,
        event_id: str | None = None,
        msg_seq: int = 1,
        message_reference: MessageReference | str | None = None,
        msg_type: int | None = None,
    ) -> MessageResponse:
        """Send a message to a group.

        Group messages support text, Markdown and rich media but not the typing
        indicator, interaction-recall flag or streaming API.

        Args:
            group_openid: Target group OpenID.
            content: Plain text (``msg_type=0``).
            markdown: Markdown object or raw string (``msg_type=2``).
            media: Uploaded ``file_info`` (``msg_type=7``).
            keyboard: Inline keyboard.
            msg_id: Inbound message ID for a passive reply.
            event_id: Event ID for passive replies to ``INTERACTION_CREATE``,
                ``GROUP_ADD_ROBOT`` or ``GROUP_MSG_RECEIVE``.
            msg_seq: Reply sequence number, unique per ``msg_id``.
            message_reference: Quote a previous message.
            msg_type: Explicit message type; inferred when omitted.

        Returns:
            The platform response containing the new message ID.
        """

        body = _build_body(
            content=content,
            markdown=markdown,
            media=media,
            keyboard=keyboard,
            msg_id=msg_id,
            event_id=event_id,
            msg_seq=msg_seq,
            message_reference=message_reference,
            msg_type=msg_type,
            allow_stream_fields=False,
        )
        active = _is_active(msg_id, event_id, None)
        data = await self._client.post(
            f"/v2/groups/{segment(group_openid)}/messages",
            json=body,
            route="message.send.group",
            relation_scope="message.active.group" if active else None,
            relation_key=group_openid if active else None,
        )
        return MessageResponse.from_dict(data or {})

    async def send_text(self, group_openid: str, content: str, **kwargs: Any) -> MessageResponse:
        """Send plain text to a group."""

        return await self.send(group_openid, content=content, **kwargs)

    async def send_markdown(
        self, group_openid: str, markdown: MessageMarkdown | str, **kwargs: Any
    ) -> MessageResponse:
        """Send Markdown to a group."""

        return await self.send(group_openid, markdown=markdown, **kwargs)

    async def send_media(self, group_openid: str, file_info: str, **kwargs: Any) -> MessageResponse:
        """Send a previously uploaded rich-media file to a group."""

        return await self.send(group_openid, media=file_info, **kwargs)

    async def recall(self, group_openid: str, message_id: str) -> None:
        """Recall a group message.

        A robot that is a group administrator may also recall messages from
        ordinary members; otherwise only its own messages can be recalled.
        """

        await self._client.delete(
            f"/v2/groups/{segment(group_openid)}/messages/{segment(message_id)}",
            route="message.recall.group",
        )


def mention(member_openid: str) -> str:
    """Return the text token that mentions one group member.

    The OpenID is percent-encoded so a crafted value cannot break out of the
    ``id`` attribute and inject additional markup tokens; ordinary OpenIDs are
    alphanumeric and pass through unchanged.
    """

    return f'<qqbot-at-user id="{quote_plus(member_openid)}" />'


def command_enter(text: str) -> str:
    """Return a Markdown token that sends ``text`` when clicked.

    Only Markdown messages support this token.  C2C is the only scenario that
    documents the enter-command behaviour.
    """

    return f'<qqbot-cmd-enter text="{quote_plus(text)}" />'


def command_input(text: str, *, show: str | None = None, reference: bool = False) -> str:
    """Return a Markdown token that inserts ``text`` into the input box.

    Args:
        text: Inserted command text.
        show: Text displayed in the message; defaults to the platform behaviour.
        reference: Whether the inserted text quotes the current message.
    """

    parts = [f'text="{quote_plus(text)}"']
    if show is not None:
        parts.append(f'show="{quote_plus(show)}"')
    if reference:
        parts.append('reference="true"')
    return f"<qqbot-cmd-input {' '.join(parts)} />"


def reply_target(event: C2CMessage | GroupMessage) -> tuple[str, str]:
    """Return ``(kind, openid)`` for replying to a message event."""

    if isinstance(event, C2CMessage):
        return "c2c", event.user_openid
    if isinstance(event, GroupMessage):
        return "group", event.group_openid
    raise TypeError(f"unsupported message event: {type(event).__name__}")


__all__ = [
    "C2CAPI",
    "C2CStreamSession",
    "GroupAPI",
    "command_enter",
    "command_input",
    "mention",
    "reply_target",
]
