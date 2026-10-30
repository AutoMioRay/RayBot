"""Protocol constants shared by the HTTP, gateway and model layers."""

from __future__ import annotations

from enum import IntEnum, IntFlag, StrEnum

__version__ = "0.1.0"

API_BASE_URL = "https://api.bot.qq.com"
DEFAULT_GATEWAY_ENDPOINT = "/gateway/bot"
FALLBACK_GATEWAY_ENDPOINT = "/gateway"


class OpCode(IntEnum):
    """Gateway opcodes defined by the QQ Bot event protocol."""

    DISPATCH = 0
    HEARTBEAT = 1
    IDENTIFY = 2
    RESUME = 6
    RECONNECT = 7
    INVALID_SESSION = 9
    HELLO = 10
    HEARTBEAT_ACK = 11
    HTTP_CALLBACK_ACK = 12
    CALLBACK_VALIDATION = 13


class Intents(IntFlag):
    """Event subscription bit mask.

    Only intents granted to the robot may be used.  Subscribing to an intent
    without permission closes the WebSocket connection.
    """

    GUILDS = 1 << 0
    GUILD_MEMBERS = 1 << 1
    GUILD_MESSAGES = 1 << 9
    GUILD_MESSAGE_REACTIONS = 1 << 10
    DIRECT_MESSAGE = 1 << 12
    GROUP_MEMBER_EVENT = 1 << 24
    GROUP_AND_C2C_EVENT = 1 << 25
    INTERACTION = 1 << 26
    MESSAGE_AUDIT = 1 << 27
    FORUMS_EVENT = 1 << 28
    AUDIO_ACTION = 1 << 29
    PUBLIC_GUILD_MESSAGES = 1 << 30


DEFAULT_INTENTS = Intents.GROUP_AND_C2C_EVENT | Intents.GROUP_MEMBER_EVENT | Intents.INTERACTION


class MessageType(IntEnum):
    """Outgoing ``msg_type`` values."""

    TEXT = 0
    MARKDOWN = 2
    ARK = 3
    INPUT_NOTIFY = 6
    MEDIA = 7


class ReceiveMessageType(IntEnum):
    """Incoming ``message_type`` values."""

    TEXT = 0
    ARK = 3
    PARALLEL = 101
    CHAT_RECORD = 102
    QUOTE = 103


class FileType(IntEnum):
    """Rich media ``file_type`` values."""

    IMAGE = 1
    VIDEO = 2
    VOICE = 3
    FILE = 4


class ChatScene(StrEnum):
    """Scene names used in interaction payloads."""

    C2C = "c2c"
    GROUP = "group"
    GUILD = "guild"


class ChatType(IntEnum):
    """Numeric chat-scene identifiers used in interaction payloads."""

    GUILD = 0
    GROUP = 1
    C2C = 2


class MemberRole(StrEnum):
    """Group member roles returned by member and bot-state endpoints."""

    MEMBER = "member"
    ADMIN = "admin"
    OWNER = "owner"


class InteractionType(IntEnum):
    """``INTERACTION_CREATE`` event types that require different handling."""

    INLINE_KEYBOARD = 11
    CALLBACK_COMMAND = 12
    MESSAGE_FEEDBACK = 13
    CLEAR_SESSION = 14
    IN_OUT_STORY = 15
    SWITCH_MODEL = 16
    USER_AUTHORIZE = 18
    GROUP_AUTHORIZE = 19
    GROUP_AUTHORIZE_STATUS = 20


class InteractionCode(IntEnum):
    """Response codes for ``PUT /interactions/{interaction_id}``."""

    SUCCESS = 0
    FAILED = 1
    RATE_LIMITED = 2
    DUPLICATE = 3
    FORBIDDEN = 4
    ADMIN_ONLY = 5


# WebSocket close codes that permit or forbid a reconnect.  4004 means the
# platform rejected the token; retrying with the same credentials is pointless.
FATAL_CLOSE_CODES = frozenset({4001, 4002, 4004, 4010, 4011, 4012, 4013, 4014, 4914, 4915})
# Codes after which the stored session cannot be resumed.
IDENTIFY_REQUIRED_CLOSE_CODES = frozenset({4006, 4007, *range(4900, 4914)})
RESUME_ALLOWED_CLOSE_CODES = frozenset({4008, 4009})
