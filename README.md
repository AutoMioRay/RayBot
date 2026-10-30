# RayBot

> 开源免费（MIT License），非官方项目，与腾讯无关联。当前版本 `0.1.0`。

RayBot 是一个基于 `asyncio`、`httpx` 与 `websockets` 从零实现的 QQ 机器人组件库，覆盖单聊、群聊、群聊管理、富媒体与互动事件，通过 WebSocket 接收事件，不依赖任何现成的 QQ 机器人 SDK。

- Python：`>=3.13.12`
- 事件通道：WebSocket（心跳、Resume、重连、分片）
- 接口范围：单聊消息、群聊消息、撤回、流式消息、富媒体上传、Markdown、内嵌键盘、群信息/成员/禁言/黑名单/入群审批/自动审批策略、机器人资料与分享链接、全局菜单与指令面板、互动事件响应
- 暂不包含：QQ 频道（Guild / 子频道 / 身份组）；包结构已预留 API 分组与事件注册表，可独立扩展

## 特性

- **消息全场景**：单聊与群聊的文本、Markdown、富媒体、引用、撤回、流式输出；被动回复自动携带 `msg_id` 与递增 `msg_seq`。
- **群管理完整**：群信息、成员查询与批量移除、禁言、黑名单、入群审批与自动审批策略。
- **互动组件**：内嵌键盘、按钮回调、全局菜单与指令面板，3 秒内可完成互动响应。
- **连接可靠**：心跳 ACK 检测、Resume、指数退避重连、分片并发控制；access token 单飞刷新与到期前预刷新。
- **安全优先**：凭据仅驻留内存、日志与异常栈不泄露 token、网关 URL 白名单校验、心跳间隔钳制、上传地址强制 HTTPS。
- **无 SDK 依赖**：协议与 API 直接实现，便于审计与定制。

## 安装

```bash
# 使用 uv（推荐）
uv sync

# 或作为本地包安装
pip install -e .

# PyPI 发布后（当前尚未发布）
pip install raybot
```

## 快速开始：WebSocket 回声机器人

```python
import logging

from RayBot import Bot, BotConfig, C2CMessage, GroupMessage


def main() -> None:
    config = BotConfig.from_env()  # 读取 QQBOT_APP_ID / QQBOT_CLIENT_SECRET
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

`Bot.reply` 会自动判断单聊/群聊、携带被动回复所需的 `msg_id`，并为同一条消息生成递增的 `msg_seq`。

## 导入方式

```python
# 公共门面：稳定的用户 API
from RayBot import Bot, BotConfig, C2CMessage, GroupMessage

# 精确导入：需要某个具体模块时
from RayBot.core.gateway import ShardManager
from RayBot.core.config import GatewayConfig
```

## 文档

- **使用手册**：[docs/index.md](docs/index.md)
  - 功能解析与最小示例：[API 参考](docs/api-reference.md)、[事件与处理器](docs/events.md)、[群聊管理方案](docs/group-management.md)、[富媒体与素材](docs/media.md)
  - 配置参数：[配置项](docs/configuration.md)
  - 错误速查：[错误与重试](docs/errors.md)
  - 测试方案：[测试与验证](docs/testing.md)
  - 架构与并发模型：[architecture](docs/architecture.md)
- **测试报告**：[功能测试报告](reports/功能测试报告.md) · [安全测试报告](reports/安全测试报告.md)
- **安全策略**：[SECURITY.md](SECURITY.md)

## 可运行示例

```bash
export QQBOT_APP_ID=...
export QQBOT_CLIENT_SECRET=...

uv run python examples/echo_bot.py
uv run python examples/smoke_test.py --gateway   # 只读联调：token/资料/网关/WS READY

uv run python examples/group_management.py info GROUP_OPENID
uv run python examples/group_management.py members GROUP_OPENID
uv run python examples/group_management.py mute GROUP_OPENID MEMBER_OPENID 30
```

## 平台约束（摘要）

- 被动回复：单聊 `msg_id` 有效期 60 分钟、每条消息最多回复 4 次；群聊 5 分钟、最多 5 次。
- 主动消息：受 Bot 维度、单关系维度与每日上限约束；用户或群管理员可关闭主动推送。
- 群管理：多数写操作要求机器人是群管理员；无权限时平台返回明确错误码。
- 富媒体：单聊与群聊上传桶隔离；`file_info` 有时效，过期需重新上传。

完整说明见 [使用手册](docs/index.md)。

## 安全模型（摘要）

- WebSocket 建连即完成平台认证，无需暴露任何入站端口；Webhook 通道因协议级签名预言机风险未在此版本提供。
- 凭据与 token 只保存在进程内存，不落盘、不写日志；怀疑泄露时请立即轮换。
- OpenAPI 与 WebSocket 默认校验 TLS 证书；网关地址受域名白名单约束。
- 本库不绕过平台的权限、审核、去重与频率限制。

漏洞披露请遵循 [SECURITY.md](SECURITY.md)。

## 反馈与共建

我们非常希望听到使用者的真实声音，欢迎通过 [Issues](https://github.com/AutoMioRay/RayBot/issues) 反馈：

- **使用体验**：上手是否顺畅、文档是否清晰、示例是否够用；
- **代码缺陷**：附最小复现、版本号、Python 与操作系统环境；
- **功能需求**：说明业务场景与期望行为，便于评估优先级；
- **安全漏洞**：**请勿公开提交 issue**，按 [SECURITY.md](SECURITY.md) 的私密渠道报告；
- **后续更新想法**：你希望新增的接口、事件或部署方式。

提交代码前请先开 issue 讨论，并阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 分支与发布

- `main` 是唯一的长期分支，承载所有发布版本；每个版本在 `main` 上打 `vX.Y.Z` 标签。
- 功能、修复与文档改动通过 `feature/*`、`fix/*`、`docs/*` 短分支提交 PR 合入。
- 发布由标签触发，自动完成全量测试、扫描、构建与制品归档。

## 许可证

MIT License，Copyright (c) 2026 MioRay。详见 [LICENSE](LICENSE) 与 [NOTICE](NOTICE)。软件按“现状”提供，不附带担保。
