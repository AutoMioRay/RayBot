# WebSocket 接入与网关

## 事件订阅位（Intents）

| 位 | 常量 | 主要事件 |
|---|---|---|
| `1 << 24` | `Intents.GROUP_MEMBER_EVENT` | `GROUP_MEMBER_ADD`、`GROUP_MEMBER_REMOVE`、`GROUP_JOIN_REQUEST` |
| `1 << 25` | `Intents.GROUP_AND_C2C_EVENT` | 单聊消息、群消息、机器人入群/退群、好友与消息开关事件 |
| `1 << 26` | `Intents.INTERACTION` | `INTERACTION_CREATE` |
| `1 << 27` | `Intents.MESSAGE_AUDIT` | 消息审核结果 |
| 其他 | 频道相关 | 本次未实现频道模型 |

默认订阅 `GROUP_AND_C2C_EVENT | GROUP_MEMBER_EVENT | INTERACTION`。没有权限的 Intent 会导致 WebSocket 鉴权失败并关闭连接。

## WebSocket 生命周期

### 1. 发现网关

```http
GET /gateway/bot
Authorization: QQBot {access_token}
```

返回示例：

```json
{
  "url": "wss://api.bot.qq.com/websocket",
  "shards": 1,
  "session_start_limit": {
    "total": 1000,
    "remaining": 1000,
    "reset_after": 86400000,
    "max_concurrency": 1
  }
}
```

`GatewayAPI.get()` 默认先请求 `/gateway/bot`；若返回 404 或空 `url`，回退到 `/gateway`。可用 `GatewayConfig.endpoint` 覆盖。

网关发现接口有独立的频率限制（实测约 40023001「接口调用超过频率限制」）。`ShardManager` 只获取一次网关信息并传给各分片客户端；`GatewayClient` 在整个连接生命周期内复用同一个 WSS 地址，重连和 Resume 不再重复请求 `/gateway/bot`。

### 2. Hello

连接建立后，平台先下发：

```json
{"op": 10, "d": {"heartbeat_interval": 45000}}
```

### 3. Identify

```json
{
  "op": 2,
  "d": {
    "token": "QQBot ACCESS_TOKEN",
    "intents": 117440512,
    "shard": [0, 1],
    "properties": {
      "$os": "python",
      "$browser": "RayBot",
      "$device": "RayBot"
    }
  }
}
```

鉴权成功后收到 `op=0, t=READY`，其中包含 `session_id`。库会：

- 保存 `session_id`；
- 重置重连计数；
- 将 `READY` 作为 `ReadyEvent` 发布到事件总线。

### 4. 心跳

每隔 `heartbeat_interval` 毫秒发送：

```json
{"op": 1, "d": 当前最新事件序号或 null}
```

收到 `op=11` 表示 ACK。若在 `interval × heartbeat_timeout_factor` 内没有收到 ACK，客户端主动关闭连接并重连，避免半死连接。

### 5. Resume

连接断开后，若仍有 `session_id` 与 `seq`，优先发送：

```json
{
  "op": 6,
  "d": {
    "token": "QQBot ACCESS_TOKEN",
    "session_id": "保存的 session_id",
    "seq": 1337
  }
}
```

平台补发遗漏事件后下发 `t=RESUMED`。以下情况会清空会话并重新 Identify：

- 收到 `op=9`（Invalid Session）；
- 关闭码 `4006`、`4007`、`4900~4913`。

### 6. 关闭码处理

| 关闭码 | 行为 |
|---|---|
| `4001`、`4002`、`4010~4014`、`4914`、`4915` | 致命错误，抛出 `GatewayError`，不重连 |
| `4008`、`4009` | 允许 Resume |
| `4006`、`4007`、`4900~4913` | 重新 Identify |
| 其他 | 若存在会话则 Resume，否则 Identify |

重连使用指数退避加随机抖动，默认无限重试。设置 `reconnect_max_attempts` 可限制连续失败次数。

### 7. 分片

- `shard_count` 显式指定分片数，优先级最高。
- `auto_shard=True` 使用平台返回的 `shards`。
- 否则单连接，使用 `shard` 配置（默认 `[0, 1]`）。

每个分片独立连接、独立心跳与 Resume。多分片时使用 `session_start_limit.max_concurrency` 限制同时建立连接的并发度，收到 READY/RESUMED 后释放连接槽位。平台按频道 ID 哈希分片，业务侧不需要自行计算哈希。

## 关于已封藏的 Webhook

Webhook 事件通道已在 0.2.0 整体封藏至 [archive/webhook/](../archive/webhook/README.md)，当前包仅支持 WebSocket 传输。

封藏的主要原因是协议层的**签名预言机风险**：QQ Webhook 的 `op=13` 回调地址验证端点与事件验签共用同一把 Ed25519 密钥，公网暴露验证端点时攻击者可对任意 `plain_token` 取得签名并伪造事件；该风险无法在不引入入站 IP 白名单、TLS 反代、限流等额外部署配套的前提下根除。此外 WebSocket 在平台侧即完成认证，不需要暴露任何入站端口。

封藏内容清单、完整风险说明与恢复步骤见 [archive/webhook/README.md](../archive/webhook/README.md)；安全模型见 [SECURITY.md](../SECURITY.md)。

## 常见问题

| 现象 | 排查方向 |
|---|---|
| 连接后立即关闭，日志显示 intents | 机器人没有该 Intent 权限；减少订阅位 |
| `op=9 Invalid Session` 反复出现 | token 失效、会话过期或 Resume 参数错误；库会自动 Identify |
| 事件重复处理 | 检查是否自行创建了两个 `Bot` 实例；同一实例共享同一个去重器 |
| 心跳 ACK 超时 | 网络或代理问题；库会关闭并重连 |
| 重连时出现 `40023001` | 旧版本会重复请求 `/gateway/bot`；当前版本已缓存网关地址，升级即可 |
