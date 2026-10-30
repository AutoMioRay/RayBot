# Webhook 模块封藏说明

封藏日期：2026-10-30

## 背景

当前项目暂时只使用 **WebSocket** 事件通道。出于收缩攻击面与降低维护成本的考虑，
Webhook 相关代码已从主包 `RayBot` 中整体卸载，**原样封藏**于本目录，
未做任何功能性改写，未来需要时可按下方步骤恢复。

被封藏的主要理由（详见 `SECURITY.md` 与封藏时的安全测试报告）：

- `op=13` 回调验证端点对任意 `plain_token` 返回 Ed25519 签名，而事件验签使用
  同一把密钥——公网暴露时构成**签名预言机**，攻击者可伪造事件（协议级风险，
  无法在不引入额外基础设施的前提下根除）；
- Webhook 需要额外暴露公网 HTTP 端口（80/443/8080/8443），并依赖反向代理终止
  TLS、入站 IP 白名单、按 IP 限流等一系列部署侧配套，运维负担大；
- WebSocket 通道在平台侧即完成认证，不暴露任何入站端口。

## 封藏内容

| 文件 | 原位置 | 说明 |
|---|---|---|
| `webhook.py` | `RayBot/core/gateway/webhook.py` | aiohttp 回调服务器（验签、op=13、ACK、入站限流、IP 白名单） |
| `signature.py` | `RayBot/core/gateway/signature.py` | Ed25519 签名/验签与密钥派生 |
| `test_webhook.py` | `tests/test_webhook.py` | Webhook 服务器测试 |
| `test_signature.py` | `tests/test_signature.py` | 签名测试 |
| `webhook_bot_example.py` | `examples/webhook_bot.py` | Webhook 示例机器人 |

## 随代码一并移除的依赖

- `aiohttp`（仅 webhook.py 使用）
- `cryptography`（仅 signature.py 使用；如恢复需重新加入）

两者已从 `pyproject.toml` 的 `[project.dependencies]` 中移除。

## 同步修改的活跃代码

- `config.py`：移除 `WebhookConfig` 及 `BotConfig.webhook` 字段
- `errors.py`：移除 `SignatureVerificationError`
- `bot.py`：移除 `webhook` 参数、`webhook` 属性与 `WebhookServer` 装配
- `gateway/__init__.py`、`__init__.py`：移除导出符号
- 文档（README、docs/*、SECURITY.md、CHANGELOG.md）同步删去 Webhook 章节

## 如何恢复（如未来需要 Webhook）

> 0.2.0 起封藏代码保持历史原样，其 import 仍为旧包名 `qqbot_toolkit`；
> 恢复时请将 `from qqbot_toolkit...` 改为 `from RayBot.core...`（例如
> `from qqbot_toolkit.gateway.signature import ...` →
> `from RayBot.core.gateway.signature import ...`）。

1. 将 `webhook.py`、`signature.py` 复制回 `RayBot/core/gateway/`；
2. 在 `config.py` 中恢复 `WebhookConfig` 与 `BotConfig.webhook` 字段
   （见 `archive` 中的 `config.py.webhook.patch` 节选，或从版本历史对照恢复）；
3. 在 `errors.py` 中恢复 `SignatureVerificationError`；
4. 在 `bot.py` 中恢复 `WebhookServer` 装配与 `start(webhook=...)` 分支；
5. 在两个 `__init__.py` 中恢复导出；
6. `pyproject.toml` 重新加入 `aiohttp>=3.14.5`、`cryptography>=50.0.2`；
7. 将测试文件复制回 `tests/` 并运行 `pytest` 验证。

**恢复前必须阅读**：`SECURITY.md` 中关于 Webhook 签名预言机的说明。生产部署
必须配置 `allowed_ips` 入站白名单、回调配置完成后关闭 `op=13`，并始终启用
事件签名校验；或者干脆继续使用 WebSocket。
