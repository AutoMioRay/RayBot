# Gitee Go 流水线（镜像用）

本目录是 **Gitee Go** 的流水线定义，仅在 Gitee 仓库的 Gitee Go 服务中生效：

| 文件 | 用途 |
|---|---|
| `PRPipeline.yml` | PR 门禁（所有源分支） |
| `MasterPipeline.yml` | push → main |
| `BranchPipeline.yml` | push → develop |
| `ReleasePipeline.yml` | tag `v*` + 人工审核 |
| `NightlyPipeline.yml` | 定时全量（Fuzz 10000） |
| `LiveSmokePipeline.yml` | 手动真实凭据冒烟 |

注意：

- **GitHub Actions 是主 CI**，定义在 `.github/workflows/`；两套流水线调用同一个
  `tools/ci/gate.py`，门禁逻辑不会漂移。
- Gitee Go 官方 `build@python` 插件只支持 Python 3.6–3.9，本项目要求 ≥3.13.12，
  因此这些流水线统一使用自有主机组（`shell@agent`，`hostGroupID: qqbot-ci`），
  详见 `reports/CI工作流设计.md`。
- 云端不跑长时 L4 稳定性测试：使用 `python tools/soak_test.py --minutes 1440`
  在本地执行。
