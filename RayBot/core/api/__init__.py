"""OpenAPI groups."""

from .base import BaseAPI
from .gateway import GatewayAPI
from .groups import GroupsAPI
from .interactions import InteractionsAPI
from .media import FileHashes, MediaAPI, MediaTarget, hash_bytes, hash_file
from .messages import (
    C2CAPI,
    C2CStreamSession,
    GroupAPI,
    command_enter,
    command_input,
    mention,
    reply_target,
)
from .robot import BotAPI

__all__ = [
    "BaseAPI",
    "BotAPI",
    "C2CAPI",
    "C2CStreamSession",
    "FileHashes",
    "GatewayAPI",
    "GroupAPI",
    "GroupsAPI",
    "InteractionsAPI",
    "MediaAPI",
    "MediaTarget",
    "hash_bytes",
    "command_enter",
    "command_input",
    "hash_file",
    "mention",
    "reply_target",
]
