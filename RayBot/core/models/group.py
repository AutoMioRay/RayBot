"""Group management response models."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .base import (
    Model,
    as_bool,
    as_int,
    as_sequence,
    as_str,
    parse_rfc3339,
)


@dataclass(slots=True, kw_only=True)
class GroupInfo(Model):
    """Basic information about a group."""

    group_openid: str = ""
    group_name: str = ""
    group_finger_memo: str = ""
    group_class_text: str = ""
    group_tags: tuple[str, ...] = ()
    group_member_num: int = 0

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> GroupInfo:
        tags = data.get("group_tags")
        return cls(
            group_openid=as_str(data.get("group_openid")),
            group_name=as_str(data.get("group_name")),
            group_finger_memo=as_str(data.get("group_finger_memo")),
            group_class_text=as_str(data.get("group_class_text")),
            group_tags=tuple(as_str(tag) for tag in tags)
            if isinstance(tags, Sequence) and not isinstance(tags, (str, bytes))
            else (),
            group_member_num=as_int(data.get("group_member_num")),
            raw=data,
        )


@dataclass(slots=True, kw_only=True)
class GroupBotState(Model):
    """The robot's own state inside a group."""

    member_openid: str = ""
    joined_at: datetime | None = None
    allow_proactive_msg: bool = False
    recv_msg_setting: str = ""
    member_role: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> GroupBotState:
        return cls(
            member_openid=as_str(data.get("member_openid")),
            joined_at=parse_rfc3339(data.get("joined_at")),
            allow_proactive_msg=as_bool(data.get("allow_proactive_msg")),
            recv_msg_setting=as_str(data.get("recv_msg_setting")),
            member_role=as_str(data.get("member_role")),
            raw=data,
        )


@dataclass(slots=True, kw_only=True)
class GroupMember(Model):
    """A member of a group."""

    member_openid: str = ""
    username: str = ""
    member_role: str = ""
    bot: bool = False
    joined_at: datetime | None = None
    union_openid: str = ""

    @property
    def is_admin(self) -> bool:
        return self.member_role in {"admin", "owner"}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> GroupMember:
        return cls(
            member_openid=as_str(data.get("member_openid")),
            username=as_str(data.get("username")),
            member_role=as_str(data.get("member_role")),
            bot=as_bool(data.get("bot")),
            joined_at=parse_rfc3339(data.get("joined_at")),
            union_openid=as_str(data.get("union_openid")),
            raw=data,
        )


@dataclass(slots=True, kw_only=True)
class GroupMemberPage(Model):
    """One page of group members."""

    members: tuple[GroupMember, ...] = ()
    next_cursor: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> GroupMemberPage:
        return cls(
            members=as_sequence(data.get("members"), GroupMember.from_dict),
            next_cursor=as_str(data.get("next_cursor")),
            raw=data,
        )


@dataclass(slots=True, kw_only=True)
class BlacklistUser(Model):
    """A user present in a group's blacklist."""

    union_openid: str = ""
    member_openid: str = ""
    username: str = ""
    banned_at: datetime | None = None
    bot: bool = False

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> BlacklistUser:
        return cls(
            union_openid=as_str(data.get("union_openid")),
            member_openid=as_str(data.get("member_openid")),
            username=as_str(data.get("username")),
            banned_at=parse_rfc3339(data.get("banned_at")),
            bot=as_bool(data.get("bot")),
            raw=data,
        )


@dataclass(slots=True, kw_only=True)
class BlacklistPage(Model):
    """One page of a group's blacklist."""

    users: tuple[BlacklistUser, ...] = ()
    next_cursor: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> BlacklistPage:
        return cls(
            users=as_sequence(data.get("users"), BlacklistUser.from_dict),
            next_cursor=as_str(data.get("next_cursor")),
            raw=data,
        )


@dataclass(slots=True, kw_only=True)
class MuteScheduleRule(Model):
    """A one-off group mute window."""

    task_id: str = ""
    start_at: datetime | None = None
    end_at: datetime | None = None
    enabled: bool = False

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> MuteScheduleRule:
        return cls(
            task_id=as_str(data.get("task_id")),
            start_at=parse_rfc3339(data.get("start_at")),
            end_at=parse_rfc3339(data.get("end_at")),
            enabled=as_bool(data.get("enabled")),
            raw=data,
        )


@dataclass(slots=True, kw_only=True)
class MuteRecurringRule(Model):
    """A weekly recurring group mute window."""

    task_id: str = ""
    weekdays: tuple[int, ...] = ()
    start_time: str = ""
    end_time: str = ""
    enabled: bool = False

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> MuteRecurringRule:
        weekdays = data.get("weekdays")
        return cls(
            task_id=as_str(data.get("task_id")),
            weekdays=tuple(as_int(day) for day in weekdays)
            if isinstance(weekdays, Sequence) and not isinstance(weekdays, (str, bytes))
            else (),
            start_time=as_str(data.get("start_time")),
            end_time=as_str(data.get("end_time")),
            enabled=as_bool(data.get("enabled")),
            raw=data,
        )


@dataclass(slots=True, kw_only=True)
class GlobalMuteRule(Model):
    """Group-wide mute configuration."""

    mode: str = "none"
    schedule_rules: tuple[MuteScheduleRule, ...] = ()
    recurring_rules: tuple[MuteRecurringRule, ...] = ()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> GlobalMuteRule:
        return cls(
            mode=as_str(data.get("mode"), "none"),
            schedule_rules=as_sequence(data.get("schedule_rules"), MuteScheduleRule.from_dict),
            recurring_rules=as_sequence(data.get("recurring_rules"), MuteRecurringRule.from_dict),
            raw=data,
        )


@dataclass(slots=True, kw_only=True)
class MemberMuteState(Model):
    """A currently muted group member."""

    member_openid: str = ""
    mute_expire_at: datetime | None = None
    username: str = ""
    union_openid: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> MemberMuteState:
        return cls(
            member_openid=as_str(data.get("member_openid")),
            mute_expire_at=parse_rfc3339(data.get("mute_expire_at")),
            username=as_str(data.get("username")),
            union_openid=as_str(data.get("union_openid")),
            raw=data,
        )


@dataclass(slots=True, kw_only=True)
class GroupMuteState(Model):
    """All mute information for a group."""

    global_rule: GlobalMuteRule = field(default_factory=GlobalMuteRule)
    members: tuple[MemberMuteState, ...] = ()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> GroupMuteState:
        rule_raw = data.get("global_rule")
        return cls(
            global_rule=GlobalMuteRule.from_dict(rule_raw)
            if isinstance(rule_raw, Mapping)
            else GlobalMuteRule(),
            members=as_sequence(data.get("members"), MemberMuteState.from_dict),
            raw=data,
        )


@dataclass(slots=True, kw_only=True)
class ReviewQA(Model):
    """One admin-defined question and the applicant's answer."""

    question: str = ""
    answer: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ReviewQA:
        return cls(
            question=as_str(data.get("question")),
            answer=as_str(data.get("answer")),
            raw=data,
        )


@dataclass(slots=True, kw_only=True)
class JoinVerifyInfo(Model):
    """How an applicant was asked to verify the join request."""

    method: str = ""
    verify_message: str = ""
    review_qa_list: tuple[ReviewQA, ...] = ()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> JoinVerifyInfo:
        return cls(
            method=as_str(data.get("method")),
            verify_message=as_str(data.get("verify_message")),
            review_qa_list=as_sequence(data.get("review_qa_list"), ReviewQA.from_dict),
            raw=data,
        )


@dataclass(slots=True, kw_only=True)
class AutoApproved(Model):
    """Present when a join request was approved by a strategy."""

    strategy_id: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AutoApproved:
        return cls(strategy_id=as_str(data.get("strategy_id")), raw=data)


@dataclass(slots=True, kw_only=True)
class JoinRequest(Model):
    """A pending (or automatically approved) request to join a group."""

    join_request_id: str = ""
    risk_tips: str = ""
    union_openid: str = ""
    member_openid: str = ""
    username: str = ""
    apply_at: datetime | None = None
    apply_source: str = ""
    invited_by: str = ""
    bot: bool = False
    verify_info: JoinVerifyInfo | None = None
    auto_approved: AutoApproved | None = None
    group_openid: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> JoinRequest:
        verify_raw = data.get("verify_info")
        auto_raw = data.get("auto_approved")
        return cls(
            join_request_id=as_str(data.get("join_request_id")),
            risk_tips=as_str(data.get("risk_tips")),
            union_openid=as_str(data.get("union_openid")),
            member_openid=as_str(data.get("member_openid")),
            username=as_str(data.get("username")),
            apply_at=parse_rfc3339(data.get("apply_at")),
            apply_source=as_str(data.get("apply_source")),
            invited_by=as_str(data.get("invited_by")),
            bot=as_bool(data.get("bot")),
            verify_info=JoinVerifyInfo.from_dict(verify_raw)
            if isinstance(verify_raw, Mapping)
            else None,
            auto_approved=AutoApproved.from_dict(auto_raw)
            if isinstance(auto_raw, Mapping)
            else None,
            group_openid=as_str(data.get("group_openid")),
            raw=data,
        )


@dataclass(slots=True, kw_only=True)
class JoinRequestPage(Model):
    """One page of join requests."""

    list: tuple[JoinRequest, ...] = ()
    next_cursor: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> JoinRequestPage:
        return cls(
            list=as_sequence(data.get("list"), JoinRequest.from_dict),
            next_cursor=as_str(data.get("next_cursor")),
            raw=data,
        )


@dataclass(slots=True, kw_only=True)
class JoinApprovalStrategy(Model):
    """An auto-approval strategy for join requests."""

    strategy_id: str = ""
    group_openids: tuple[str, ...] = ()
    group_ids: tuple[str, ...] = ()
    whitelist_user_count: int = 0
    is_enable: str = ""
    expire_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    remark: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> JoinApprovalStrategy:
        group_openids = data.get("group_openids")
        group_ids = data.get("group_ids")
        return cls(
            strategy_id=as_str(data.get("strategy_id")),
            group_openids=tuple(as_str(item) for item in group_openids)
            if isinstance(group_openids, Sequence) and not isinstance(group_openids, (str, bytes))
            else (),
            group_ids=tuple(as_str(item) for item in group_ids)
            if isinstance(group_ids, Sequence) and not isinstance(group_ids, (str, bytes))
            else (),
            whitelist_user_count=as_int(data.get("whitelist_user_count")),
            is_enable=as_str(data.get("is_enable")),
            expire_at=parse_rfc3339(data.get("expire_at")),
            created_at=parse_rfc3339(data.get("created_at")),
            updated_at=parse_rfc3339(data.get("updated_at")),
            remark=as_str(data.get("remark")),
            raw=data,
        )


@dataclass(slots=True, kw_only=True)
class StrategyPage(Model):
    """One page of auto-approval strategies."""

    strategies: tuple[JoinApprovalStrategy, ...] = ()
    next_cursor: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> StrategyPage:
        return cls(
            strategies=as_sequence(data.get("strategies"), JoinApprovalStrategy.from_dict),
            next_cursor=as_str(data.get("next_cursor")),
            raw=data,
        )


@dataclass(slots=True, kw_only=True)
class StrategyState(Model):
    """State returned after creating or updating a strategy."""

    strategy_id: str = ""
    is_enable: str = ""
    expire_at: datetime | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> StrategyState:
        return cls(
            strategy_id=as_str(data.get("strategy_id")),
            is_enable=as_str(data.get("is_enable")),
            expire_at=parse_rfc3339(data.get("expire_at")),
            raw=data,
        )


@dataclass(slots=True, kw_only=True)
class WhitelistUpdateResult(Model):
    """Result of adding or removing whitelist numbers."""

    strategy_id: str = ""
    whitelist_user_count: int = 0
    updated_at: datetime | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> WhitelistUpdateResult:
        return cls(
            strategy_id=as_str(data.get("strategy_id")),
            whitelist_user_count=as_int(data.get("whitelist_user_count")),
            updated_at=parse_rfc3339(data.get("updated_at")),
            raw=data,
        )


@dataclass(slots=True, kw_only=True)
class BatchRemoveResult(Model):
    """Result of removing multiple group members."""

    remove_members_result: str = ""
    add_to_member_blacklist_fail_openids: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> BatchRemoveResult:
        failed = data.get("add_to_member_blacklist_fail_openids")
        return cls(
            remove_members_result=as_str(data.get("remove_members_result")),
            add_to_member_blacklist_fail_openids=tuple(as_str(item) for item in failed)
            if isinstance(failed, Sequence) and not isinstance(failed, (str, bytes))
            else (),
            raw=data,
        )


@dataclass(slots=True, kw_only=True)
class BlacklistUpdateResult(Model):
    """Result of adding or removing blacklist entries."""

    fail_openids: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> BlacklistUpdateResult:
        failed = data.get("fail_openids")
        return cls(
            fail_openids=tuple(as_str(item) for item in failed)
            if isinstance(failed, Sequence) and not isinstance(failed, (str, bytes))
            else (),
            raw=data,
        )


__all__ = [
    "AutoApproved",
    "BatchRemoveResult",
    "BlacklistPage",
    "BlacklistUpdateResult",
    "BlacklistUser",
    "GlobalMuteRule",
    "GroupBotState",
    "GroupInfo",
    "GroupMember",
    "GroupMemberPage",
    "GroupMuteState",
    "JoinApprovalStrategy",
    "JoinRequest",
    "JoinRequestPage",
    "JoinVerifyInfo",
    "MemberMuteState",
    "MuteRecurringRule",
    "MuteScheduleRule",
    "ReviewQA",
    "StrategyPage",
    "StrategyState",
    "WhitelistUpdateResult",
]
