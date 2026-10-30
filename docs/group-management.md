# 群聊管理方案

## 前置条件

1. **管理员身份**：禁言、踢人、黑名单、入群审批、自动审批策略等写操作要求机器人是群管理员。
2. **事件订阅**：
   - 入群申请、成员加入/退出需要 `GROUP_MEMBER_EVENT (1 << 24)`；
   - 机器人入群/退群、群消息开关、群消息需要 `GROUP_AND_C2C_EVENT (1 << 25)`。
3. **接口权限**：成员列表、单个成员、批量移除、黑名单等接口当前文档标注为内邀能力。无权限时平台返回 `err_code=11253`，`APIError.is_auth_error` 为 `True`。
4. **群 OpenID**：所有群管理接口都使用 `group_openid`，不是 QQ 群号。

默认配置已经订阅 `GROUP_MEMBER_EVENT` 与 `GROUP_AND_C2C_EVENT`。

## 能力矩阵

| 能力 | 方法 | 单次限制 | 频率（文档） | 备注 |
|---|---|---|---|---|
| 群信息 | `get_info` | — | 30 QPM | 内邀接口权限 |
| 机器人群内状态 | `get_bot_state` | — | 30 QPM | 内邀接口权限 |
| 成员列表 | `iter_members` | 30/页 | 60 QPM | 内邀 |
| 单个成员 | `get_member` | — | 30 QPM | 内邀 |
| 批量移除 | `batch_remove_members` | 20 | 30 QPM | 内邀 |
| 黑名单查询 | `iter_blacklist` | 100/页 | 30 QPM | 内邀 |
| 黑名单增删 | `update_blacklist` | 20 | 60 QPM | 仅非群成员可加入 |
| 禁言查询 | `get_mute_state` | — | 30 QPM | 管理员 |
| 成员禁言 | `set_member_mutes` | 20 | 60 QPM | 最长 30 天 |
| 入群申请列表 | `iter_join_requests` | 50/页 | 30 QPM | 管理员 |
| 入群审批 | `approve_join_request` | 1 | 60 QPM | 管理员 |
| 自动审批策略 | `create/update/delete/execute` | 20 个策略 | 60 QPM | 管理员 |
| 白名单号码 | `update_strategy_whitelist` | 10000/次，上限 10 万 | 60 QPM | 号码用字符串避免精度问题 |

群级全员禁言的**写入**接口不在当前文档范围内；`get_mute_state` 返回的 `global_rule` 只读。

## 推荐架构

```text
                    ┌─────────────────────┐
GROUP_JOIN_REQUEST ─► 审批编排器           ├─► approve/decline
                    │ 风险检查/关键词/白名单 │
                    └─────────┬───────────┘
                              │ 审计写入（业务自建）
                              ▼
                       审计日志 / 数据库

定时任务 ─► iter_join_requests ─► 补偿遗漏事件
        └► execute_strategy   ─► 白名单全量扫描

管理命令 ─► 权限校验（bot_state.member_role）
        ├─► mute / unmute
        ├─► kick / batch_remove
        └─► blacklist add/del
```

组件库负责协议与调用，业务侧需要负责：

- **审计日志**：记录操作者、目标成员、原因、时间、结果、`trace_id`；
- **持久化**：群配置、白名单、黑名单同步状态、审批记录；
- **幂等**：以 `join_request_id` 作为唯一键，避免重复审批；
- **补偿**：事件可能丢失或机器人重启，定时拉取申请列表兜底；
- **权限缓存**：`get_bot_state` 结果缓存数分钟，减少 QPM 消耗。

## 入群审批

### 事件驱动

```python
from qqbot_toolkit import Bot, BotConfig, GroupJoinRequest

bot = Bot(BotConfig.from_env())
KEYWORD = "申请理由"

@bot.on_group_join_request()
async def review(event: GroupJoinRequest) -> None:
    # risk_tips 非空表示平台给出风险提示，建议人工复核
    if event.risk_tips:
        await bot.groups.approve_join_request(
            event.group_openid,
            event.member_openid,
            op="decline",
            join_request_id=event.join_request_id,
            reject_reason="需要人工复核",
        )
        return

    if KEYWORD in event.verify_message:
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
            reject_reason="验证消息不符合要求",
            add_to_blacklist=False,
        )
```

### 补偿扫描

```python
async def reconcile(group_openid: str) -> None:
    async for request in bot.groups.iter_join_requests(group_openid, limit=50):
        if should_approve(request):
            await bot.groups.approve_join(group_openid, request)
```

`approve_join` / `reject_join` 直接接受 `JoinRequest` 模型，自动带上 `join_request_id`。

## 自动审批策略

自动审批策略维护白名单号码，命中白名单的申请会被平台自动通过（机器人需为管理员）。

```python
state = await bot.groups.create_strategy(
    group_openids=["GROUP_OPENID"],
    is_enable="on",
    remark="白名单自动通过",
)

await bot.groups.update_strategy_whitelist(
    state.strategy_id,
    op="add",
    whitelist_users=["123456789", "987654321"],
)

# 对关联的全部群做一次全量扫描，异步执行，约 10 分钟
await bot.groups.execute_strategy(state.strategy_id)
```

实测：对 `is_enable="off"` 的策略调用 `execute_strategy` 会返回平台 `50105002`；执行前先启用策略。策略执行是异步任务，返回成功不代表扫描立即完成。

修改关联群：

```python
await bot.groups.update_strategy(
    state.strategy_id,
    group_action={"op": "add", "group_openids": ["ANOTHER_GROUP"]},
)
```

停用：

```python
await bot.groups.update_strategy(state.strategy_id, is_enable="off")
```

## 禁言

```python
from datetime import UTC, datetime, timedelta

until = datetime.now(UTC) + timedelta(minutes=30)
await bot.groups.mute_member(group_openid, member_openid, until)

await bot.groups.unmute_member(group_openid, member_openid)
```

批量操作：

```python
from qqbot_toolkit.models.outbound import MemberMuteChange

await bot.groups.set_member_mutes(group_openid, [
    MemberMuteChange(op="add", member_openid="M1", mute_expire_at=until),
    MemberMuteChange(op="update", member_openid="M2", mute_expire_at=until),
    MemberMuteChange(op="del", member_openid="M3", mute_expire_at=""),
])
```

约束：

- 单次最多 20 项；
- 最长 30 天；
- 不能操作群主、管理员或机器人；
- 机器人必须是管理员。

## 踢人与黑名单

```python
await bot.groups.batch_remove_members(
    group_openid,
    ["MEMBER_1", "MEMBER_2"],
    add_to_blacklist=True,
)

await bot.groups.update_blacklist(group_openid, "add", ["MEMBER_3"])
await bot.groups.update_blacklist(group_openid, "del", ["MEMBER_3"])
```

注意：

- 单次最多 20 个；
- 目标用户仍在群中时不能加入黑名单，应先移除；
- 批量移除返回 `add_to_member_blacklist_fail_openids`，黑名单增删返回 `fail_openids`，业务应记录失败项。

## 权限校验与降级

```python
from qqbot_toolkit.errors import APIError

async def ensure_admin(group_openid: str) -> bool:
    state = await bot.groups.get_bot_state(group_openid)
    return state.member_role in {"admin", "owner"}

try:
    await bot.groups.mute_member(group_openid, member_openid, until)
except APIError as exc:
    if exc.err_code == 11253:
        # 无接口权限（内邀能力）
        ...
    elif exc.is_rate_limited:
        ...
    raise
```

`APIError` 提供的判断：`is_rate_limited`、`is_auth_error`、`is_retryable`。不要依据 `message` 文本判断。

## 高频调用的优化

1. **缓存元数据**：`get_info` / `get_bot_state` 结果缓存 1~5 分钟。
2. **分页拉取**：成员列表每页 30、入群申请每页最多 50、黑名单每页最多 100；避免无界并发。
3. **批量接口**：禁言、黑名单、移除都支持 20 个/次，优先合并调用。
4. **限流**：库内已按文档配置路由桶；业务层不需要再叠加固定 sleep。
5. **审计异步化**：审批/禁言成功后，审计写入放到独立队列，避免阻塞处理器。

## 常见错误码

| 错误码 | 含义 | 处理 |
|---|---|---|
| `11253` / `40012010` | 应用无接口访问权限 | 该接口为内邀能力，申请权限；成员列表、成员详情、黑名单常见此错误 |
| `11282` | 非管理员 | 提示用户授予管理员 |
| `11265` | 机器人已被封禁 | 停止调用并人工处理 |
| `40034101` / `40054003` | 机器人非群成员 | 重新邀请入群 |
| `40011030` | 机器人不是群管理员 | 授予管理员权限后重试 |
| `40054002` | 机器人被禁言 | 等待解禁 |
| `40034100` | 主动消息频控 | 降低频率或改用被动回复 |
