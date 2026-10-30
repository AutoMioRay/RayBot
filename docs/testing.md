# 测试与验证

本文面向使用者，说明 RayBot 的测试分层、如何运行测试、如何解读报告，以及维护者的长时稳定性验证方式。

## 测试分层

| 层级 | 目标 | 主要文件 | 是否需要真实凭据 |
|---|---|---|---|
| 功能测试 | 消息收发、群管理、富媒体、配置、事件总线、HTTP 重试与限流、模型解析 | `tests/test_api.py`、`tests/test_robot_api.py`、`tests/test_models.py`、`tests/test_bus.py`、`tests/test_gateway.py`、`tests/test_http_client.py`、`tests/test_token_manager.py` | 否 |
| 安全测试 | 凭证卫生、解析 Fuzz、协议分支、恶意服务器与 TLS MITM、并发与背压 | `tests/test_credentials_and_backpressure.py`、`tests/test_fuzz_parsers.py`、`tests/test_protocol_security.py`、`tests/test_hostile_server.py`、`tests/test_security_config.py` | 否 |

全部测试使用进程内假服务器与 Mock 传输，**不访问真实 QQ 平台、不需要任何密钥**；因此任何人都可以在本地或 CI 中安全运行。

## 运行方式

```bash
# 安装依赖
uv sync

# 全部测试（默认 Fuzz 2000 个样本）
uv run pytest

# 只跑某一层
uv run pytest tests/test_api.py tests/test_models.py
uv run pytest tests/test_protocol_security.py tests/test_hostile_server.py

# 调整 Fuzz 样本数（默认 2000；CI 快速门禁 500，夜间 10000）
QQBOT_FUZZ_EXAMPLES=500 uv run pytest

# 与 CI 一致的门禁：构建 + 测试 + 扫描（ruff/bandit/pip-audit/密钥/覆盖率）
python tools/ci/gate.py test --examples 500
python tools/ci/gate.py scan
```

## 自动化门禁

| 检查 | 内容 | 门禁 |
|---|---|---|
| 静态检查 | ruff（含 bandit 规则集）、格式检查 | 0 告警 |
| 安全静态 | bandit（Medium 及以上） | 0 命中 |
| 依赖漏洞 | pip-audit（本地环境） | 0 已知漏洞 |
| 密钥扫描 | 工作树 + git 历史（`tools/check_secrets.py --history`） | 0 命中 |
| 覆盖率 | 行覆盖率 | 当前 78%，门禁 75% |
| 跨平台 | Linux 与 Windows 运行测试 | 全绿 |

CI 在每次推送与 PR 上运行上述门禁（`quality`、`test-windows`），并在 PR 上执行依赖变更审查。

## 测试报告

- [功能测试报告](../reports/功能测试报告.md)：功能测试范围、用例分布、覆盖率与结论。
- [安全测试报告](../reports/安全测试报告.md)：威胁模型、L1–L5 分层结果与修复闭环情况。

## 长时稳定性验证

超过数小时的资源稳定性测试（内存、句柄、asyncio 任务数）由维护者在本机执行，测试工具与记录随开发分支提供，不随使用者版本分发：

<https://github.com/AutoMioRay/RayBot/tree/develop>

## 测试原则

- 新功能必须同时包含成功路径与错误路径测试。
- 安全相关修复必须附带可复现的回归用例。
- 不提交任何真实 AppID/Secret；测试中的凭据均为明显的占位值或注入用例。
