"""Read-only live smoke test for a real bot account.

This script never sends messages to users or groups.  It validates:
    * access-token acquisition;
    * ``GET /users/@me``;
    * gateway discovery;
    * global menu and command-panel listing;
    * optionally, a real WebSocket Identify and READY.

Usage:
    QQBOT_APP_ID=... QQBOT_CLIENT_SECRET=... \\
        python examples/smoke_test.py --gateway

The credentials are read from the environment and are never printed.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace

from qqbot_toolkit import Bot, BotConfig, ReadyEvent
from qqbot_toolkit.errors import APIError


async def run(*, gateway: bool) -> None:
    config = BotConfig.from_env()
    if not config.app_id or not config.client_secret:
        raise SystemExit("QQBOT_APP_ID and QQBOT_CLIENT_SECRET must be set")

    config = config.with_overrides(
        http=replace(
            config.http,
            timeout=20.0,
            max_retries=0,
            enforce_rate_limits=False,
            enforce_relation_limits=False,
        ),
        gateway=replace(
            config.gateway,
            open_timeout=15.0,
            reconnect_max_attempts=3,
        ),
    )
    bot = Bot(config)
    try:
        token = await bot.tokens.get_token()
        print(f"token: ok (length={len(token)})")

        me = await bot.bot.get_me()
        print(f"profile: id={me.id} username={me.username} bot={me.bot}")

        info = await bot.gateway_api.get()
        print(
            "gateway: "
            f"url={info.url} shards={info.shards} "
            f"max_concurrency={info.session_start_limit.max_concurrency}"
        )

        menu = await bot.bot.get_global_menu()
        items = len(menu.menu.items) if menu.menu else 0
        print(f"menu: version={menu.version} items={items}")

        for scope in ("c2c", "group", "channel", "dm"):
            page = await bot.bot.list_panels(scope=scope)
            print(f"panels[{scope}]: records={len(page.records)} is_end={page.is_end}")

        images = await bot.media.list_images()
        print(f"media images: total={images.total}")

        if gateway:
            ready = asyncio.Event()

            @bot.on("READY")
            async def on_ready(event: ReadyEvent) -> None:
                print(
                    f"websocket: READY session={event.session_id} "
                    f"user={event.user.username} shard={event.shard}"
                )
                ready.set()

            await bot.start()
            await asyncio.wait_for(ready.wait(), timeout=25)
    except APIError as exc:
        print(f"api error: err_code={exc.err_code} status={exc.status} trace_id={exc.trace_id}")
        raise
    finally:
        await bot.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description="qqbot-toolkit live smoke test")
    parser.add_argument(
        "--gateway",
        action="store_true",
        help="also open a WebSocket and wait for READY",
    )
    args = parser.parse_args()
    asyncio.run(run(gateway=args.gateway))


if __name__ == "__main__":
    main()
