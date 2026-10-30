# 错误与重试

## 异常层级

```text
QQBotError
├── ConfigurationError       配置缺失或非法
├── APIError                 OpenAPI 调用失败
│   └── AuthenticationError  获取 token 或鉴权失败
├── GatewayError             WebSocket 致命错误或重连耗尽
└── PayloadError             网关 payload 无法解析
```

所有异常都可以从 `RayBot.core.errors` 导入，主要异常也从包根导出。

## APIError

```python
class APIError(QQBotError):
    message: str
    status: int | None
    err_code: int | str | None
    trace_id: str | None
    method: str | None
    path: str | None
    body: Any
```

判断属性：

| 属性 | 条件 |
|---|---|
| `is_rate_limited` | HTTP 429，或 `err_code` 属于限频类（如 `1100100`、`20028`、`40034100`、`40054005`） |
| `is_auth_error` | HTTP 401，或权限/token 类错误码（如 `11241`、`11243`、`11253`、`11265`、`40011030`、`40012010`） |
| `is_retryable` | HTTP 429/5xx，或 5xx 段业务错误码 |

`str(exc)` 会拼接方法、路径、HTTP 状态、`err_code` 与 `trace_id`，便于日志排查。

### 错误来源

QQ OpenAPI 有两套错误位置：

1. **HTTP 状态码**：401、429、5xx 等；
2. **HTTP body 的 `err_code`**：即使 HTTP 为 200，业务也可能失败。

`APIClient` 同时检查两者。`APIError` 的 `trace_id` 优先取响应头 `X-Tps-trace-ID`，其次取 body 的 `trace_id`。

不要依赖 `message` 文本，平台可能随时调整措辞。

## 重试策略

`APIClient` 默认 `max_retries=2`：

| 情况 | 行为 |
|---|---|
| `httpx.RequestError` | 指数退避后重试 |
| HTTP 429 | 优先使用 `Retry-After`，否则退避 |
| HTTP 500 / 502 / 503 / 504 | 退避后重试 |
| HTTP 401 | 清空 token，重新获取并重试一次 |
| HTTP 400 / 403 / 404 | 不重试 |
| 业务 `err_code` | 不自动重试（除非调用方自行处理） |

退避公式近似：

```text
delay = min(retry_max_delay, retry_base_delay * 2^attempt) + random(0, retry_base_delay)
```

关闭重试：

```python
from dataclasses import replace
from RayBot import HTTPConfig

http = replace(HTTPConfig(), max_retries=0)
```

### 非幂等请求

发送消息、创建策略等 POST 在超时后重试可能重复执行。平台的 `msg_id + msg_seq` 去重可以拦截重复消息；创建策略等接口建议业务侧使用幂等键或先查询再创建。需要严格一次语义时关闭自动重试。

## 限流错误处理

库内令牌桶会在请求前等待，通常不会主动触发 429。仍可能在以下情况遇到平台限流：

- 多实例共享同一个 AppID，各实例独立计数；
- 平台临时策略变化；
- 主动消息单用户/单群每日上限。

建议：

```python
try:
    await bot.group.send(group_openid, content="主动通知")
except APIError as exc:
    if exc.is_rate_limited:
        # 降低频率、延后重试或改用被动回复
        ...
    raise
```

## WebSocket 错误

`GatewayError` 字段：

- `close_code`：平台关闭码；
- `fatal`：是否不可恢复。

致命关闭码（不重连）：`4001`、`4002`、`4010~4014`、`4914`、`4915`。其余错误按 [WebSocket 接入与网关](gateway.md) 中的表处理。

重连耗尽时也会抛出 `GatewayError(fatal=True)`。

## 日志与追踪

- `APIError.trace_id` 与响应头 `X-Tps-trace-ID` 对应，反馈平台问题时一并提供；
- 网关日志包含分片编号、断线原因、重连延迟；
- 处理器异常由 `EventBus` 记录，并可通过 `bot.on_error` 收集；
- 日志不会输出 `access_token` 或 `client_secret`。

推荐配置：

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
```
