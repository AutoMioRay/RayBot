# API 参考

本文按**使用场景**组织，而不是按类组织。先看快速导航，再进入对应章节。

| 我想做什么 | 章节 |
|---|---|
| 配置 AppID、启动/关闭机器人、注册事件处理器 | [基本配置与初始化](#基本配置与初始化) |
| 给一个用户发消息、回复用户、流式输出、撤回 | [单聊消息](#单聊消息) |
| 给群发消息、@成员、回复群消息、撤回 | [群聊消息](#群聊消息) |
| 查群信息、成员、禁言、黑名单、入群审批、自动审批 | [群聊管理](#群聊管理) |
| 上传图片/视频/文件，管理 Markdown 素材 | [富媒体与素材](#富媒体与素材) |
| 发送按钮、处理点击、配置菜单与指令面板 | [互动按钮与菜单](#互动按钮与菜单) |
| 查机器人资料、生成分享链接 | [机器人资料与分享](#机器人资料与分享) |
| 选择接入方式、订阅事件、自定义传输 | [事件接入与网关](#事件接入与网关) |
| 处理错误码、重试、限流 | [错误处理与重试](#错误处理与重试) |
| 直接使用 TokenManager/APIClient/EventBus | [附录：低级组件、模型与工具](#附录低级组件模型与工具) |

所有 I/O 方法都是 `async`。OpenAPI 空响应统一返回 `None`；JSON 响应转换为模型或字典；业务错误统一抛出 `APIError`，请用 `err_code` 判断，不要依赖 `message` 文本。

## 基本配置与初始化

### 最小可运行示例

```python
from qqbot_toolkit import Bot, BotConfig

bot = Bot(BotConfig.from_env())

@bot.on_message()
async def on_message(event):
    await bot.reply(event, f"收到：{event.content}")

if __name__ == "__main__":
    bot.run()  # WebSocket 模式
```

### 凭据与 BotConfig

```python
from qqbot_toolkit import Bot, BotConfig

config = BotConfig(
    app_id="APPID",
    client_secret="CLIENTSECRET",
)
bot = Bot(config)
```

也可以从环境变量读取（`QQBOT_APP_ID`、`QQBOT_CLIENT_SECRET`，可选 `QQBOT_BASE_URL`）：

```python
config = BotConfig.from_env()
```

测试或自定义传输时可以注入依赖：

```python
import httpx

bot = Bot(
    config,
    transport=httpx.MockTransport(handler),  # 自定义 httpx transport
    http_client=None,                        # 或直接注入 httpx.AsyncClient
    plain_client=None,                       # 预签名 PUT 使用的普通 client
    bus=None,                                # 自定义 EventBus
)
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `app_id` | `str` | 开放平台 AppID |
| `client_secret` | `str` | 开放平台 ClientSecret，用于获取 `access_token` |
| `http` | `HTTPConfig` | 超时、连接池、重试、限流 |
| `gateway` | `GatewayConfig` | Intents、分片、事件队列、重连 |

嵌套配置不可直接修改，使用 `dataclasses.replace`：

```python
from dataclasses import replace
from qqbot_toolkit import HTTPConfig, GatewayConfig

config = config.with_overrides(
    http=replace(HTTPConfig(), timeout=20.0, max_retries=3),
    gateway=replace(GatewayConfig(), auto_shard=True),
)
```

完整字段见 [配置项](configuration.md)。

### 启动与关闭

```python
await bot.start()                            # 事件总线 + WebSocket
await bot.stop()                             # 停止传输并排空事件队列
await bot.aclose()                           # 额外关闭 HTTP 连接与 token 缓存
```

同步入口：

```python
bot.run()                 # WebSocket
await bot.run_forever()   # 异步入口，直到 stop()
```

### Bot 属性

| 属性 | 类型 | 用途 |
|---|---|---|
| `bot.c2c` | `C2CAPI` | 单聊消息 |
| `bot.group` | `GroupAPI` | 群聊消息 |
| `bot.groups` | `GroupsAPI` | 群聊管理 |
| `bot.media` | `MediaAPI` | 富媒体与素材 |
| `bot.bot` | `BotAPI` | 机器人资料、菜单、指令面板 |
| `bot.interactions` | `InteractionsAPI` | 互动事件回应 |
| `bot.gateway_api` | `GatewayAPI` | 网关地址发现 |
| `bot.bus` | `EventBus` | 自定义事件订阅 |
| `bot.tokens` | `TokenManager` | token 获取/刷新 |
| `bot.http` | `APIClient` | 底层 HTTP 调用 |
| `bot.config` | `BotConfig` | 当前配置 |

### 事件处理器注册

| 方法 | 订阅事件 |
|---|---|
| `on(event_name, *, priority=0, once=False)` | 任意原始事件名 |
| `on_c2c_message(...)` | `C2C_MESSAGE_CREATE` |
| `on_group_at_message(...)` | `GROUP_AT_MESSAGE_CREATE` |
| `on_group_message(...)` | `GROUP_AT_MESSAGE_CREATE`、`GROUP_MESSAGE_CREATE` |
| `on_message(...)` | 单聊 + 两种群消息 |
| `on_interaction(...)` | `INTERACTION_CREATE` |
| `on_group_join_request(...)` | `GROUP_JOIN_REQUEST` |
| `on_group_member_add(...)` | `GROUP_MEMBER_ADD` |
| `on_group_member_remove(...)` | `GROUP_MEMBER_REMOVE` |
| `on_group_add_robot(...)` | `GROUP_ADD_ROBOT` |
| `on_group_del_robot(...)` | `GROUP_DEL_ROBOT` |
| `on_group_msg_receive(...)` | `GROUP_MSG_RECEIVE` |
| `on_group_msg_reject(...)` | `GROUP_MSG_REJECT` |
| `on_friend_add(...)` | `FRIEND_ADD` |
| `on_friend_del(...)` | `FRIEND_DEL` |
| `on_c2c_msg_receive(...)` | `C2C_MSG_RECEIVE` |
| `on_c2c_msg_reject(...)` | `C2C_MSG_REJECT` |
| `on_raw(*, priority=0)` | 所有事件，包括未知事件 |
| `on_error(handler)` | 处理器异常 |

`priority` 越大越先执行；`once=True` 只执行一次。事件字段见 [事件与处理器](events.md)。

### 通用回复 `bot.reply`

```python
await bot.reply(event, content="收到")
```

| 参数 | 类型 | 说明 |
|---|---|---|
| `event` | `C2CMessage \| GroupMessage \| InteractionEvent` | 要回复的事件 |
| `content` | `str \| None` | 纯文本 |
| `markdown` | `MessageMarkdown \| str \| None` | Markdown |
| `media` | `MediaInfo \| str \| None` | 已上传的 `file_info` |
| `keyboard` | `Keyboard \| dict \| None` | 内嵌键盘 |
| `message_reference` | `MessageReference \| str \| None` | 引用回复 |
| `msg_seq` | `int \| None` | 不传时自动递增 |
| `**kwargs` | — | 透传 `is_wakeup` 等单聊参数 |

返回 `MessageResponse`。无法回复的事件类型抛 `TypeError`；互动事件缺少外层 `event_id` 抛 `ValueError`。

`reply_text` / `reply_markdown` / `reply_media` 是快捷方法。

### 主动消息与被动消息

| 类型 | 特征 | 说明 |
|---|---|---|
| 主动消息 | 不传 `msg_id`/`event_id`/`is_wakeup` | 受主动消息频控和用户开关限制 |
| 被动回复 | 传 `msg_id` | 单聊 60 分钟/最多 4 次，群聊 5 分钟/最多 5 次 |
| 事件回复 | 传 `event_id` | 互动事件、加好友、机器人入群等 |
| 召回消息 | `is_wakeup=True` | 仅单聊，与 `msg_id`/`event_id` 互斥 |

`msg_type`：

| 值 | 内容字段 | 说明 |
|---|---|---|
| `0` | `content` | 纯文本 |
| `2` | `markdown` | Markdown |
| `6` | `input_notify` | 单聊输入中状态 |
| `7` | `media` | 富媒体，先上传得到 `file_info` |

不传 `msg_type` 时按字段推断：`input_notify` → 6，`media` → 7，`markdown` → 2，否则 0。

## 单聊消息

通过 `bot.c2c` 访问。

### 发送文本

```python
msg = await bot.c2c.send_text(user_openid, "你好")
print(msg.id)
```

### 发送 Markdown

```python
from qqbot_toolkit.models.outbound import MessageMarkdown

await bot.c2c.send(
    user_openid,
    markdown=MessageMarkdown(content="## 今日推荐\n**重点内容**"),
)
```

也可以直接传字符串，库会包装成 `MessageMarkdown`：

```python
await bot.c2c.send_markdown(user_openid, "**加粗**")
```

### 发送富媒体

先上传，再发送（上传接口见 [富媒体与素材](#富媒体与素材)）：

```python
from qqbot_toolkit.api.media import MediaTarget

media = await bot.media.upload_file(MediaTarget.c2c(user_openid), "image.png")
await bot.c2c.send_media(user_openid, media.file_info)
```

### 键盘与引用

```python
from qqbot_toolkit.models.outbound import (
    KeyboardRow, MessageReference, command_button, keyboard,
)

kb = keyboard(KeyboardRow(buttons=[command_button("帮助", "/help")]))
await bot.c2c.send(
    user_openid,
    content="请选择",
    keyboard=kb,
    message_reference=MessageReference(message_id="被引用的消息 ID"),
)
```

引用机器人自己发送的消息时，`message_id` 来自发送响应的 `ext_info.ref_idx`。

### 被动回复

推荐使用 `bot.reply`，自动带上 `msg_id` 和递增 `msg_seq`：

```python
@bot.on_c2c_message()
async def on_message(event):
    await bot.reply(event, "收到")
```

手动控制：

```python
await bot.c2c.send(
    event.user_openid,
    content="收到",
    msg_id=event.id,
    msg_seq=1,
)
```

同一 `msg_id` 多次回复时递增 `msg_seq`；相同的 `msg_id + msg_seq` 会被平台拒绝。

对 `FRIEND_ADD` 等事件使用外层 `event_id`：

```python
@bot.on_friend_add()
async def on_friend_add(event):
    await bot.c2c.send(event.openid, content="欢迎", event_id=event.event_id)
```

### 输入中状态

```python
from qqbot_toolkit.models.outbound import InputNotify

await bot.c2c.send(
    user_openid,
    input_notify=InputNotify(input_second=30),
    msg_id=event.id,
)
```

### 流式消息

```python
async def answer(event):
    session = bot.c2c.stream(event.user_openid, msg_id=event.id)
    await session.push("**正在生成**")
    await session.push("\n\n第一部分…")
    await session.finish("\n\n最终结果")
```

- `input_mode="append"`：`content_raw` 是增量；
- `input_mode="replace"`：`content_raw` 是当前全量文本，必须以上次内容为前缀；
- 首个分片自动生成 `stream_msg_id`，后续分片自动携带；
- 实测部分机器人在没有被动上下文时返回 `50015001`，流式消息应在回复真实入站消息时使用。

底层分片接口：

```python
await bot.c2c.send_stream(
    user_openid,
    content_raw="正在生成",
    input_state=1,
    index=0,
    msg_id=event.id,
)
```

### 撤回

```python
await bot.c2c.recall(user_openid, message_id)
```

发送超过 2 分钟不可撤回。

### C2CAPI.send 参数

```python
await bot.c2c.send(
    user_openid,
    *,
    content=None,
    markdown=None,
    media=None,
    keyboard=None,
    msg_id=None,
    event_id=None,
    msg_seq=1,
    message_reference=None,
    is_wakeup=None,
    input_notify=None,
    msg_type=None,
) -> MessageResponse
```

| 参数 | 说明 |
|---|---|
| `content` | 文本，`msg_type=0` |
| `markdown` | `MessageMarkdown` 或字符串，`msg_type=2` |
| `media` | `file_info` 或 `MediaInfo`，`msg_type=7` |
| `keyboard` | 内嵌键盘 |
| `msg_id` / `event_id` | 被动回复，二者互斥 |
| `msg_seq` | 被动回复序号，从 1 开始 |
| `message_reference` | 引用回复 |
| `is_wakeup` | 互动召回消息，与 `msg_id`/`event_id` 互斥 |
| `input_notify` | 输入中状态，`msg_type=6` |
| `msg_type` | 显式指定，通常不用传 |

主动消息（无 `msg_id`/`event_id`/`is_wakeup`）额外经过单关系限流桶。

### 单聊方法总表

| 方法 | 返回 | 用途 |
|---|---|---|
| `await send(...)` | `MessageResponse` | 通用发送 |
| `await send_text(user, content, **kw)` | `MessageResponse` | 文本 |
| `await send_markdown(user, markdown, **kw)` | `MessageResponse` | Markdown |
| `await send_media(user, file_info, **kw)` | `MessageResponse` | 富媒体 |
| `await recall(user, message_id)` | `None` | 撤回 |
| `await send_stream(...)` | `MessageResponse` | 单分片流式 |
| `stream(...)` | `C2CStreamSession` | 流式会话 |
| `session.push(chunk)` | `MessageResponse` | 发送流式增量 |
| `session.finish(final=None)` | `MessageResponse` | 结束流式 |

## 群聊消息

通过 `bot.group` 访问。群消息与单聊共享大部分参数，但不支持 `input_notify`、`is_wakeup` 和流式接口。

### 发送文本

```python
msg = await bot.group.send_text(group_openid, "大家好")
```

### 发送 Markdown

```python
from qqbot_toolkit.models.outbound import MessageMarkdown

await bot.group.send(
    group_openid,
    markdown=MessageMarkdown(content="### 群公告\n- 第一条\n- 第二条"),
)
```

### 发送富媒体

```python
from qqbot_toolkit.api.media import MediaTarget

media = await bot.media.upload_file(MediaTarget.group(group_openid), "image.png")
await bot.group.send_media(group_openid, media.file_info)
```

### @成员、键盘与引用

```python
from qqbot_toolkit import mention
from qqbot_toolkit.models.outbound import KeyboardRow, command_button, keyboard

content = f"{mention(member_openid)} 你好"
kb = keyboard(KeyboardRow(buttons=[command_button("签到", "/sign", enter=True)]))
await bot.group.send(group_openid, content=content, keyboard=kb)
```

`mention` 生成 `<qqbot-at-user id="..." />`。全量群消息中，用户 @ 其他人会以 `<@member_openid>` 出现在 `content` 中。

### 被动回复

```python
@bot.on_group_at_message()
async def on_group_message(event):
    await bot.reply(event, "收到")
```

手动回复：

```python
await bot.group.send(
    event.group_openid,
    content="收到",
    msg_id=event.id,
    msg_seq=1,
)
```

`event_id` 支持 `INTERACTION_CREATE`、`GROUP_ADD_ROBOT`、`GROUP_MSG_RECEIVE`：

```python
@bot.on_interaction()
async def on_interaction(event):
    await bot.acknowledge_interaction(event)
    await bot.reply(event, "操作成功")
```

### 两种群消息事件

| 事件 | 触发条件 | 模型 |
|---|---|---|
| `GROUP_AT_MESSAGE_CREATE` | 用户 @ 机器人 | `GroupAtMessage`，`content` 已去掉 @ 前缀 |
| `GROUP_MESSAGE_CREATE` | 开启“接收所有消息”后的每条群消息 | `GroupAllMessage` |

`on_group_message` 同时订阅两者；`on_group_at_message` 只订阅 @ 消息。

### 撤回

```python
await bot.group.recall(group_openid, message_id)
```

机器人是群管理员时，可以撤回普通成员的消息；否则只能撤回自己发送的消息。超过 2 分钟不可撤回。

### 群聊方法总表

| 方法 | 返回 | 用途 |
|---|---|---|
| `await send(...)` | `MessageResponse` | 通用发送 |
| `await send_text(group, content, **kw)` | `MessageResponse` | 文本 |
| `await send_markdown(group, markdown, **kw)` | `MessageResponse` | Markdown |
| `await send_media(group, file_info, **kw)` | `MessageResponse` | 富媒体 |
| `await recall(group, message_id)` | `None` | 撤回 |

`send` 参数与 `C2CAPI.send` 相同，去掉 `is_wakeup`、`input_notify`、`msg_type=6` 和流式参数。

## 群聊管理

通过 `bot.groups` 访问。详细的管理策略、权限矩阵和审计建议见 [群聊管理方案](group-management.md)。

### 前置条件

1. **管理员权限**：禁言、踢人、黑名单、入群审批、自动审批策略等写操作要求机器人是群管理员。
2. **事件订阅**：成员加入/退出、入群申请需要 `GROUP_MEMBER_EVENT (1 << 24)`；机器人入群/退群、消息开关需要 `GROUP_AND_C2C_EVENT (1 << 25)`。
3. **接口权限**：成员列表、成员详情、批量移除、黑名单属于内邀接口，无权限时返回 `40012010`，即使机器人是管理员也可能不可用。

先检查机器人角色：

```python
state = await bot.groups.get_bot_state(group_openid)
if state.member_role not in {"admin", "owner"}:
    raise RuntimeError("机器人不是群管理员")
```

### 群信息与机器人状态

```python
info = await bot.groups.get_info(group_openid)
print(info.group_name, info.group_member_num, info.group_tags)

state = await bot.groups.get_bot_state(group_openid)
print(state.member_role, state.allow_proactive_msg, state.recv_msg_setting)
```

| 方法 | 返回 | 说明 |
|---|---|---|
| `get_info(group_openid)` | `GroupInfo` | 群名称、简介、分类、标签、成员数 |
| `get_bot_state(group_openid)` | `GroupBotState` | 机器人角色、入群时间、主动消息开关、消息接收模式 |

### 成员管理

```python
page = await bot.groups.get_members(group_openid)
for member in page.members:
    print(member.member_openid, member.member_role, member.username)

async for member in bot.groups.iter_members(group_openid):
    ...

member = await bot.groups.get_member(group_openid, member_openid)

result = await bot.groups.batch_remove_members(
    group_openid,
    [member_openid_1, member_openid_2],
    add_to_blacklist=True,
)
```

| 方法 | 返回 | 说明 |
|---|---|---|
| `get_members(group, *, cursor="")` | `GroupMemberPage` | 每页最多 30 人 |
| `iter_members(group, *, max_pages=None)` | `AsyncIterator[GroupMember]` | 自动翻页 |
| `get_member(group, member)` | `GroupMember` | 单个成员 |
| `batch_remove_members(group, ids, *, add_to_blacklist=False)` | `BatchRemoveResult` | 单次最多 20 人 |

> 成员列表、成员详情、批量移除当前为内邀接口，无权限时返回 `40012010`。批量移除是破坏性操作，务必先做权限校验和审计。

### 禁言

```python
from datetime import UTC, datetime, timedelta

until = datetime.now(UTC) + timedelta(minutes=30)
await bot.groups.mute_member(group_openid, member_openid, until)

mute_state = await bot.groups.get_mute_state(group_openid)
print(mute_state.global_rule.mode, [m.member_openid for m in mute_state.members])

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

| 方法 | 返回 | 说明 |
|---|---|---|
| `get_mute_state(group)` | `GroupMuteState` | 全员禁言规则 + 当前被禁言成员 |
| `set_member_mutes(group, changes)` | `None` | 单次最多 20 项 |
| `mute_member(group, member, until, *, op="add")` | `None` | `until` 支持 `datetime`、Unix 时间戳、RFC3339 |
| `unmute_member(group, member)` | `None` | 立即解除禁言 |

限制：

- 最长 30 天；
- 只能操作普通成员，不能操作群主、管理员或机器人；
- 群级全员禁言的写入接口不在当前文档范围，`get_mute_state` 的 `global_rule` 只读。

### 黑名单

```python
page = await bot.groups.get_blacklist(group_openid, limit=20)
async for user in bot.groups.iter_blacklist(group_openid):
    print(user.member_openid, user.username)

await bot.groups.update_blacklist(group_openid, "add", ["MEMBER_OPENID"])
await bot.groups.update_blacklist(group_openid, "del", ["MEMBER_OPENID"])
```

| 方法 | 返回 | 说明 |
|---|---|---|
| `get_blacklist(group, *, cursor="", limit=None)` | `BlacklistPage` | 分页，limit 最大 100 |
| `iter_blacklist(group, *, limit=100, max_pages=None)` | `AsyncIterator[BlacklistUser]` | 自动翻页 |
| `update_blacklist(group, op, ids)` | `BlacklistUpdateResult` | `op=add/del`，单次最多 20 个 |

只有目标用户不在群中时才能加入黑名单；接口当前为内邀能力，常见 `40012010`。

### 入群审批

事件处理：

```python
@bot.on_group_join_request()
async def review(event):
    if event.risk_tips:
        return
    await bot.groups.approve_join_request(
        event.group_openid,
        event.member_openid,
        op="approve",
        join_request_id=event.join_request_id,
    )
```

列表与模型审批：

```python
async for request in bot.groups.iter_join_requests(group_openid):
    print(request.username, request.verify_info.verify_message if request.verify_info else "")

await bot.groups.approve_join(group_openid, request)
await bot.groups.reject_join(group_openid, request, reason="条件不满足", blacklist=False)
```

| 方法 | 返回 | 说明 |
|---|---|---|
| `get_join_requests(group, *, cursor="", limit=None)` | `JoinRequestPage` | 分页，limit 最大 50 |
| `iter_join_requests(group, *, limit=50, max_pages=None)` | `AsyncIterator[JoinRequest]` | 自动翻页 |
| `approve_join_request(group, member, *, op="approve", join_request_id=None, reject_reason=None, add_to_blacklist=False)` | `None` | 手动审批 |
| `approve_join(group, request)` | `None` | 通过模型审批 |
| `reject_join(group, request, *, reason=None, blacklist=False)` | `None` | 拒绝，可选拉黑 |

### 自动审批策略

```python
state = await bot.groups.create_strategy(
    group_openids=[group_openid],
    is_enable="off",
    remark="白名单策略",
)

await bot.groups.update_strategy_whitelist(
    state.strategy_id,
    op="add",
    whitelist_users=["123456789"],
)

await bot.groups.update_strategy(
    state.strategy_id,
    group_action={"op": "add", "group_openids": ["OTHER_GROUP"]},
)

# execute_strategy 要求策略处于启用状态
await bot.groups.update_strategy(state.strategy_id, is_enable="on")
await bot.groups.execute_strategy(state.strategy_id)
await bot.groups.delete_strategy(state.strategy_id)
```

| 方法 | 返回 | 说明 |
|---|---|---|
| `list_strategies(*, cursor="", limit=None)` | `StrategyPage` | 分页 |
| `iter_strategies(*, limit=50, max_pages=None)` | `AsyncIterator[JoinApprovalStrategy]` | 自动翻页 |
| `create_strategy(*, group_openids=None, group_ids=None, is_enable="on", expire_at=None, remark=None)` | `StrategyState` | 关联群二选一 |
| `update_strategy(id, *, is_enable=None, expire_at=None, group_action=None, remark=None)` | `StrategyState` | 修改状态/关联群 |
| `delete_strategy(id)` | `None` | 删除 |
| `execute_strategy(id)` | `None` | 全量扫描，异步执行 |
| `update_strategy_whitelist(id, *, op, whitelist_users)` | `WhitelistUpdateResult` | 单次最多 10000 个 |

注意事项：

- `create_strategy` 的 `group_openids` 与 `group_ids` 必须且只能提供一个；
- 一个机器人最多 20 个策略；
- 实测对 `is_enable="off"` 的策略执行 `execute_strategy` 返回 `50105002`，执行前先启用；
- 策略规则只有在机器人是群管理员时才生效。

### 群管理方法总表

| 方法 | 返回 |
|---|---|
| `get_info(group)` | `GroupInfo` |
| `get_bot_state(group)` | `GroupBotState` |
| `get_members(group, *, cursor="")` | `GroupMemberPage` |
| `iter_members(group, *, max_pages=None)` | `AsyncIterator[GroupMember]` |
| `get_member(group, member)` | `GroupMember` |
| `batch_remove_members(group, ids, *, add_to_blacklist=False)` | `BatchRemoveResult` |
| `get_blacklist(group, *, cursor="", limit=None)` | `BlacklistPage` |
| `iter_blacklist(group, *, limit=100, max_pages=None)` | `AsyncIterator[BlacklistUser]` |
| `update_blacklist(group, op, ids)` | `BlacklistUpdateResult` |
| `get_mute_state(group)` | `GroupMuteState` |
| `set_member_mutes(group, changes)` | `None` |
| `mute_member(group, member, until, *, op="add")` | `None` |
| `unmute_member(group, member)` | `None` |
| `get_join_requests(group, *, cursor="", limit=None)` | `JoinRequestPage` |
| `iter_join_requests(group, *, limit=50, max_pages=None)` | `AsyncIterator[JoinRequest]` |
| `approve_join_request(...)` | `None` |
| `approve_join(group, request)` | `None` |
| `reject_join(group, request, ...)` | `None` |
| `list_strategies(*, cursor="", limit=None)` | `StrategyPage` |
| `iter_strategies(*, limit=50, max_pages=None)` | `AsyncIterator[JoinApprovalStrategy]` |
| `create_strategy(...)` | `StrategyState` |
| `update_strategy(id, ...)` | `StrategyState` |
| `delete_strategy(id)` | `None` |
| `execute_strategy(id)` | `None` |
| `update_strategy_whitelist(id, *, op, whitelist_users)` | `WhitelistUpdateResult` |

## 富媒体与素材

通过 `bot.media` 访问。单聊与群聊的上传桶相互隔离，`file_info` 不能跨场景使用。

### MediaTarget

单聊与群聊的上传目标：

```python
from qqbot_toolkit.api.media import MediaTarget

MediaTarget.c2c(user_openid)
MediaTarget.group(group_openid)
```

字段：`kind`（`"c2c"` / `"group"`）、`openid`。属性 `base_path` 返回 `/v2/users/{id}` 或 `/v2/groups/{id}`。

### 选择上传方式

| 场景 | 方法 |
|---|---|
| 文件已有公网 URL | `upload_url` |
| 内存中的 bytes | `upload_bytes` |
| 本地文件 | `upload_file` |
| 大文件 / 需要自定义分片 | `upload_prepare` + PUT + `upload_part_finish` + `upload` |
| 上传后立即发送 | `srv_send_msg=True` |

### URL 上传

```python
from qqbot_toolkit.api.media import MediaTarget
from qqbot_toolkit.constants import FileType

target = MediaTarget.group(group_openid)
result = await bot.media.upload_url(
    target,
    FileType.IMAGE,
    "https://example.com/image.png",
)
await bot.group.send_media(group_openid, result.file_info)
```

### 内存字节

```python
result = await bot.media.upload_bytes(
    MediaTarget.c2c(user_openid),
    FileType.IMAGE,
    "image.png",
    data,
)
```

不超过 5 MiB 时 Base64 直传；超过或 `force_chunked=True` 时自动分片。

### 本地文件

```python
result = await bot.media.upload_file(
    MediaTarget.group(group_openid),
    "video.mp4",
    srv_send_msg=False,
)
await bot.group.send_media(group_openid, result.file_info)
```

`file_type` 不传时按扩展名推断；超过 5 MiB 自动分片，并发度使用服务端 `upload_config.concurrency`。

### 上传并直接发送

```python
result = await bot.media.upload_file(
    MediaTarget.c2c(user_openid),
    "image.png",
    srv_send_msg=True,
)
print(result.id)  # 消息 ID
```

会占用主动消息频次。

### 底层分片接口

```python
import asyncio
from qqbot_toolkit.api.media import hash_file

prepared = await bot.media.upload_prepare(
    target,
    file_type=FileType.VIDEO,
    file_size=size,
    file_name="video.mp4",
    hashes=await asyncio.to_thread(hash_file, path),
)
# 对 prepared.parts 逐片 PUT，然后：
await bot.media.upload_part_finish(
    target,
    upload_id=prepared.upload_id,
    part_index=0,
    block_size=prepared.block_size,
    md5=part_md5,
)
# 全部分片完成后合并：
result = await bot.media.upload(
    target,
    file_type=FileType.VIDEO,
    upload_id=prepared.upload_id,
    file_name="video.mp4",
)
```

### Markdown 素材图片

```python
image = await bot.media.upload_image("chart.png")
markdown = f"![K线 #800px #400px]({image.url})"
await bot.group.send(group_openid, markdown=markdown)

page = await bot.media.list_images()
await bot.media.delete_image(image.image_id)
```

限制：10 MiB，png/jpeg/gif/webp，单机器人最多 100 张，连续 90 天未引用失效。

### 方法总表

| 方法 | 返回 | 说明 |
|---|---|---|
| `upload_prepare(target, *, file_type, file_size, file_name, hashes)` | `UploadPrepareResult` | 分片第一步 |
| `upload_part_finish(target, *, upload_id, part_index, block_size, md5=None)` | `None` | 分片完成通知 |
| `upload(target, *, file_type, url=None, upload_id=None, file_name=None, file_data=None, srv_send_msg=False)` | `MessageResponse` | 上传/合并 |
| `upload_url(target, file_type, url, *, srv_send_msg=False)` | `MessageResponse` | URL 转存 |
| `upload_bytes(target, file_type, file_name, data, *, srv_send_msg=False, force_chunked=False)` | `MessageResponse` | bytes 上传 |
| `upload_file(target, path, *, file_type=None, file_name=None, srv_send_msg=False, force_chunked=False)` | `MessageResponse` | 本地文件 |
| `upload_image(path)` | `MaterialImage` | Markdown 素材 |
| `list_images(*, cursor=None)` | `MaterialImagePage` | 素材列表 |
| `delete_image(image_id)` | `None` | 删除素材 |

辅助函数：`hash_bytes(data)`、`hash_file(path)`、`infer_file_type(path)`。

平台会校验图片实际可用性；1×1 等边界尺寸可能返回 `40034002`，使用常规尺寸的合法图片即可。

## 互动按钮与菜单

### 构建键盘

```python
from qqbot_toolkit.models.outbound import (
    ButtonAction, Keyboard, KeyboardButton, KeyboardContent, KeyboardRow,
    Permission, RenderData, command_button, keyboard, link_button,
)

# 指令按钮：点击后发送 /sign；enter=True 仅单聊生效
kb = keyboard(KeyboardRow(buttons=[command_button("签到", "/sign", enter=True)]))

# 链接按钮
kb = keyboard(KeyboardRow(buttons=[link_button("官网", "https://example.com")]))

# 回调按钮：点击触发 INTERACTION_CREATE
callback = KeyboardButton(
    id="btn_check",
    render_data=RenderData(label="确认", style=1),
    action=ButtonAction(
        type=1,
        permission=Permission(type=2),
        data="check:confirm",
        unsupport_tips="请升级 QQ 后重试",
    ),
)
kb = Keyboard(content=KeyboardContent(rows=[KeyboardRow(buttons=[callback])]))
```

按钮 `action.type`：

| 值 | 行为 |
|---|---|
| `0` | 跳转链接 |
| `1` | 回调机器人，触发 `INTERACTION_CREATE` |
| `2` | 指令按钮，插入/发送命令 |

### 发送与处理点击

```python
@bot.on_interaction()
async def on_interaction(event):
    # 必须在 3 秒内回应，否则客户端一直 loading
    await bot.acknowledge_interaction(event)
    await bot.reply(event, f"收到按钮数据：{event.button_data}")
```

互动事件有两个 ID：

- `event.id`：互动 ID，用于 `PUT /interactions/{id}` 回应；
- `event.event_id`：外层信封 ID，用于发消息接口的被动回复。

`Bot.reply` 自动使用 `event.event_id`；不要用 `event.id` 代替，否则返回 `40034025`。

互动类型：

| `type` | 含义 | 需要回应 |
|---|---|---|
| `11` | 消息按钮 | 是 |
| `12` | 单聊快捷菜单 | 是 |
| `13` | 消息反馈 | 否 |
| `14` | 清空会话 | 否 |
| `15` | 进出故事集 | 否 |
| `16` | 切换模型 | 否 |
| `18/19/20` | 用户/群授权 | 否 |

回应码：`0` 成功、`1` 失败、`2` 频繁、`3` 重复、`4` 无权限、`5` 仅管理员。

### 全局自定义菜单

```python
from qqbot_toolkit.models.outbound import Menu, MenuItem, SubMenuItem, Switch

menu = Menu(items=[
    MenuItem(name="帮助", type="send_message", send_message="/help"),
    MenuItem(name="官网", type="link", link="https://example.com"),
    MenuItem(name="更多", type="menu", sub_menu_items=[
        SubMenuItem(name="设置", type="send_message", send_message="/settings"),
    ]),
    MenuItem(name="搜索", type="switch", switch=Switch(switch_id="search", default=False)),
])
await bot.bot.update_global_menu(menu)
```

```python
info = await bot.bot.get_global_menu()
print(info.version, info.menu)
```

### 指令面板

```python
from qqbot_toolkit.models.outbound import Panel, PanelItem

panel_id = await bot.bot.create_panel(
    scope="group",
    target_type="specific",
    group_openids=[group_openid],
    panel=Panel(
        items=[
            PanelItem(type="command", name="签到", desc="每日签到"),
            PanelItem(type="link", name="官网", link="https://example.com"),
        ],
        remark="群助手",
    ),
)
await bot.bot.get_panel(panel_id)
await bot.bot.update_panel(panel_id, Panel(items=[PanelItem(type="command", name="新指令")]))
await bot.bot.update_panel_targets(panel_id, op="del", group_openids=[group_openid])
await bot.bot.update_panel_targets(panel_id, op="add", group_openids=[group_openid])
await bot.bot.delete_panel(panel_id)
```

`scope` 支持 `c2c`、`group`、`channel`、`dm`；`channel`/`dm` 仅支持 `target_type="all"`。一个机器人最多 20 个面板，每个面板最多 20 个元素。

### 互动与菜单方法总表

| 方法 | 返回 | 用途 |
|---|---|---|
| `bot.acknowledge_interaction(event, code=0)` | `None` | ACK 按钮/快捷菜单 |
| `bot.interactions.respond(interaction_id, code=0)` | `None` | 直接回应 |
| `bot.bot.get_global_menu()` | `MenuInfo` | 查询全局菜单 |
| `bot.bot.update_global_menu(menu)` | `None` | 覆盖全局菜单 |
| `bot.bot.create_panel(...)` | `str` | 创建面板 |
| `bot.bot.list_panels(*, scope, cursor="", limit=None)` | `PanelPage` | 面板列表 |
| `bot.bot.iter_panels(scope, *, limit=50, max_pages=None)` | `AsyncIterator[PanelRecord]` | 自动翻页 |
| `bot.bot.get_panel(panel_id)` | `PanelDetail` | 面板详情 |
| `bot.bot.update_panel(panel_id, panel)` | `int` | 覆盖面板内容 |
| `bot.bot.delete_panel(panel_id)` | `None` | 删除面板 |
| `bot.bot.update_panel_targets(panel_id, *, op, user_openids=None, group_openids=None)` | `None` | 增删关联对象 |

## 机器人资料与分享

通过 `bot.bot` 访问。

```python
me = await bot.bot.get_me()
print(me.id, me.username, me.avatar)

url = await bot.bot.generate_share_link("campaign-1")
```

| 方法 | 返回 | 说明 |
|---|---|---|
| `get_me()` | `BotProfile` | 机器人资料 |
| `generate_share_link(callback_data=None)` | `str` | 好友邀请链接；`callback_data` 最长 32 字符 |

## 事件接入与网关

### 选择接入方式

```python
bot.run()                  # WebSocket
await bot.start()          # 事件总线 + WebSocket
```

当前版本仅支持 WebSocket 传输；Webhook 事件通道已封藏至 [archive/webhook/](../archive/webhook/README.md)。详细协议见 [WebSocket 接入与网关](gateway.md)。

### WebSocket

```python
info = await bot.gateway_api.get()
print(info.url, info.shards, info.session_start_limit.max_concurrency)
```

低级组件构造：

```python
from qqbot_toolkit.gateway import GatewayClient, ShardManager

GatewayClient(
    token_manager, gateway_api, config, bus, deduplicator=None,
    *, shard=None, connect_gate=None, gateway_info=None,
)
ShardManager(token_manager, gateway_api, config, bus, deduplicator=None)
```

| 方法/属性 | 说明 |
|---|---|
| `GatewayAPI.get()` | 获取 WSS 地址、分片建议、会话配额 |
| `ShardManager.run()` | 运行所有分片 |
| `ShardManager.start()` | 后台启动，返回 `asyncio.Task` |
| `ShardManager.stop()` | 停止所有分片 |
| `ShardManager.clients` | 当前分片客户端 |
| `GatewayClient.run()` / `stop()` | 单分片运行/停止 |
| `GatewayClient.shard` / `session_id` | 分片参数与当前会话 |

网关地址在连接生命周期内缓存，重连和 Resume 不会重复请求 `/gateway/bot`。

### 事件总线

```python
from qqbot_toolkit import EventBus

bus = EventBus(concurrency=64, queue_size=2048)
bot.bus.subscribe("GROUP_AT_MESSAGE_CREATE", handler, priority=10)
```

| 方法 | 说明 |
|---|---|
| `start()` | 启动 worker |
| `await stop(*, drain=True)` | 停止；默认排空队列 |
| `await publish(event)` | 入队，队列满时等待 |
| `publish_nowait(event)` | 非阻塞入队，满时返回 `False` |
| `await drain()` | 等待队列排空 |
| `subscribe(name, handler, *, priority=0, once=False)` | 订阅，返回取消函数 |
| `subscribe_all(handler, *, priority=0, once=False)` | 订阅全部事件 |
| `on(name, *, priority=0, once=False)` | 装饰器形式 |
| `on_error(handler)` | 设置错误处理器 |

### 去重

```python
from qqbot_toolkit import Deduplicator

dedup = Deduplicator(ttl=600.0, max_size=20000)
if dedup.is_duplicate("event-key"):
    return
```

消息事件优先按 `message_scene.ext.msg_idx` 去重，其次按外层事件 ID 或序号。

## 错误处理与重试

```python
from qqbot_toolkit.errors import APIError

try:
    await bot.group.send(group_openid, content="通知")
except APIError as exc:
    print(exc.err_code, exc.status, exc.trace_id)
    if exc.is_rate_limited:
        ...
    elif exc.is_auth_error:
        ...
```

`APIError` 字段：`message`、`status`、`err_code`、`trace_id`、`method`、`path`、`body`。

| 属性 | 条件 |
|---|---|
| `is_rate_limited` | HTTP 429 或限频类错误码 |
| `is_auth_error` | HTTP 401，或权限类错误码（`11253`、`40011030`、`40012010` 等） |
| `is_retryable` | HTTP 429/5xx，或 5xx 段业务错误码 |

`APIClient` 默认重试网络错误、429、5xx；401 会清空 token 并重试一次；400/403/404 和业务 `err_code` 不自动重试。`HTTPConfig.max_retries=0` 可关闭。

常见错误：

| 错误码 | 含义 |
|---|---|
| `40011030` | 机器人不是群管理员 |
| `40012010` | 接口未开通（内邀能力） |
| `40103004` | 目标成员是机器人/群主/管理员，不允许禁言 |
| `40034025` | `event_id` 无效，互动事件应使用外层 `event.event_id` |
| `40034002` | 富媒体格式不支持 |
| `50015001` | 流式接口无被动上下文或平台暂不可用 |

详见 [错误与重试](errors.md)。

## 附录：低级组件、模型与工具

### TokenManager

```python
TokenManager(app_id, client_secret, config=None, *, http_client=None, transport=None)
```

| 方法/属性 | 说明 |
|---|---|
| `await get_token(*, force_refresh=False)` | 返回有效 token，并发刷新只执行一次 |
| `await invalidate(token=None)` | 清空缓存 |
| `token` | 当前有效 token 或 `None` |
| `stats` | `TokenStats`：刷新次数、失败次数、最近刷新时间、最近错误 |
| `await aclose()` | 取消后台刷新并关闭内部 HTTP 客户端 |

### APIClient

```python
APIClient(token_manager, config=None, *, limiter=None, http_client=None, transport=None)
```

| 方法 | 说明 |
|---|---|
| `await request(method, path, *, json=None, params=None, headers=None, route=None, relation_scope=None, relation_key=None, request_timeout=None, max_retries=None)` | 通用请求 |
| `await get/post/put/patch/delete(path, **kwargs)` | 方法快捷方式 |
| `await aclose()` | 关闭内部客户端 |

`json`/`params` 中的 `None` 会被移除；响应体含非零 `err_code` 时抛出 `APIError`。

### 出站 payload

| 类型 | 用途 |
|---|---|
| `MessageMarkdown` | Markdown 内容或模板 |
| `Keyboard` / `KeyboardContent` / `KeyboardRow` / `KeyboardButton` | 内嵌键盘 |
| `RenderData` / `ButtonAction` / `Permission` / `Modal` | 按钮渲染、行为、权限、二次确认 |
| `MediaInfo` | `file_info` |
| `MessageReference` | 引用消息 |
| `InputNotify` | 单聊输入状态 |
| `MemberMuteChange` | 群成员禁言变更 |
| `Menu` / `MenuItem` / `SubMenuItem` / `Switch` | 全局自定义菜单 |
| `Panel` / `PanelItem` | 指令面板 |

所有 payload 继承 `Payload`，`to_dict()` 会递归移除 `None`。

### 工具函数

| 函数 | 说明 |
|---|---|
| `mention(member_openid)` | `<qqbot-at-user id="..." />` |
| `command_enter(text)` | `<qqbot-cmd-enter text="..." />`，仅 Markdown、单聊 |
| `command_input(text, *, show=None, reference=False)` | `<qqbot-cmd-input ... />`，仅 Markdown |
| `reply_target(event)` | 返回 `("c2c", user_openid)` 或 `("group", group_openid)` |
| `parse_rfc3339(value)` | 解析 RFC3339，失败返回 `None` |
| `format_rfc3339(value)` | `datetime`/Unix 时间戳/字符串 → RFC3339 |

### 入站模型

用户、消息、群管理、互动事件模型见 [事件与处理器](events.md)。所有入站模型保留 `raw` 原始字典，便于读取平台新增字段。
