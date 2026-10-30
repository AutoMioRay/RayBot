"""Group management endpoints."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import datetime
from typing import Any

from ..models.base import format_rfc3339
from ..models.group import (
    BatchRemoveResult,
    BlacklistPage,
    BlacklistUpdateResult,
    BlacklistUser,
    GroupBotState,
    GroupInfo,
    GroupMember,
    GroupMemberPage,
    GroupMuteState,
    JoinApprovalStrategy,
    JoinRequest,
    JoinRequestPage,
    StrategyPage,
    StrategyState,
    WhitelistUpdateResult,
)
from ..models.outbound import MemberMuteChange
from .base import BaseAPI, segment


class GroupsAPI(BaseAPI):
    """Group information, members, moderation and join-approval endpoints.

    Most write operations require the robot to be a group administrator.  The
    platform also marks several member-listing endpoints as invitation-only;
    those calls surface the platform ``err_code`` (usually ``11253``) through
    :class:`~qqbot_toolkit.errors.APIError`.
    """

    async def get_info(self, group_openid: str) -> GroupInfo:
        """Get the group's name, description, tags and member count."""

        data = await self._client.get(
            f"/v2/groups/{segment(group_openid)}/info",
            route="group.info",
        )
        return GroupInfo.from_dict(data or {})

    async def get_bot_state(self, group_openid: str) -> GroupBotState:
        """Get the robot's role, join time and message-receiving settings."""

        data = await self._client.get(
            f"/v2/groups/{segment(group_openid)}/bot_state",
            route="group.bot_state",
        )
        return GroupBotState.from_dict(data or {})

    async def get_members(self, group_openid: str, *, cursor: str = "") -> GroupMemberPage:
        """Get one page of group members (at most 30 per page)."""

        data = await self._client.get(
            f"/v2/groups/{segment(group_openid)}/members",
            params={"cursor": cursor},
            route="group.member.list",
        )
        return GroupMemberPage.from_dict(data or {})

    async def iter_members(
        self, group_openid: str, *, max_pages: int | None = None
    ) -> AsyncIterator[GroupMember]:
        """Yield every group member across all pages."""

        cursor = ""
        seen: set[str] = set()
        pages = 0
        while True:
            page = await self.get_members(group_openid, cursor=cursor)
            for member in page.members:
                yield member
            pages += 1
            if not page.next_cursor or page.next_cursor in seen:
                return
            if max_pages is not None and pages >= max_pages:
                return
            seen.add(page.next_cursor)
            cursor = page.next_cursor

    async def get_member(self, group_openid: str, member_openid: str) -> GroupMember:
        """Get one group member's profile."""

        data = await self._client.get(
            f"/v2/groups/{segment(group_openid)}/members/{segment(member_openid)}",
            route="group.member.get",
        )
        return GroupMember.from_dict(data or {})

    async def batch_remove_members(
        self,
        group_openid: str,
        member_openids: Sequence[str],
        *,
        add_to_blacklist: bool = False,
    ) -> BatchRemoveResult:
        """Remove up to 20 members, optionally adding them to the blacklist."""

        if not member_openids:
            raise ValueError("member_openids cannot be empty")
        if len(member_openids) > 20:
            raise ValueError("at most 20 members can be removed per request")
        data = await self._client.post(
            f"/v2/groups/{segment(group_openid)}/batch_remove_members",
            json={
                "member_openids": list(member_openids),
                "add_to_member_blacklist": add_to_blacklist,
            },
            route="group.member.batch_remove",
        )
        return BatchRemoveResult.from_dict(data or {})

    async def get_blacklist(
        self, group_openid: str, *, cursor: str = "", limit: int | None = None
    ) -> BlacklistPage:
        """Get one page of the group blacklist."""

        data = await self._client.get(
            f"/v2/groups/{segment(group_openid)}/member_blacklist",
            params={"cursor": cursor, "limit": limit},
            route="group.blacklist.get",
        )
        return BlacklistPage.from_dict(data or {})

    async def iter_blacklist(
        self, group_openid: str, *, limit: int = 100, max_pages: int | None = None
    ) -> AsyncIterator[BlacklistUser]:
        """Yield every blacklisted user across all pages."""

        cursor = ""
        seen: set[str] = set()
        pages = 0
        while True:
            page = await self.get_blacklist(group_openid, cursor=cursor, limit=limit)
            for user in page.users:
                yield user
            pages += 1
            if not page.next_cursor or page.next_cursor in seen:
                return
            if max_pages is not None and pages >= max_pages:
                return
            seen.add(page.next_cursor)
            cursor = page.next_cursor

    async def update_blacklist(
        self, group_openid: str, op: str, member_openids: Sequence[str]
    ) -> BlacklistUpdateResult:
        """Add or remove up to 20 users from the blacklist.

        A user who is still in the group cannot be added to the blacklist.
        """

        if op not in {"add", "del"}:
            raise ValueError("op must be 'add' or 'del'")
        if not member_openids:
            raise ValueError("member_openids cannot be empty")
        if len(member_openids) > 20:
            raise ValueError("at most 20 members can be changed per request")
        data = await self._client.post(
            f"/v2/groups/{segment(group_openid)}/member_blacklist",
            json={"op": op, "member_openids": list(member_openids)},
            route="group.blacklist.set",
        )
        return BlacklistUpdateResult.from_dict(data or {})

    async def get_mute_state(self, group_openid: str) -> GroupMuteState:
        """Get the group-wide mute rule and currently muted members."""

        data = await self._client.get(
            f"/v2/groups/{segment(group_openid)}/restrict_chat_setting",
            route="group.mute.get",
        )
        return GroupMuteState.from_dict(data or {})

    async def set_member_mutes(
        self, group_openid: str, changes: Sequence[MemberMuteChange | Mapping[str, Any]]
    ) -> None:
        """Apply up to 20 add/update/delete mute operations in one call."""

        if not changes:
            raise ValueError("changes cannot be empty")
        if len(changes) > 20:
            raise ValueError("at most 20 mute changes are allowed per request")
        members: list[dict[str, Any]] = []
        for change in changes:
            if isinstance(change, Mapping):
                entry = dict(change)
            else:
                entry = change.to_dict()
            op = entry.get("op")
            if op not in {"add", "update", "del"}:
                raise ValueError("mute op must be 'add', 'update' or 'del'")
            expire = entry.get("mute_expire_at")
            if op in {"add", "update"} and not expire:
                raise ValueError("mute_expire_at is required for add/update")
            if expire is not None:
                entry["mute_expire_at"] = format_rfc3339(expire)
            members.append(entry)
        await self._client.post(
            f"/v2/groups/{segment(group_openid)}/restrict_chat_setting",
            json={"members": members},
            route="group.mute.set",
        )

    async def mute_member(
        self,
        group_openid: str,
        member_openid: str,
        until: datetime | int | float | str,
        *,
        op: str = "add",
    ) -> None:
        """Mute one member until ``until`` (maximum 30 days)."""

        await self.set_member_mutes(
            group_openid,
            [MemberMuteChange(op=op, member_openid=member_openid, mute_expire_at=until)],
        )

    async def unmute_member(self, group_openid: str, member_openid: str) -> None:
        """Remove a member's mute immediately."""

        await self.set_member_mutes(
            group_openid,
            [MemberMuteChange(op="del", member_openid=member_openid, mute_expire_at="")],
        )

    async def get_join_requests(
        self, group_openid: str, *, cursor: str = "", limit: int | None = None
    ) -> JoinRequestPage:
        """Get one page of pending join requests.

        The robot must be a group administrator to receive join events and call
        this endpoint.
        """

        data = await self._client.get(
            f"/v2/groups/{segment(group_openid)}/join_request_list",
            params={"cursor": cursor, "limit": limit},
            route="group.join.list",
        )
        return JoinRequestPage.from_dict(data or {})

    async def iter_join_requests(
        self, group_openid: str, *, limit: int = 50, max_pages: int | None = None
    ) -> AsyncIterator[JoinRequest]:
        """Yield every pending join request across all pages."""

        cursor = ""
        seen: set[str] = set()
        pages = 0
        while True:
            page = await self.get_join_requests(group_openid, cursor=cursor, limit=limit)
            for request in page.list:
                yield request
            pages += 1
            if not page.next_cursor or page.next_cursor in seen:
                return
            if max_pages is not None and pages >= max_pages:
                return
            seen.add(page.next_cursor)
            cursor = page.next_cursor

    async def approve_join_request(
        self,
        group_openid: str,
        member_openid: str,
        *,
        op: str = "approve",
        join_request_id: str | None = None,
        reject_reason: str | None = None,
        add_to_blacklist: bool = False,
    ) -> None:
        """Approve or decline one join request.

        Args:
            group_openid: Group OpenID.
            member_openid: Applicant's member OpenID.
            op: ``approve`` or ``decline``.
            join_request_id: Request ID from the event or request list.
            reject_reason: Reason shown when declining.
            add_to_blacklist: Also blacklist the applicant when declining.
        """

        if op not in {"approve", "decline"}:
            raise ValueError("op must be 'approve' or 'decline'")
        body: dict[str, Any] = {"op": op}
        if join_request_id is not None:
            body["join_request_id"] = join_request_id
        if reject_reason is not None:
            body["reject_reason"] = reject_reason
        if add_to_blacklist:
            body["add_to_member_blacklist"] = True
        await self._client.post(
            f"/v2/groups/{segment(group_openid)}/approval_join_request/{segment(member_openid)}",
            json=body,
            route="group.join.approve",
        )

    async def approve_join(self, group_openid: str, request: JoinRequest) -> None:
        """Approve a join request model returned by the API or an event."""

        await self.approve_join_request(
            group_openid,
            request.member_openid,
            op="approve",
            join_request_id=request.join_request_id,
        )

    async def reject_join(
        self,
        group_openid: str,
        request: JoinRequest,
        *,
        reason: str | None = None,
        blacklist: bool = False,
    ) -> None:
        """Decline a join request, optionally blacklisting the applicant."""

        await self.approve_join_request(
            group_openid,
            request.member_openid,
            op="decline",
            join_request_id=request.join_request_id,
            reject_reason=reason,
            add_to_blacklist=blacklist,
        )

    async def list_strategies(self, *, cursor: str = "", limit: int | None = None) -> StrategyPage:
        """List active auto-approval strategies."""

        data = await self._client.get(
            "/v2/groups/join_approval_strategy",
            params={"cursor": cursor, "limit": limit},
            route="group.strategy.list",
        )
        return StrategyPage.from_dict(data or {})

    async def iter_strategies(
        self, *, limit: int = 50, max_pages: int | None = None
    ) -> AsyncIterator[JoinApprovalStrategy]:
        """Yield every auto-approval strategy across all pages."""

        cursor = ""
        seen: set[str] = set()
        pages = 0
        while True:
            page = await self.list_strategies(cursor=cursor, limit=limit)
            for strategy in page.strategies:
                yield strategy
            pages += 1
            if not page.next_cursor or page.next_cursor in seen:
                return
            if max_pages is not None and pages >= max_pages:
                return
            seen.add(page.next_cursor)
            cursor = page.next_cursor

    async def create_strategy(
        self,
        *,
        group_openids: Sequence[str] | None = None,
        group_ids: Sequence[int | str] | None = None,
        is_enable: str = "on",
        expire_at: datetime | int | float | str | None = None,
        remark: str | None = None,
    ) -> StrategyState:
        """Create a whitelist auto-approval strategy.

        Exactly one of ``group_openids`` and ``group_ids`` is required.  A robot
        may own at most 20 strategies.
        """

        if bool(group_openids) == bool(group_ids):
            raise ValueError("exactly one of group_openids or group_ids is required")
        body: dict[str, Any] = {"is_enable": is_enable}
        if group_openids:
            body["group_openids"] = list(group_openids)
        if group_ids:
            body["group_ids"] = list(group_ids)
        if expire_at is not None:
            body["expire_at"] = format_rfc3339(expire_at)
        if remark is not None:
            body["remark"] = remark
        data = await self._client.post(
            "/v2/groups/join_approval_strategy",
            json=body,
            route="group.strategy.write",
        )
        return StrategyState.from_dict(data or {})

    async def update_strategy(
        self,
        strategy_id: str,
        *,
        is_enable: str | None = None,
        expire_at: datetime | int | float | str | None = None,
        group_action: Mapping[str, Any] | None = None,
        remark: str | None = None,
    ) -> StrategyState:
        """Change a strategy's state, expiry, associated groups or remark."""

        body: dict[str, Any] = {}
        if is_enable is not None:
            if is_enable not in {"on", "off"}:
                raise ValueError("is_enable must be 'on' or 'off'")
            body["is_enable"] = is_enable
        if expire_at is not None:
            body["expire_at"] = format_rfc3339(expire_at)
        if group_action is not None:
            body["group_action"] = dict(group_action)
        if remark is not None:
            body["remark"] = remark
        if not body:
            raise ValueError("at least one field must be provided")
        data = await self._client.patch(
            f"/v2/groups/join_approval_strategy/{segment(strategy_id)}",
            json=body,
            route="group.strategy.write",
        )
        return StrategyState.from_dict(data or {})

    async def delete_strategy(self, strategy_id: str) -> None:
        """Delete an auto-approval strategy."""

        await self._client.delete(
            f"/v2/groups/join_approval_strategy/{segment(strategy_id)}",
            route="group.strategy.write",
        )

    async def execute_strategy(self, strategy_id: str) -> None:
        """Run a full scan of a strategy's groups.

        Execution is asynchronous and may take about ten minutes.
        """

        await self._client.post(
            f"/v2/groups/join_approval_strategy/{segment(strategy_id)}/execute",
            json={},
            route="group.strategy.execute",
        )

    async def update_strategy_whitelist(
        self,
        strategy_id: str,
        *,
        op: str,
        whitelist_users: Sequence[str],
    ) -> WhitelistUpdateResult:
        """Add or remove up to 10,000 whitelist QQ numbers."""

        if op not in {"add", "del"}:
            raise ValueError("op must be 'add' or 'del'")
        if not whitelist_users:
            raise ValueError("whitelist_users cannot be empty")
        if len(whitelist_users) > 10_000:
            raise ValueError("at most 10,000 whitelist users per request")
        data = await self._client.post(
            f"/v2/groups/join_approval_strategy/{segment(strategy_id)}/whitelist_users",
            json={"op": op, "whitelist_users": [str(user) for user in whitelist_users]},
            route="group.strategy.whitelist",
        )
        return WhitelistUpdateResult.from_dict(data or {})


__all__ = ["GroupsAPI"]
