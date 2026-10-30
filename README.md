# qqbot-toolkit

> 开源免费，MIT License。非官方项目，与腾讯无关联。当前版本：`0.2.0`（Beta）。

基于 `asyncio`、`httpx` 与 `websockets` 从零实现的 QQ 机器人组件库。覆盖 QQ 单聊、群聊、群聊管理、富媒体与互动事件，通过 WebSocket 接收事件，不依赖任何 QQ 机器人成型 SDK。

> 说明：Webhook 事件通道已封藏至 [archive/webhook/](archive/webhook/README.md)，当前版本仅支持 WebSocket 事件通道。

- Python 版本：`>=3.13.12`
- 事件通道：WebSocket（心跳、Resume、重连、分片）
- 接口范围：单聊消息、群聊消息、撤回、流式消息、富媒体上传、Markdown、内嵌键盘、群信息/成员/禁言/黑名单/入群审批/自动审批策略、机器人资料与分享链接、全局菜单与指令面板、互动事件响应
- 当前版本不包含：QQ 频道（Guild / 子频道 / 频道身份组）；包结构预留了 API 分组和事件注册表，可独立扩展

文档入口：[docs/index.md](docs/index.md)

- [架构与并发模型](docs/architecture.md)
- [配置项](docs/configuration.md)
- [事件与处理器](docs/events.md)
- [WebSocket 接入与网关](docs/gateway.md)
- [API 参考](docs/api-reference.md)：按基本配置、单聊消息、群聊消息、群聊管理组织
- [群聊管理方案](docs/group-management.md)
- [富媒体与素材](docs/media.md)
- [错误与重试](docs/errors.md)

## 安装

```bash
uv sync
```

或作为本地包安装：

```bash
pip install -e .
```

PyPI 发布后可直接安装（当前仓库尚未发布到 PyPI）：

```bash
pip install qqbot-toolkit
```

## 快速开始：WebSocket 回声机器人

```python
import logging

from qqbot_toolkit import Bot, BotConfig, C2CMessage, GroupMessage


def main() -> None:
    config = BotConfig.from_env()  # QQBOT_APP_ID / QQBOT_CLIENT_SECRET
    bot = Bot(config)

    @bot.on_c2c_message()
    async def echo_c2c(event: C2CMessage) -> None:
        await bot.reply(event, f"Echo: {event.content}")

    @bot.on_group_at_message()
    async def echo_group(event: GroupMessage) -> None:
        await bot.reply(event, f"Echo: {event.content}")

    bot.run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
```

`Bot.reply` 会自动完成三件事：

1. 从事件类型判断单聊或群聊；
2. 携带被动回复所需的 `msg_id`；
3. 为同一条消息生成递增的 `msg_seq`，避免平台按「相同 msg_id + msg_seq」去重导致第二次回复失败。

## 可运行示例

```bash
export QQBOT_APP_ID=...
export QQBOT_CLIENT_SECRET=...

uv run python examples/echo_bot.py
uv run python examples/smoke_test.py --gateway   # 只读联调：token/资料/网关/WS READY

# 群管理命令示例
uv run python examples/group_management.py info GROUP_OPENID
uv run python examples/group_management.py members GROUP_OPENID
uv run python examples/group_management.py mute GROUP_OPENID MEMBER_OPENID 30
```

## 配置速览

```python
from dataclasses import replace
from qqbot_toolkit import BotConfig, HTTPConfig

config = BotConfig(
    app_id="你的 AppID",
    client_secret="你的 ClientSecret",
    http=replace(HTTPConfig(), timeout=20.0, max_retries=3),
)
```

完整字段见 [配置项](docs/configuration.md)。凭据也可以通过环境变量提供：

| 变量 | 必填 | 说明 |
|---|---|---|
| `QQBOT_APP_ID` | 是 | 开放平台 AppID |
| `QQBOT_CLIENT_SECRET` | 是 | 开放平台 ClientSecret；旧文档中的 AppSecret 使用同一入口，具体以管理端当前字段名为准 |
| `QQBOT_BASE_URL` | 否 | 覆盖 OpenAPI 根地址，默认 `https://api.bot.qq.com` |

## 目录结构

```text
src/qqbot_toolkit/
├── api/          # OpenAPI 分组：消息、群管理、富媒体、机器人、网关、互动
├── events/       # payload、事件总线、去重
├── gateway/      # WebSocket 客户端、分片管理
├── http/         # httpx 客户端、重试、令牌桶限流
├── models/       # 入站数据模型与出站 payload
├── auth.py       # access_token 获取与缓存
├── config.py     # 不可变配置对象
├── constants.py  # Intents、OpCode、消息类型等协议常量
├── errors.py     # 异常层级
└── bot.py        # Bot 门面、装饰器、回复序号管理
```

## 测试与静态检查

```bash
uv run pytest
uv run ruff check src tests examples

# 与 CI 完全一致的门禁（构建 → 测试 → 扫描 → 发布演练）
python tools/ci/gate.py all
```

CI 主平台是 **GitHub Actions**（`.github/workflows/`）：`ci`（构建-测试-扫描，
含 Windows 交叉回归与 PR 依赖审查）、`codeql`（安全静态分析）、`release`
（v* 标签、OIDC 发布、构建溯源、GitHub Release）、`nightly`（Fuzz 10000 +
全历史密钥扫描）与手动 `live-smoke`。Gitee Go 镜像定义保留在 `.workflow/`。
两套流水线共用 `tools/ci/gate.py`；设计与分支策略见
[reports/CI工作流设计.md](reports/CI工作流设计.md)，安全流程审核见
[reports/安全流程审核报告.md](reports/安全流程审核报告.md)。

云端配额有限，**长时 L4 稳定性测试只在本地跑**：

```bash
python tools/soak_test.py --minutes 60     # 本地长跑（RSS/句柄/asyncio 任务采样）
```

## 平台约束

以下限制来自 QQ 官方文档，库只负责正确传递参数和暴露错误码，不会绕过平台限制：

- 被动回复：单聊 `msg_id` 有效期 60 分钟、每条消息最多回复 4 次；群聊 5 分钟、最多 5 次。
- 主动消息：单聊与群聊均受 Bot 维度、单关系维度和每日上限约束；用户或群管理员可关闭主动推送。
- 群管理：大部分写操作要求机器人是群管理员；成员列表、批量移除、黑名单等接口目前标注为内邀能力，无权限时可能返回 `11253` 或 `40012010`。
- 富媒体：单聊与群聊的上传桶相互隔离；`file_info` 有时效，过期需重新上传。
- 同一 `msg_id` 可能重复推送；库默认按 `message_scene.ext.msg_idx` 或事件 ID 去重。

## 安全模型与已知风险

- **Webhook 已封藏（协议级风险）**：Webhook 的 `op=13` 验证端点与事件签名共用同一把 Ed25519 密钥，公网暴露时构成签名预言机，攻击者可借此伪造事件。该风险无法在不引入额外部署配套的前提下根除，因此 Webhook 传输已整体封藏至 [archive/webhook/](archive/webhook/README.md)，当前仅支持 WebSocket。
- **TLS**：OpenAPI 与 WebSocket 默认校验证书。
- **凭据**：`client_secret` 与 access token 只保存在进程内存，不落盘、不写日志；请使用环境变量或密钥管理系统，怀疑泄露时立即轮换。
- **Bearer token**：进程被攻破时，token 在有效期内可被直接使用；请限制主机访问权限并监控异常调用。
- **平台权限与频控**：本库不绕过 QQ 平台的权限、审核、去重和频率限制；无权限时请按平台要求申请或授予管理员。
- **无担保**：本项目按 MIT License“按现状”提供，不附带任何明示或暗示担保。生产部署前请自行完成安全评估、权限最小化和审计。

漏洞披露与更多说明见 [SECURITY.md](SECURITY.md)，WebSocket 接入见 [WebSocket 接入与网关](docs/gateway.md)。

## 贡献、安全与变更

- [贡献指南](CONTRIBUTING.md)
- [安全策略](SECURITY.md)
- [变更记录](CHANGELOG.md)
- [行为准则](CODE_OF_CONDUCT.md)

## 许可证

MIT License，Copyright (c) 2026 MioRay。详见 [LICENSE](LICENSE) 与 [NOTICE](NOTICE)。

允许商业使用、修改、再分发和私有使用，但需保留版权与许可声明；软件按现状提供，不附带担保。
