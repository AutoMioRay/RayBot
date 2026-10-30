# 架构与并发模型

## 分层

```text
                 ┌──────────────────────────────┐
                 │             Bot              │
                 │ 生命周期 / 装饰器 / reply()   │
                 └──────────────┬───────────────┘
                                │
        ┌───────────────────────┼────────────────────────┐
        │                       │                        │
┌───────▼────────┐    ┌─────────▼─────────┐    ┌─────────▼─────────┐
│   api 分组      │    │   gateway 传输     │    │    events 总线     │
│ C2C / Group    │    │ WebSocket         │    │ publish / worker  │
│ Groups / Media │    │ 心跳 / Resume     │    │ 去重 / 分发        │
└───────┬────────┘    └─────────┬─────────┘    └─────────┬─────────┘
        │                       │                        │
┌───────▼────────┐    ┌─────────▼─────────┐    ┌─────────▼─────────┐
│  http 客户端    │    │  events.payload   │    │    models         │
│ 鉴权/重试/限流  │    │  opcode / 信封     │    │ 入站模型 / 出站   │
└───────┬────────┘    └───────────────────┘    └───────────────────┘
        │
┌───────▼────────┐
│ auth / config  │
│ token 缓存     │
└────────────────┘
```

依赖方向自上而下，底层不反向导入 `Bot`，因此 API 分组、事件模型和传输层都可以单独使用。例如只调用 OpenAPI 时，不需要启动事件总线：

```python
from qqbot_toolkit import Bot, BotConfig

bot = Bot(BotConfig(app_id="...", client_secret="..."))
state = await bot.groups.get_bot_state("GROUP_OPENID")
await bot.aclose()
```

## HTTP 调用路径

1. API 方法校验参数并构造 body。
2. `RateLimitRegistry` 按路由和（主动消息场景下的）用户/群 OpenID 获取令牌。
3. `APIClient` 从 `TokenManager` 取 token；缓存命中时不发请求。
4. 共享 `httpx.AsyncClient` 的连接池发送请求。
5. 2xx 但 body 含非零 `err_code` 时同样抛出 `APIError`。
6. 429 / 5xx / 网络错误按配置重试；401 会清空 token 并重试一次。

重试默认只覆盖瞬时错误。发送消息的 POST 在超时后重试可能产生重复投递，平台侧的 `msg_id + msg_seq` 去重与库侧事件去重会降低影响；需要严格一次语义时，把 `HTTPConfig.max_retries` 设为 `0`。

## 事件路径

```text
WebSocket
        │
        ▼
GatewayPayload(op, d, s, t, id)
        │
        ▼
parse_event(t, d)  ──►  C2CMessage / GroupMessage / InteractionEvent / ...
        │
        ▼
Deduplicator（msg_idx / event id / seq）
        │
        ▼
EventBus 有界队列
        │
        ▼
worker × dispatch_concurrency
        │
        ▼
按 priority 顺序执行该事件的处理器
```

### 并发与背压

- 单个事件循环，所有 I/O 非阻塞。
- 事件先进入 `asyncio.Queue`，队列长度由 `gateway.dispatch_queue_size` 控制。队列满时 `publish` 等待，形成背压，不会无限创建任务。
- `dispatch_concurrency` 个 worker 并行消费不同事件；同一个事件的多个处理器按 `priority` 从高到低串行执行，避免同一事件内的状态竞争和顺序不确定。
- 处理器抛出的异常被隔离并交给 `on_error`，不会终止 worker。
- WebSocket 主循环与心跳在同一个连接内并发：接收循环处理下行事件，心跳任务按周期发送 `op=1` 并等待 `op=11`。

### 去重

`Deduplicator` 使用 TTL + 最大条目数限制：

- 消息事件优先使用 `message_scene.ext.msg_idx`；
- 其次使用信封 `id`；
- 最后使用事件序号。

实时下行事件与断线 Resume 补发的事件走同一个去重器，因此同一条事件只处理一次。

## 生命周期

```python
bot = Bot(config)
await bot.start()                 # 启动事件总线 + WebSocket
await bot.stop()                  # 停止传输，等待队列排空
await bot.aclose()                # 关闭 HTTP 连接与 token 缓存
```

`Bot.run()` / `run_forever()` 会自动执行 `start` 与 `aclose`。`Bot.stop()` 可重复调用。

## 解耦与扩展点

- **新增 OpenAPI 分组**：继承 `BaseAPI`，只依赖 `APIClient`，在 `Bot` 中注入即可；不需要修改网关或事件层。
- **新增事件模型**：在 `models` 中定义 `Event` 子类，实现 `from_dict`，注册到 `EVENT_REGISTRY`；未注册事件会保留为 `UnknownEvent`。
- **自定义传输**：`EventBus.publish` 只要求一个 `Event`，任何事件来源都可以接入，包括消息队列或其他长连接。
- **替换存储/缓存**：`TokenManager`、`Deduplicator`、`ReplySequencer` 都是独立类，可单独替换。
- **频道（Guild）扩展**：新增 `api/guilds.py`、`api/channels.py` 与对应事件模型即可，现有群聊/单聊路径不受影响。

## 设计取舍

| 决策 | 原因 | 代价 |
|---|---|---|
| 事件按 worker 池并发、单事件内串行 | 保证同一事件处理器顺序，避免共享状态竞争 | 单个慢处理器会延迟同事件的其他处理器 |
| 有界队列 + 背压 | 防止流量突增时内存无限增长 | 队列满时接收循环会等待，延迟上升 |
| 主动消息默认启用单关系限流 | 贴近平台 20 条/分钟的单用户/单群限制 | 高频主动推送会阻塞；可关闭 |
| 富媒体分片并发由服务端配置控制 | 遵循 `upload_config.concurrency` | 上传速度受服务端下发值限制 |
| 不内置持久化 | 组件库不假设数据库或缓存 | 业务需自行持久化群配置、审计日志等 |
