# qqbot-toolkit 文档

`qqbot-toolkit` 是一个开源免费的、基于 asyncio 的 QQ 机器人组件库，非官方项目，与腾讯无关联。

## 文档地图

| 文档 | 适合谁 | 内容 |
|---|---|---|
| [README](../README.md) | 第一次接触项目 | 定位、安装、快速开始、安全声明、许可证 |
| [架构与并发模型](architecture.md) | 想了解内部设计 | 分层、HTTP/事件路径、背压、扩展点 |
| [配置项](configuration.md) | 部署与调优 | HTTP/Gateway 全部字段、凭据校验与安全配置 |
| [事件与处理器](events.md) | 业务开发 | 事件模型、处理器、去重、互动事件 |
| [WebSocket 接入与网关](gateway.md) | 接入与运维 | 心跳、Resume、重连、分片、关闭码 |
| [API 参考](api-reference.md) | 日常开发 | 按基本配置、单聊、群聊、群管理组织 |
| [群聊管理方案](group-management.md) | 群管理开发 | 权限、审批、禁言、黑名单、策略 |
| [富媒体与素材](media.md) | 图片/视频/文件 | 上传方式、分片、素材图片 |
| [错误与重试](errors.md) | 排障 | 异常层级、错误码、重试与限流 |

## 推荐阅读路径

1. 新手：README 快速开始 → 配置项 → 事件与处理器。
2. 做消息机器人：API 参考的单聊消息/群聊消息 → 富媒体与素材 → 互动按钮与菜单。
3. 做群管理：群聊管理方案 → API 参考的群聊管理 → 错误与重试。
4. 做部署：WebSocket 接入与网关 → 配置项 → SECURITY.md。

## 安全

当前版本仅支持 WebSocket 传输：平台在建立 WebSocket 连接时即完成认证，不需要暴露任何入站端口。Webhook 事件通道已因协议层的签名预言机风险封藏至 [archive/webhook/](../archive/webhook/README.md)。

漏洞披露流程见 [SECURITY.md](../SECURITY.md)。

## 许可证

MIT License，Copyright (c) 2026 MioRay。详见 [LICENSE](../LICENSE) 与 [NOTICE](../NOTICE)。
