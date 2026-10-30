"""WebSocket echo bot.

Run with environment variables:
    QQBOT_APP_ID=...
    QQBOT_CLIENT_SECRET=...

The default intents cover C2C, group messages, group membership and
interactions.  The robot replies to every direct message and every group
message that mentions it.
"""

from __future__ import annotations

import logging

from RayBot import Bot, BotConfig, C2CMessage, GroupMessage, InteractionEvent


def build_bot() -> Bot:
    config = BotConfig.from_env()
    if not config.app_id or not config.client_secret:
        raise SystemExit("QQBOT_APP_ID and QQBOT_CLIENT_SECRET must be set")

    bot = Bot(config)

    @bot.on_c2c_message()
    async def echo_c2c(event: C2CMessage) -> None:
        await bot.reply(event, f"Echo: {event.content}")

    @bot.on_group_at_message()
    async def echo_group(event: GroupMessage) -> None:
        await bot.reply(event, f"Echo: {event.content}")

    @bot.on_interaction()
    async def handle_interaction(event: InteractionEvent) -> None:
        # Button clicks must be acknowledged quickly or the client keeps
        # showing a loading state.
        await bot.acknowledge_interaction(event)
        if event.button_data:
            await bot.reply(event, f"Button payload: {event.button_data}")

    @bot.on_error
    async def handle_error(event, handler, exc) -> None:
        logging.getLogger(__name__).exception(
            "handler %s failed for %s",
            getattr(handler, "__name__", handler),
            type(event).__name__,
            exc_info=(type(exc), exc, exc.__traceback__),
        )

    return bot


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    build_bot().run()
