"""RayBot - a modular, asyncio-native QQ bot toolkit.

The public facade re-exports the stable API, so application code can use::

    from RayBot import Bot, BotConfig, C2CMessage

Implementation modules live under :mod:`RayBot.core`; reach a specific module
when you need a narrow import::

    from RayBot.core.gateway import ShardManager
    from RayBot.core.config import GatewayConfig

This release supports the WebSocket transport only.
"""

from __future__ import annotations

from . import core
from .core import *  # noqa: F401,F403 - facade re-export
from .core import __all__ as _core_all

__all__ = [*_core_all, "core"]
__version__ = core.__version__
