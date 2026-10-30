"""A modular, asyncio-native QQ bot component library.

The public API is grouped into:
    * :class:`Bot` - composition root and lifecycle;
    * ``api`` - typed OpenAPI groups;
    * ``models`` - inbound models and outbound payloads;
    * ``events`` - event bus, payload envelope and de-duplication;
    * ``gateway`` - the WebSocket transport.

This release supports the WebSocket transport only.
"""

from .api.gateway import GatewayAPI
from .api.groups import GroupsAPI
from .api.interactions import InteractionsAPI
from .api.media import MediaAPI, MediaTarget
from .api.messages import (
    C2CAPI,
    C2CStreamSession,
    GroupAPI,
    command_enter,
    command_input,
    mention,
)
from .api.robot import BotAPI
from .auth import TokenManager, TokenStats
from .bot import Bot, ReplySequencer
from .config import BotConfig, GatewayConfig, HTTPConfig
from .constants import (
    API_BASE_URL,
    DEFAULT_INTENTS,
    ChatScene,
    ChatType,
    FileType,
    Intents,
    InteractionCode,
    InteractionType,
    MemberRole,
    MessageType,
    OpCode,
    ReceiveMessageType,
    __version__,
)
from .errors import (
    APIError,
    AuthenticationError,
    ConfigurationError,
    GatewayError,
    PayloadError,
    QQBotError,
)
from .events import Deduplicator, EventBus, GatewayPayload
from .gateway import ShardManager
from .http import APIClient, RateLimitRegistry, RateRule
from .models import (
    BotProfile,
    C2CMessage,
    ChatMessage,
    Event,
    GroupAllMessage,
    GroupAtMessage,
    GroupMessage,
    InteractionEvent,
    MessageResponse,
    Model,
    ReadyEvent,
    UnknownEvent,
    parse_event,
)

__all__ = [
    "API_BASE_URL",
    "APIError",
    "APIClient",
    "AuthenticationError",
    "Bot",
    "BotAPI",
    "BotConfig",
    "BotProfile",
    "C2CAPI",
    "C2CMessage",
    "C2CStreamSession",
    "ChatMessage",
    "ChatScene",
    "ChatType",
    "ConfigurationError",
    "DEFAULT_INTENTS",
    "Deduplicator",
    "Event",
    "EventBus",
    "FileType",
    "GatewayAPI",
    "GatewayConfig",
    "GatewayError",
    "GatewayPayload",
    "GroupAPI",
    "GroupAllMessage",
    "GroupAtMessage",
    "GroupMessage",
    "GroupsAPI",
    "HTTPConfig",
    "Intents",
    "InteractionCode",
    "InteractionEvent",
    "InteractionType",
    "InteractionsAPI",
    "MediaAPI",
    "MediaTarget",
    "MemberRole",
    "MessageResponse",
    "MessageType",
    "Model",
    "OpCode",
    "PayloadError",
    "QQBotError",
    "RateLimitRegistry",
    "RateRule",
    "ReadyEvent",
    "ReceiveMessageType",
    "ReplySequencer",
    "ShardManager",
    "TokenManager",
    "TokenStats",
    "UnknownEvent",
    "__version__",
    "command_enter",
    "command_input",
    "mention",
    "parse_event",
]
