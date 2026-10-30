"""Webhook bot showing signature validation, join approval and welcome messages.

QQ requires the callback address to be HTTPS and to use port 80, 443, 8080 or
8443.  Configure the same URL in the QQ Open Platform console and keep
``QQBOT_CLIENT_SECRET`` identical to the console value: it is used both to
derive the Ed25519 key and to sign callback-url validation responses.

Environment:
    QQBOT_APP_ID
    QQBOT_CLIENT_SECRET
    QQBOT_WEBHOOK_PORT                  optional, default 8080
    QQBOT_WEBHOOK_ALLOWED_IPS           comma-separated inbound IP/CIDR allowlist
    QQBOT_WEBHOOK_TRUSTED_PROXIES       comma-separated trusted proxy IP/CIDR
    QQBOT_WEBHOOK_TRUST_FORWARDED_FOR   "1" to trust X-Forwarded-For from proxies
    QQBOT_WEBHOOK_VALIDATION            "1" to accept op=13; set "0" after setup
    QQBOT_WEBHOOK_REQUIRE_TLS           "1" to require a local ssl_context
    QQBOT_WEBHOOK_RATE_LIMIT            requests/second per source IP, default 100
    QQBOT_WEBHOOK_RATE_BURST            burst size, default 200
    QQBOT_WEBHOOK_MAX_SKEW              timestamp tolerance seconds, default 300
    QQBOT_JOIN_KEYWORD                  optional, auto-approve join requests whose
                                        verification message contains this keyword
"""

from __future__ import annotations

import logging
import os

from qqbot_toolkit import (
    Bot,
    BotConfig,
    FriendAdd,
    GroupAddRobot,
    GroupJoinRequest,
    InteractionEvent,
)
from qqbot_toolkit.config import WebhookConfig

LOG = logging.getLogger(__name__)


def _csv_env(name: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in os.getenv(name, "").split(",") if item.strip())


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def build_bot() -> Bot:
    config = BotConfig.from_env()
    if not config.app_id or not config.client_secret:
        raise SystemExit("QQBOT_APP_ID and QQBOT_CLIENT_SECRET must be set")

    port = int(os.getenv("QQBOT_WEBHOOK_PORT", "8080"))
    allowed_ips = _csv_env("QQBOT_WEBHOOK_ALLOWED_IPS")
    trusted_proxies = _csv_env("QQBOT_WEBHOOK_TRUSTED_PROXIES")
    trust_forwarded = _bool_env("QQBOT_WEBHOOK_TRUST_FORWARDED_FOR")
    if trust_forwarded and not trusted_proxies:
        LOG.warning(
            "QQBOT_WEBHOOK_TRUST_FORWARDED_FOR is set but "
            "QQBOT_WEBHOOK_TRUSTED_PROXIES is empty; X-Forwarded-For is ignored"
        )
        trust_forwarded = False
    if not allowed_ips:
        LOG.warning("QQBOT_WEBHOOK_ALLOWED_IPS is empty; any source can reach the callback")

    config = config.with_overrides(
        webhook=WebhookConfig(
            host=os.getenv("QQBOT_WEBHOOK_HOST", "0.0.0.0"),
            port=port,
            path=os.getenv("QQBOT_WEBHOOK_PATH", "/qqbot"),
            allowed_ips=allowed_ips,
            trusted_proxies=trusted_proxies,
            trust_forwarded_for=trust_forwarded,
            validation_enabled=_bool_env("QQBOT_WEBHOOK_VALIDATION", True),
            max_timestamp_skew=float(os.getenv("QQBOT_WEBHOOK_MAX_SKEW", "300")),
            rate_limit_per_second=float(os.getenv("QQBOT_WEBHOOK_RATE_LIMIT", "100")),
            rate_limit_burst=int(os.getenv("QQBOT_WEBHOOK_RATE_BURST", "200")),
            require_tls=_bool_env("QQBOT_WEBHOOK_REQUIRE_TLS"),
        )
    )
    bot = Bot(config)
    keyword = os.getenv("QQBOT_JOIN_KEYWORD", "")

    @bot.on_group_add_robot()
    async def welcome_group(event: GroupAddRobot) -> None:
        kwargs = {"event_id": event.event_id} if event.event_id else {}
        await bot.group.send(
            event.group_openid,
            content="Robot joined. Send /help to see available commands.",
            **kwargs,
        )

    @bot.on_friend_add()
    async def welcome_friend(event: FriendAdd) -> None:
        kwargs = {"event_id": event.event_id} if event.event_id else {}
        await bot.c2c.send(
            event.openid,
            content="Thanks for adding me. Send /help to start.",
            **kwargs,
        )

    @bot.on_group_join_request()
    async def review_join(event: GroupJoinRequest) -> None:
        if not keyword:
            LOG.info(
                "join request from %s (%s), approval keyword not configured",
                event.username,
                event.member_openid,
            )
            return
        if keyword in event.verify_message:
            await bot.groups.approve_join_request(
                event.group_openid,
                event.member_openid,
                op="approve",
                join_request_id=event.join_request_id,
            )
        else:
            await bot.groups.approve_join_request(
                event.group_openid,
                event.member_openid,
                op="decline",
                join_request_id=event.join_request_id,
                reject_reason="Verification message does not contain the required keyword",
            )

    @bot.on_interaction()
    async def acknowledge(event: InteractionEvent) -> None:
        await bot.acknowledge_interaction(event)

    return bot


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    build_bot().run(webhook=True)
