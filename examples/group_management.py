"""Group-management command-line example.

This script performs administrative calls only; it does not start a gateway.
It is intended for operators who already know the group and member OpenIDs.

Examples:
    python examples/group_management.py info GROUP_OPENID
    python examples/group_management.py members GROUP_OPENID
    python examples/group_management.py mute GROUP_OPENID MEMBER_OPENID 30
    python examples/group_management.py unmute GROUP_OPENID MEMBER_OPENID
    python examples/group_management.py kick GROUP_OPENID MEMBER_OPENID
    python examples/group_management.py blacklist GROUP_OPENID add MEMBER_OPENID
    python examples/group_management.py approve GROUP_OPENID MEMBER_OPENID JOIN_REQUEST_ID
    python examples/group_management.py reject GROUP_OPENID MEMBER_OPENID JOIN_REQUEST_ID
    python examples/group_management.py strategies
    python examples/group_management.py create-strategy GROUP_OPENID

Environment:
    QQBOT_APP_ID
    QQBOT_CLIENT_SECRET
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, timedelta

from RayBot import Bot, BotConfig


async def run(args: argparse.Namespace) -> None:
    config = BotConfig.from_env()
    if not config.app_id or not config.client_secret:
        raise SystemExit("QQBOT_APP_ID and QQBOT_CLIENT_SECRET must be set")

    bot = Bot(config)
    try:
        if args.command == "info":
            info = await bot.groups.get_info(args.group)
            print(
                f"name={info.group_name} members={info.group_member_num} "
                f"tags={','.join(info.group_tags)}"
            )

        elif args.command == "members":
            async for member in bot.groups.iter_members(args.group):
                print(
                    f"{member.member_openid}\t{member.member_role}\t"
                    f"{member.username}\tbot={member.bot}"
                )

        elif args.command == "mute":
            until = datetime.now(UTC) + timedelta(minutes=args.minutes)
            await bot.groups.mute_member(args.group, args.member, until)
            print(f"muted {args.member} until {until.isoformat(timespec='seconds')}")

        elif args.command == "unmute":
            await bot.groups.unmute_member(args.group, args.member)
            print(f"unmuted {args.member}")

        elif args.command == "kick":
            result = await bot.groups.batch_remove_members(
                args.group, [args.member], add_to_blacklist=args.blacklist
            )
            print(f"result={result.remove_members_result}")

        elif args.command == "blacklist":
            result = await bot.groups.update_blacklist(args.group, args.op, [args.member])
            print(f"failed={','.join(result.fail_openids) or 'none'}")

        elif args.command in {"approve", "reject"}:
            await bot.groups.approve_join_request(
                args.group,
                args.member,
                op="approve" if args.command == "approve" else "decline",
                join_request_id=args.join_request_id,
                add_to_blacklist=args.command == "reject" and args.blacklist,
            )
            print(f"{args.command} completed for {args.member}")

        elif args.command == "strategies":
            async for strategy in bot.groups.iter_strategies():
                print(
                    f"{strategy.strategy_id}\tenabled={strategy.is_enable}\t"
                    f"whitelist={strategy.whitelist_user_count}"
                )

        elif args.command == "create-strategy":
            state = await bot.groups.create_strategy(group_openids=[args.group])
            print(f"strategy_id={state.strategy_id} enabled={state.is_enable}")

    finally:
        await bot.aclose()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="QQ group management example")
    sub = parser.add_subparsers(dest="command", required=True)

    info = sub.add_parser("info")
    info.add_argument("group")

    members = sub.add_parser("members")
    members.add_argument("group")

    mute = sub.add_parser("mute")
    mute.add_argument("group")
    mute.add_argument("member")
    mute.add_argument("minutes", type=int)

    unmute = sub.add_parser("unmute")
    unmute.add_argument("group")
    unmute.add_argument("member")

    kick = sub.add_parser("kick")
    kick.add_argument("group")
    kick.add_argument("member")
    kick.add_argument("--blacklist", action="store_true")

    blacklist = sub.add_parser("blacklist")
    blacklist.add_argument("group")
    blacklist.add_argument("op", choices=["add", "del"])
    blacklist.add_argument("member")

    for name in ("approve", "reject"):
        request = sub.add_parser(name)
        request.add_argument("group")
        request.add_argument("member")
        request.add_argument("join_request_id")
        request.add_argument("--blacklist", action="store_true")

    sub.add_parser("strategies")

    create = sub.add_parser("create-strategy")
    create.add_argument("group")

    return parser


if __name__ == "__main__":
    asyncio.run(run(build_parser().parse_args()))
