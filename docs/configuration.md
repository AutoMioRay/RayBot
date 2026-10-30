# 配置项

所有配置对象都是 `frozen=True` 的 dataclass。修改嵌套配置时使用 `dataclasses.replace`，不要直接赋值。

```python
from dataclasses import replace
from qqbot_toolkit import BotConfig, GatewayConfig, HTTPConfig

config = BotConfig(
    app_id="APPID",
    client_secret="CLIENTSECRET",
    http=replace(HTTPConfig(), timeout=20.0, max_retries=3),
    gateway=replace(GatewayConfig(), auto_shard=True),
)
```

## BotConfig

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `app_id` | `str` | 是 | 开放平台 AppID |
| `client_secret` | `str` | 是 | 开放平台 ClientSecret，用于获取 `access_token` |
| `http` | `HTTPConfig` | 否 | HTTP 传输、重试与限流配置 |
| `gateway` | `GatewayConfig` | 否 | WebSocket 与事件分发配置 |

### 凭据校验

`BotConfig` 在构造时校验 `app_id` 与 `client_secret`，任一条件不满足会抛出 `ConfigurationError`：

- 不能为空；
- 长度受限：`app_id` 最长 64 字符，`client_secret` 最长 256 字符；
- 不允许以空白字符开头或结尾；
- 不允许包含控制字符（含换行），避免凭据被原样写入 JSON 请求体与日志。

`BotConfig.from_env()` 从环境变量读取凭据后同样经过该校验，因此环境变量值若带前后空白或换行也会在启动时被拒绝。

### BotConfig.from_env(prefix="QQBOT_")

读取：

- `QQBOT_APP_ID`
- `QQBOT_CLIENT_SECRET`
- `QQBOT_BASE_URL`（可选）

### BotConfig.with_overrides(**changes)

返回替换后的副本。嵌套配置需要整体替换：

```python
config = config.with_overrides(gateway=replace(config.gateway, auto_shard=True))
```

## HTTPConfig

| 字段 | 默认值 | 说明 |
|---|---|---|
| `base_url` | `https://api.bot.qq.com` | OpenAPI 根地址；会去掉末尾 `/` |
| `timeout` | `30.0` | 单次请求总超时（秒） |
| `connect_timeout` | `10.0` | 建连超时（秒） |
| `max_connections` | `200` | 连接池最大连接数 |
| `max_keepalive_connections` | `50` | 连接池保活连接数 |
| `max_retries` | `2` | 瞬时错误最大重试次数 |
| `retry_base_delay` | `0.4` | 指数退避基数（秒） |
| `retry_max_delay` | `8.0` | 指数退避上限（秒） |
| `token_refresh_margin` | `60.0` | 提前刷新 token 的秒数；不会超过 TTL 的一半 |
| `user_agent` | `qqbot-toolkit/0.2.0` | HTTP User-Agent（跟随包版本） |
| `enforce_rate_limits` | `True` | 是否启用路由级令牌桶 |
| `enforce_relation_limits` | `True` | 是否对主动消息启用单用户/单群限流 |
| `http2` | `False` | 是否启用 HTTP/2；需要安装 `h2` |
| `trust_env` | `True` | 是否读取系统代理环境变量 |
| `allow_insecure_http` | `False` | 是否允许非回环地址使用 `http://`；默认强制 HTTPS |
| `token_background_refresh` | `True` | 是否在 token TTL 约 80% 处后台预刷新 |
| `token_refresh_jitter` | `0.1` | 后台刷新抖动比例（0~1），避免多进程同时刷新 |

### 重试策略

`APIClient` 对以下情况重试：

- `httpx.RequestError`（连接失败、超时等）；
- HTTP `429`、`500`、`502`、`503`、`504`；
- `401`：清空 token 后重试一次，不占用普通重试次数。

`429` 优先使用响应头 `Retry-After`（秒数或 HTTP 日期）。其余情况使用指数退避加随机抖动。

### 路由限流

默认规则（官方文档中的接口频率限制）：

| 路由 | 速率 | 突发 |
|---|---|---|
| `message.send.c2c` / `message.send.group` | 100/s | 100 |
| `message.stream.c2c` | 50/s | 50 |
| `message.recall.c2c` / `message.recall.group` | 10/s | 10 |
| `media.upload.c2c` / `media.upload.group` | 50/s | 50 |
| `media.prepare` / `media.part_finish` | 10/s | 10 |
| `group.info` / `group.bot_state` / `group.member.get` | 0.5/s（30/min） | 5 |
| `group.member.list` | 1/s（60/min） | 10 |
| `group.join.approve` / `group.mute.set` / `group.blacklist.set` | 1/s（60/min） | 10 |
| `group.strategy.*` | 1/s（60/min） | 10 |
| `interaction.respond` | 50/s | 50 |
| `bot.menu.read` | 0.5/s（30/min） | 5 |
| `bot.menu.write` | 5/min | 2 |
| `bot.panel.read` | 0.5/s（30/min） | 5 |
| `bot.panel.write` | 10/min | 2 |
| `bot.panel.target` | 1/s（60/min） | 10 |

主动消息另外受单关系桶限制：

| 桶 | 速率 | 突发 |
|---|---|---|
| `message.active.c2c` | 20/min | 20 |
| `message.active.group` | 20/min | 20 |

被动回复（携带 `msg_id` 或 `event_id`）只受路由桶限制。关闭限流：

```python
http = replace(HTTPConfig(), enforce_rate_limits=False, enforce_relation_limits=False)
```

## GatewayConfig

| 字段 | 默认值 | 说明 |
|---|---|---|
| `endpoint` | `None` | 覆盖网关发现路径；默认先试 `/gateway/bot`，404 时回退 `/gateway` |
| `intents` | `GROUP_AND_C2C_EVENT \| GROUP_MEMBER_EVENT \| INTERACTION` | 事件订阅位掩码 |
| `shard` | `(0, 1)` | 单连接模式下的分片参数 |
| `shard_count` | `None` | 显式分片数，优先级高于 `auto_shard` |
| `auto_shard` | `False` | 使用平台建议的分片数 |
| `dispatch_concurrency` | `64` | 事件 worker 数 |
| `dispatch_queue_size` | `2048` | 事件队列长度 |
| `dedup_ttl` | `600.0` | 去重条目保留秒数 |
| `dedup_max_size` | `20000` | 去重表最大条目数 |
| `reconnect_initial_delay` | `1.0` | 首次重连延迟（秒） |
| `reconnect_max_delay` | `60.0` | 重连延迟上限（秒） |
| `reconnect_max_attempts` | `None` | 连续失败上限；`None` 表示无限重试 |
| `heartbeat_timeout_factor` | `1.5` | 等待心跳 ACK 的周期倍数 |
| `open_timeout` | `10.0` | WebSocket 建连超时（秒） |
| `close_timeout` | `5.0` | 关闭握手超时（秒） |
| `max_message_size` | `16 MiB` | 单条下行消息最大字节数 |
| `proxy` | `None` | `None` 使用 websockets 默认；可设为字符串或 `False` |
| `properties` | 见下 | Identify 中的设备信息 |

默认 `properties`：

```python
{"$os": "python", "$browser": "qqbot-toolkit", "$device": "qqbot-toolkit"}
```

`intents` 可以传 `Intents` 组合：

```python
from qqbot_toolkit import GatewayConfig, Intents

gateway = GatewayConfig(
    intents=Intents.GROUP_AND_C2C_EVENT | Intents.INTERACTION
)
```

## HTTP 传输安全

- `base_url` 默认 `https://api.bot.qq.com`；非回环地址使用 `http://` 会直接抛出 `ConfigurationError`。只有明确设置 `allow_insecure_http=True` 才允许，且应仅用于可信本地环境。
- `base_url` 不允许包含用户名/密码。
- `token_background_refresh=True` 时，`TokenManager` 会在 token 有效期约 80% 处后台刷新，并在失败后 30 秒重试；`aclose()` 会取消后台任务。刷新计数可通过 `bot.tokens.stats` 查看。
- `trust_env=True` 会读取系统代理环境变量；严格环境可设为 `False`。


## 环境变量示例

```bash
export QQBOT_APP_ID=102000000
export QQBOT_CLIENT_SECRET=xxxxxxxx
export QQBOT_BASE_URL=https://api.bot.qq.com
```

```python
config = BotConfig.from_env()
```
