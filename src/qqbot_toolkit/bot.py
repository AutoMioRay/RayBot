"""High-level bot facade tying the API groups and transports together."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

import httpx

from .api.gateway import GatewayAPI
from .api.groups import GroupsAPI
from .api.interactions import InteractionsAPI
from .api.media import MediaAPI
from .api.messages import C2CAPI, GroupAPI
from .api.robot import BotAPI
from .auth import TokenManager
from .config import BotConfig
from .constants import InteractionType
from .events.bus import ErrorHandler, EventBus, Handler
from .events.dedup import Deduplicator
from .gateway.ws import ShardManager
from .http import APIClient
from .models.base import Event
from .models.common import MessageResponse
from .models.events import (
    C2CMsgReceive,
    C2CMsgReject,
    FriendAdd,
    FriendDel,
    GroupAddRobot,
    GroupDelRobot,
    GroupJoinRequest,
    GroupMemberAdd,
    GroupMemberRemove,
    GroupMsgReceive,
    GroupMsgReject,
)
from .models.interaction import InteractionEvent
from .models.messages import C2CMessage, GroupMessage
from .models.outbound import Keyboard, MediaInfo, MessageMarkdown, MessageReference

logger = logging.getLogger(__name__)


class ReplySequencer:
    """Generate increasing ``msg_seq`` values for passive replies.

    QQ rejects a repeated ``msg_id + msg_seq`` pair.  Each inbound message gets
    its own counter and entries expire so long-running bots do not grow without
    bound.
    """

    __slots__ = ("_ttl", "_max_entries", "_entries")

    def __init__(self, *, ttl: float = 900.0, max_entries: int = 20_000) -> None:
        self._ttl = ttl
        self._max_entries = max_entries
        self._entries: OrderedDict[str, tuple[int, float]] = OrderedDict()

    def next(self, key: str) -> int:
        """Return the next sequence number for ``key``."""

        now = time.monotonic()
        self._purge(now)
        previous = self._entries.pop(key, None)
        sequence = previous[0] + 1 if previous else 1
        self._entries[key] = (sequence, now)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)
        return sequence

    def _purge(self, now: float) -> None:
        boundary = now - self._ttl
        while self._entries:
            key, (_, seen_at) = next(iter(self._entries.items()))
            if seen_at >= boundary:
                return
            self._entries.popitem(last=False)


class Bot:
    """Composition root for configuration, APIs, transports and handlers."""

    def __init__(
        self,
        config: BotConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        http_client: httpx.AsyncClient | None = None,
        plain_client: httpx.AsyncClient | None = None,
        bus: EventBus | None = None,
    ) -> None:
        self.config = config
        self._tokens = TokenManager(
            config.app_id,
            config.client_secret,
            config.http,
            transport=transport,
        )
        self._http = APIClient(
            self._tokens,
            config.http,
            transport=transport,
            http_client=http_client,
        )
        self.c2c = C2CAPI(self._http)
        self.group = GroupAPI(self._http)
        self.groups = GroupsAPI(self._http)
        self.media = MediaAPI(self._http, config.http, plain_client=plain_client)
        self.bot = BotAPI(self._http)
        self.interactions = InteractionsAPI(self._http)
        self.gateway_api = GatewayAPI(self._http, config.gateway)
        self.bus = bus or EventBus(
            concurrency=config.gateway.dispatch_concurrency,
            queue_size=config.gateway.dispatch_queue_size,
            overflow=config.gateway.dispatch_overflow,
        )
        self._dedup = Deduplicator(
            ttl=config.gateway.dedup_ttl,
            max_size=config.gateway.dedup_max_size,
        )
        self._gateway = ShardManager(
            self._tokens, self.gateway_api, config.gateway, self.bus, self._dedup
        )
        self._replies = ReplySequencer()
        self._gateway_task: asyncio.Task[None] | None = None
        self._started = False
        self._closed = False
        self._stop_event = asyncio.Event()

    # ------------------------------------------------------------------ handlers

    def on(
        self, event_name: str, *, priority: int = 0, once: bool = False
    ) -> Callable[[Handler], Handler]:
        """Subscribe a handler to one raw event name."""

        return self.bus.on(event_name, priority=priority, once=once)

    def _on_many(
        self, event_names: tuple[str, ...], *, priority: int = 0, once: bool = False
    ) -> Callable[[Handler], Handler]:
        def decorator(handler: Handler) -> Handler:
            for name in event_names:
                self.bus.subscribe(name, handler, priority=priority, once=once)
            return handler

        return decorator

    def on_c2c_message(
        self, *, priority: int = 0, once: bool = False
    ) -> Callable[[Handler], Handler]:
        """Handle ``C2C_MESSAGE_CREATE`` events."""

        return self._on_many((C2CMessage.event_name,), priority=priority, once=once)

    def on_group_at_message(
        self, *, priority: int = 0, once: bool = False
    ) -> Callable[[Handler], Handler]:
        """Handle group messages that mention the robot."""

        return self._on_many(("GROUP_AT_MESSAGE_CREATE",), priority=priority, once=once)

    def on_group_message(
        self, *, priority: int = 0, once: bool = False
    ) -> Callable[[Handler], Handler]:
        """Handle both @-messages and full-mode group messages."""

        return self._on_many(
            ("GROUP_AT_MESSAGE_CREATE", "GROUP_MESSAGE_CREATE"),
            priority=priority,
            once=once,
        )

    def on_message(self, *, priority: int = 0, once: bool = False) -> Callable[[Handler], Handler]:
        """Handle C2C and both group message event types."""

        return self._on_many(
            ("C2C_MESSAGE_CREATE", "GROUP_AT_MESSAGE_CREATE", "GROUP_MESSAGE_CREATE"),
            priority=priority,
            once=once,
        )

    def on_interaction(
        self, *, priority: int = 0, once: bool = False
    ) -> Callable[[Handler], Handler]:
        """Handle ``INTERACTION_CREATE`` events."""

        return self._on_many((InteractionEvent.event_name,), priority=priority, once=once)

    def on_group_join_request(
        self, *, priority: int = 0, once: bool = False
    ) -> Callable[[Handler], Handler]:
        """Handle join requests. The robot must be a group administrator."""

        return self._on_many((GroupJoinRequest.event_name,), priority=priority, once=once)

    def on_group_member_add(
        self, *, priority: int = 0, once: bool = False
    ) -> Callable[[Handler], Handler]:
        """Handle new group members."""

        return self._on_many((GroupMemberAdd.event_name,), priority=priority, once=once)

    def on_group_member_remove(
        self, *, priority: int = 0, once: bool = False
    ) -> Callable[[Handler], Handler]:
        """Handle members leaving or being removed."""

        return self._on_many((GroupMemberRemove.event_name,), priority=priority, once=once)

    def on_group_add_robot(
        self, *, priority: int = 0, once: bool = False
    ) -> Callable[[Handler], Handler]:
        """Handle the robot being added to a group."""

        return self._on_many((GroupAddRobot.event_name,), priority=priority, once=once)

    def on_group_del_robot(
        self, *, priority: int = 0, once: bool = False
    ) -> Callable[[Handler], Handler]:
        """Handle the robot being removed from a group."""

        return self._on_many((GroupDelRobot.event_name,), priority=priority, once=once)

    def on_group_msg_receive(
        self, *, priority: int = 0, once: bool = False
    ) -> Callable[[Handler], Handler]:
        """Handle a group administrator enabling bot notifications."""

        return self._on_many((GroupMsgReceive.event_name,), priority=priority, once=once)

    def on_group_msg_reject(
        self, *, priority: int = 0, once: bool = False
    ) -> Callable[[Handler], Handler]:
        """Handle a group administrator disabling bot notifications."""

        return self._on_many((GroupMsgReject.event_name,), priority=priority, once=once)

    def on_friend_add(
        self, *, priority: int = 0, once: bool = False
    ) -> Callable[[Handler], Handler]:
        """Handle users adding the robot."""

        return self._on_many((FriendAdd.event_name,), priority=priority, once=once)

    def on_friend_del(
        self, *, priority: int = 0, once: bool = False
    ) -> Callable[[Handler], Handler]:
        """Handle users removing the robot."""

        return self._on_many((FriendDel.event_name,), priority=priority, once=once)

    def on_c2c_msg_receive(
        self, *, priority: int = 0, once: bool = False
    ) -> Callable[[Handler], Handler]:
        """Handle a user enabling active messages."""

        return self._on_many((C2CMsgReceive.event_name,), priority=priority, once=once)

    def on_c2c_msg_reject(
        self, *, priority: int = 0, once: bool = False
    ) -> Callable[[Handler], Handler]:
        """Handle a user disabling active messages."""

        return self._on_many((C2CMsgReject.event_name,), priority=priority, once=once)

    def on_raw(self, *, priority: int = 0) -> Callable[[Handler], Handler]:
        """Handle every event, including unknown event names."""

        def decorator(handler: Handler) -> Handler:
            self.bus.subscribe_all(handler, priority=priority)
            return handler

        return decorator

    def on_error(self, handler: ErrorHandler) -> ErrorHandler:
        """Register a handler for exceptions raised by event handlers."""

        return self.bus.on_error(handler)

    # ------------------------------------------------------------------ replies

    async def reply(
        self,
        event: Event,
        content: str | None = None,
        *,
        markdown: MessageMarkdown | str | None = None,
        media: MediaInfo | str | None = None,
        keyboard: Keyboard | dict[str, Any] | None = None,
        message_reference: MessageReference | str | None = None,
        msg_seq: int | None = None,
        **kwargs: Any,
    ) -> MessageResponse:
        """Reply to an inbound message or interaction event.

        The target channel and passive ``msg_id`` / ``event_id`` are derived
        from the event.  ``msg_seq`` is generated automatically so multiple
        replies to the same message are accepted.

        Raises:
            TypeError: If the event is not a message or interaction that can be
                replied to.
            ValueError: If an interaction is missing its target OpenID.
        """

        sequence = msg_seq
        if isinstance(event, C2CMessage):
            if sequence is None:
                sequence = self._replies.next(event.id)
            return await self.c2c.send(
                event.user_openid,
                content=content,
                markdown=markdown,
                media=media,
                keyboard=keyboard,
                message_reference=message_reference,
                msg_id=event.id,
                msg_seq=sequence,
                **kwargs,
            )
        if isinstance(event, GroupMessage):
            if sequence is None:
                sequence = self._replies.next(event.id)
            return await self.group.send(
                event.group_openid,
                content=content,
                markdown=markdown,
                media=media,
                keyboard=keyboard,
                message_reference=message_reference,
                msg_id=event.id,
                msg_seq=sequence,
                **kwargs,
            )
        if isinstance(event, InteractionEvent):
            # ``d.id`` is the interaction ID for PUT /interactions/{id}; the
            # passive-message ``event_id`` is the outer envelope id.
            reply_event_id = event.event_id
            if not reply_event_id:
                raise ValueError(
                    "interaction event has no envelope id; cannot send a passive reply"
                )
            if sequence is None:
                sequence = self._replies.next(event.id)
            if event.user_openid:
                return await self.c2c.send(
                    event.user_openid,
                    content=content,
                    markdown=markdown,
                    media=media,
                    keyboard=keyboard,
                    message_reference=message_reference,
                    event_id=reply_event_id,
                    msg_seq=sequence,
                    **kwargs,
                )
            if event.group_openid:
                return await self.group.send(
                    event.group_openid,
                    content=content,
                    markdown=markdown,
                    media=media,
                    keyboard=keyboard,
                    message_reference=message_reference,
                    event_id=reply_event_id,
                    msg_seq=sequence,
                    **kwargs,
                )
            raise ValueError("interaction has no user_openid or group_openid")
        raise TypeError(f"event cannot be replied to: {type(event).__name__}")

    async def reply_text(self, event: Event, content: str, **kwargs: Any) -> MessageResponse:
        """Reply with plain text."""

        return await self.reply(event, content, **kwargs)

    async def reply_markdown(
        self, event: Event, markdown: MessageMarkdown | str, **kwargs: Any
    ) -> MessageResponse:
        """Reply with Markdown."""

        return await self.reply(event, markdown=markdown, **kwargs)

    async def reply_media(self, event: Event, file_info: str, **kwargs: Any) -> MessageResponse:
        """Reply with a previously uploaded rich-media file."""

        return await self.reply(event, media=file_info, **kwargs)

    async def acknowledge_interaction(self, event: InteractionEvent, code: int = 0) -> None:
        """Acknowledge a button or quick-menu interaction.

        Call this within three seconds for ``type`` 11 and 12 events.
        ``event.id`` is the interaction ID used by
        ``PUT /interactions/{interaction_id}``; passive message replies use the
        outer envelope ``event.event_id`` instead.
        """

        if event.type not in {
            InteractionType.INLINE_KEYBOARD,
            InteractionType.CALLBACK_COMMAND,
        }:
            return
        await self.interactions.respond(event.id, code)

    # ------------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        """Start the event bus and the WebSocket gateway.

        The Webhook transport has been archived (see ``archive/webhook/``);
        passing ``webhook=...`` now fails with a :class:`TypeError`.
        """

        if self._closed:
            raise RuntimeError("bot is closed")
        if self._started:
            return
        self._started = True
        self.bus.start()
        self._gateway_task = self._gateway.start()

    async def stop(self) -> None:
        """Stop all transports and drain queued events."""

        self._stop_event.set()
        if self._gateway_task is not None:
            await self._gateway.stop()
            self._gateway_task = None
        if self._started:
            await self.bus.stop(drain=True)
            self._started = False

    async def aclose(self) -> None:
        """Release HTTP connections and cached credentials."""

        if self._closed:
            return
        await self.stop()
        await self.media.aclose()
        await self._http.aclose()
        await self._tokens.aclose()
        self._closed = True

    async def run_forever(self) -> None:
        """Start the gateway and wait until :meth:`stop` is called."""

        await self.start()
        try:
            await self._stop_event.wait()
        finally:
            await self.aclose()

    def run(self) -> None:
        """Blocking convenience wrapper around :meth:`run_forever`."""

        try:
            asyncio.run(self.run_forever())
        except KeyboardInterrupt:
            logger.info("interrupted, shutting down")

    @property
    def tokens(self) -> TokenManager:
        return self._tokens

    @property
    def http(self) -> APIClient:
        return self._http


__all__ = ["Bot", "ReplySequencer"]
