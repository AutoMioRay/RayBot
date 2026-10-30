# 事件与处理器

## 事件映射

| 事件名 `t` | Intent | 模型 | Bot 装饰器 |
|---|---|---|---|
| `C2C_MESSAGE_CREATE` | `GROUP_AND_C2C_EVENT` | `C2CMessage` | `on_c2c_message` |
| `GROUP_AT_MESSAGE_CREATE` | `GROUP_AND_C2C_EVENT` | `GroupAtMessage` | `on_group_at_message` / `on_group_message` |
| `GROUP_MESSAGE_CREATE` | `GROUP_AND_C2C_EVENT` | `GroupAllMessage` | `on_group_message` |
| `GROUP_ADD_ROBOT` | `GROUP_AND_C2C_EVENT` | `GroupAddRobot` | `on_group_add_robot` |
| `GROUP_DEL_ROBOT` | `GROUP_AND_C2C_EVENT` | `GroupDelRobot` | `on_group_del_robot` |
| `GROUP_MSG_REJECT` | `GROUP_AND_C2C_EVENT` | `GroupMsgReject` | `on_group_msg_reject` |
| `GROUP_MSG_RECEIVE` | `GROUP_AND_C2C_EVENT` | `GroupMsgReceive` | `on_group_msg_receive` |
| `GROUP_MEMBER_ADD` | `GROUP_MEMBER_EVENT` | `GroupMemberAdd` | `on_group_member_add` |
| `GROUP_MEMBER_REMOVE` | `GROUP_MEMBER_EVENT` | `GroupMemberRemove` | `on_group_member_remove` |
| `GROUP_JOIN_REQUEST` | `GROUP_MEMBER_EVENT` | `GroupJoinRequest` | `on_group_join_request` |
| `C2C_MSG_REJECT` | `GROUP_AND_C2C_EVENT` | `C2CMsgReject` | `on_c2c_msg_reject` |
| `C2C_MSG_RECEIVE` | `GROUP_AND_C2C_EVENT` | `C2CMsgReceive` | `on_c2c_msg_receive` |
| `FRIEND_ADD` | `GROUP_AND_C2C_EVENT` | `FriendAdd` | `on_friend_add` |
| `FRIEND_DEL` | `GROUP_AND_C2C_EVENT` | `FriendDel` | `on_friend_del` |
| `INTERACTION_CREATE` | `INTERACTION` | `InteractionEvent` | `on_interaction` |
| `READY` | 连接生命周期 | `ReadyEvent` | `on("READY")` |
| `RESUMED` | 连接生命周期 | `ResumedEvent` | `on("RESUMED")` |
| 未建模事件 | — | `UnknownEvent` | `on_raw` |

`on_message` 同时订阅 `C2C_MESSAGE_CREATE`、`GROUP_AT_MESSAGE_CREATE`、`GROUP_MESSAGE_CREATE`。

## 消息事件

`C2CMessage`、`GroupAtMessage`、`GroupAllMessage` 共享 `ChatMessage` 字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | `str` | 消息 ID，用于被动回复和撤回 |
| `author` | `User` | 发送者；单聊取 `user_openid`，群聊取 `member_openid` |
| `content` | `str` | 文本内容；群 @ 消息已去掉 @机器人 前缀 |
| `timestamp` | `datetime \| None` | RFC3339 时间 |
| `message_type` | `int` | `0` 文本、`3` 卡片、`101/102` 合并消息、`103` 引用 |
| `message_scene` | `MessageScene \| None` | `msg_idx`、`ref_msg_idx`、`auth_token` |
| `attachments` | `tuple[MessageAttachment, ...]` | 图片、语音、视频、文件 |
| `mentions` | `tuple[User, ...]` | 被 @ 的其他成员（不含机器人） |
| `ark_data` | `ArkData \| None` | 卡片消息 |
| `msg_elements` | `tuple[MsgElement, ...]` | 引用/合并消息内容 |
| `event_id` | `str \| None` | 事件信封 ID，可用于事件回复 |
| `seq` | `int \| None` | 事件序号 |

便捷属性：

- `is_quote` / `is_card`
- `msg_idx` / `ref_msg_idx` / `auth_token`
- `quoted`：引用消息中的被引用元素
- `attachments_of("image/")`：按 MIME 前缀筛选附件
- `C2CMessage.user_openid`
- `GroupMessage.group_openid` / `member_openid`

全量群消息中，`content` 内的 @ 会替换为 `<@member_openid>`，@全体成员为 `<@all>`；被 @ 的成员列表在 `mentions`。

## 处理器约定

处理器可以是同步或异步函数，接收一个事件对象：

```python
@bot.on_group_message()
async def handler(event: GroupMessage) -> None:
    ...
```

也可以直接使用事件总线：

```python
bot.bus.subscribe("GROUP_AT_MESSAGE_CREATE", handler, priority=10)
```

### 优先级

同一事件的处理器按 `priority` 从高到低串行执行。高优先级处理器先运行并先完成：

```python
@bot.on_group_message(priority=100)
async def audit(event): ...

@bot.on_group_message(priority=0)
async def business(event): ...
```

### 只执行一次

```python
@bot.on("READY", once=True)
async def on_ready(event): ...
```

### 错误处理

```python
@bot.on_error
async def on_error(event, handler, exc) -> None:
    logging.exception("handler failed", exc_info=exc)
```

处理器异常不会终止 worker，也不会阻断同一事件的其他处理器。未设置错误处理器时只写日志。

### 通配与未知事件

```python
@bot.on_raw()
async def log_all(event) -> None:
    if isinstance(event, UnknownEvent):
        ...
```

未知事件保留原始 `name` 与 `data`，不会因为平台新增事件而中断分发。

## 去重

QQ 为保证送达可能重复推送同一条消息。默认去重键：

1. `message_scene.ext.msg_idx`（消息事件优先）；
2. 信封 `id`；
3. `t + seq`。

可通过 `gateway.dedup_ttl` 和 `gateway.dedup_max_size` 调整窗口。业务若需要「同一用户重复发送相同文本仍分别处理」，不要关闭去重；去重针对平台重复投递，不是文本内容。

## 被动回复与序号

`Bot.reply` 自动设置 `msg_id` 与递增 `msg_seq`：

```python
await bot.reply(event, "第一条")
await bot.reply(event, "第二条")   # msg_seq = 2
```

平台规则：

- 单聊：`msg_id` 60 分钟内有效，每条消息最多回复 4 次；
- 群聊：`msg_id` 5 分钟内有效，每条消息最多回复 5 次；
- 相同 `msg_id + msg_seq` 重复发送会被拒绝。

需要精确控制时可直接调用 API：

```python
await bot.group.send(
    event.group_openid,
    content="manual",
    msg_id=event.id,
    msg_seq=10,
)
```

## 互动事件

`INTERACTION_CREATE` 包含按钮回调、快捷菜单、消息反馈、清空会话、授权等类型。仅 `type=11`（消息按钮）与 `type=12`（快捷菜单）需要回应：

```python
@bot.on_interaction()
async def on_interaction(event: InteractionEvent) -> None:
    await bot.acknowledge_interaction(event)  # 3 秒内
    if event.button_data:
        await bot.reply(event, f"收到：{event.button_data}")
```

互动事件有两个 ID：

- `event.id`：互动 ID，用于 `PUT /interactions/{event.id}` 回应；
- `event.event_id`：外层信封 ID，用于发消息接口的被动回复 `event_id`。

`Bot.reply(event)` 会自动使用 `event.event_id`，不要用 `event.id` 代替，否则平台返回 `40034025 请求参数 event_id 无效`。

`bot.acknowledge_interaction` 对其他类型是空操作。回应码：

| `InteractionCode` | 值 | 含义 |
|---|---|---|
| `SUCCESS` | 0 | 成功 |
| `FAILED` | 1 | 操作失败 |
| `RATE_LIMITED` | 2 | 操作频繁 |
| `DUPLICATE` | 3 | 重复操作 |
| `FORBIDDEN` | 4 | 没有权限 |
| `ADMIN_ONLY` | 5 | 仅管理员 |

## 群成员与入群事件

`GroupJoinRequest` 将完整载荷放在 `request: JoinRequest` 中，并暴露常用属性：

- `group_openid`
- `join_request_id`
- `member_openid`
- `username`
- `apply_source`（`self_apply` / `invited`）
- `risk_tips`
- `verify_message`
- `auto_approved`（自动审批通过时含 `strategy_id`）

审批示例见 [群聊管理方案](group-management.md)。
