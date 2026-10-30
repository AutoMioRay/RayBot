# CI 流水线设计：构建 → 测试 → 扫描 → 发布（GitHub Actions 主 / Gitee Go 镜像）

- 日期：2026-10-30（第三轮：GitHub Actions 成为主 CI，Gitee Go 保留为镜像）
- 承载平台：
  - **GitHub Actions（主）**：`.github/workflows/`，见下节；
  - **Gitee Go（镜像）**：仓库根 `.workflow/*.yml`，仅在 Gitee 侧生效。
- 设计原则：**YAML 只编排，逻辑在脚本**。两套平台调用同一个 `tools/ci/gate.py`，门禁逻辑不会漂移；本地与 CI 跑同一套命令。

## 〇、GitHub Actions 工作流（主平台）

| 工作流 | 触发 | 内容 | 关键权限 |
|---|---|---|---|
| `ci.yml` → `quality` | push main/develop、PR | install → build → test(500) → scan | `contents: read` |
| `ci.yml` → `test-windows` | 同上 | Windows 交叉回归 | `contents: read` |
| `ci.yml` → `dependency-review` | 仅 PR | 依赖变更审查，high 阻断 | `contents/pull-requests: read` |
| `codeql.yml` → `analyze` | push/PR/每周一 | CodeQL `security-extended` | `security-events: write` |
| `release.yml` → `verify` → `publish` | tag `v*` | 全量测试(10000)+扫描；发布校验、PyPI OIDC、构建溯源、GitHub Release | `contents: write`、`id-token: write`、`attestations: write` |
| `nightly.yml` → `nightly-full` | 每日 02:30 CST / 手动 | Fuzz 10000 + 全量扫描 + 全历史密钥扫描 | `contents: read` |
| `live-smoke.yml` → `live-smoke` | 仅手动 | 真实凭据 token→网关→READY（environment 隔离） | `contents: read` |

GitHub 侧的所有工作流均设置顶层只读权限、`concurrency` 去重、`timeout-minutes`、
`persist-credentials: false`，且不使用 `pull_request_target`。分支保护（main/develop
必需 `quality` + `test-windows`）与仓库安全开关由 `tools/github/setup_repo.py` 配置。

以下第一至十节为 **Gitee Go 镜像** 的规范与分支策略（官方 YAML 事实核对、自有主机组等）。

## 一、Gitee Go 格式核对结果（本轮修正）

以下字段均已对照官方文档（help.gitee.com/gitee-go）核实：

| 项 | 官方规范 | 本项目落地 |
|---|---|---|
| 文件位置 | 仓库根 `.workflow/` 目录；控制台启用时生成 `MasterPipeline.yml`、`BranchPipeline.yml`、`PRPipeline.yml` | 沿用三件套命名 + `ReleasePipeline.yml` / `NightlyPipeline.yml` / `LiveSmokePipeline.yml` |
| 顶层字段 | `version: '1.0'`、`name`（仓库内唯一）、`displayName`、`variables` | 全部使用 |
| 触发（push） | `push.branches` / `push.tags` 支持 `prefix`、`precise`、`include`（正则）、`exclude`（排除优先） | main/develop 用 `precise`，标签用 `prefix` |
| 触发（PR） | 键名是 **`pr`**（不是 `pull_request`）；`pr.branches` **匹配源分支**，支持 `commitMessages` / `comments` | `pr.branches.include: '.*'`，目标分支用仓库保护规则约束（见第三节） |
| 触发（定时） | `schedule: [{cron: 'M H D m d y'}]`，秒自动补齐，仅支持一条 | nightly 用 `0 18 * * ?` |
| 阶段 | `stages[].stage`: `name`、`displayName`、`strategy`（`naturally`/`fast`）、`trigger`（`auto`/`manual`） | 门禁用 `fast`；发布的 release 阶段用 `manual`（人工审核） |
| 任务 | `steps[].step` + `name`、`displayName`、插件字段、`commands`/`script`、`dependsOn` | 统一 `shell@agent`（原因见第二节） |
| 高级项 | `strategy.blocking`、`strategy.stepTimeout`（1–1440 分钟） | 按需在控制台设置，未写入 YAML（避开方言差异） |

**修正记录**：首版草稿使用了 `pull_request`、`include: ['v*']` 等 GitHub Actions 习惯写法，与 Gitee Go 不符，现已全部按官方语法重写。

## 二、运行环境的硬约束（重要）

官方 **`build@python` 插件只支持 Python 2.7 / 3.6–3.9**（基础镜像 CentOS 8.3），而本项目 `requires-python = ">=3.13.12"`（使用了 PEP 695 泛型语法、`tomllib` 等）。因此：

- **云端 `build@python` 无法运行本项目的任何门禁**；
- 所有流水线任务改为在 **Gitee Go 自有主机组**（self-hosted host group）上执行，插件用 `shell@agent`；
- 若未来控制台提供 3.13 的 `build@python`，把 `step: shell@agent` 换回 `build@python` + `pythonVersion: '3.13'` 即可，commands 不变。

主机组准备（一次性）：

1. Gitee Go → 主机管理 → 新建主机组，**ID 设为 `qqbot-ci`**（与 YAML 中 `hostGroupID` 一致），按指引在 Linux 主机安装 Agent；
2. 主机安装 `git` 与 `uv`：`curl -LsSf https://astral.sh/uv/install.sh | sh`，随后 `uv python install 3.13.12`（或用系统包管理器安装 3.13.12）；
3. 控制台流水线变量：
   - `CI_WORKSPACE`：代码检出目录（默认 `.`，即任务启动目录；Agent 若检出到子目录需显式指定）；
   - `PYTHON_BIN`：3.13 解释器路径（如 uv 管理的 `.../cpython-3.13.12-*/bin/python3`；若 `python3` 已是 3.13 可保持默认）。
4. 建议使用 Linux 主机：门禁脚本按 POSIX shell 编写。

## 三、分支策略（回答：main 要不要设？）

### 结论

| 分支/事件 | 是否配置 | 流水线 | 理由 |
|---|---|---|---|
| PR（任意源分支 → main/develop） | **必须** | `PRPipeline.yml` | 合并前门禁；Gitee Go 的 `pr.branches` 匹配**源分支**，所以源分支用 `.*` 全匹配，目标分支由仓库保护规则限制 |
| push → **main** | **必须** | `MasterPipeline.yml` | main 是发布基线：`v*` 标签从 main 打；PR 合并结果、管理员直接推送都要重新验证。发布流水线虽然也会全量复核，但 main 门禁能把问题拦在打标签之前 |
| push → develop | **建议** | `BranchPipeline.yml` | 集成分支，直接推送/本地合并后立即验证，反馈最早；**额度紧张时可删除本文件**——经 PR 进入 develop 的改动仍由 PRPipeline 把关 |
| push tag `v*` | **必须** | `ReleasePipeline.yml` | 发布前全量复核 + 制品构建/校验/上传，人工审核放行 |
| 定时 / `nightly-*` | 建议 | `NightlyPipeline.yml` | Fuzz 10000 长尾覆盖；云端只跑分钟级，不跑长时 L4 |
| 手动 / `smoke-*` | 按需 | `LiveSmokePipeline.yml` | 真实凭据连通性，仅手动触发，不产出制品 |

**为什么不靠 `pr.branches` 指定 main/develop**：官方明确 PR 触发器匹配的是**源分支**。要"禁止不过门禁的代码进入 main/develop"，正确做法是在仓库设置里给 main/develop 开启**合并请求保护**（要求流水线通过 + 至少 1 名 reviewer），让 PR 目标分支受保护；YAML 侧用 `include: '.*'` 覆盖所有源分支，避免漏网。

**额度优化建议**（云端配额有限时）：保留 `PRPipeline + MasterPipeline + ReleasePipeline`，删除 `BranchPipeline`（develop 走 PR 门禁），nightly 从每日改为每周。

## 四、流水线总览

```
.workflow/
├── PRPipeline.yml        pr（源分支 .*）                         → gate：构建/测试(500)/扫描
├── MasterPipeline.yml    push precise [main]                     → gate：同上
├── BranchPipeline.yml    push precise [develop]                  → gate：同上（可删）
├── ReleasePipeline.yml   push tags prefix [v]                    → verify(全量) → release(manual)
├── NightlyPipeline.yml   schedule 0 18 * * ? + tags [nightly-]   → Fuzz 10000 全量
└── LiveSmokePipeline.yml tags [smoke-] + 控制台手动              → 真实凭据冒烟（密文变量）
```

所有 `steps[].step` 均为 `shell@agent`（`hostGroupID: qqbot-ci`），脚本统一调用：

```
python tools/ci/gate.py install     # uv sync --frozen（pip 兜底）
python tools/ci/gate.py build       # compileall + sdist/wheel + build.json
python tools/ci/gate.py test ...    # pytest 96 例 + JUnit + 覆盖率 XML
python tools/ci/gate.py scan        # ruff(S)/bandit/pip-audit/密钥/覆盖率门禁
python tools/ci/gate.py release     # 版本三方一致 + twine check + SHA256SUMS + 可选上传
```

## 五、各阶段详解

### 1 构建

`gate.py install`：Python ≥3.13 校验（非 3.13.12 仅告警）；优先 `uv sync --frozen` 严格按锁文件安装，无 uv 时 pip 兜底。
`gate.py build`：先 `compileall src` 语法门禁（坏 import 在打包前暴露）→ `python -m build` 产出 sdist/wheel → 校验产物名携带版本 → 写 `reports/ci/build.json`（产物 SHA256 清单）。

### 2 测试

`gate.py test --examples N`：96 个用例（L2 凭证/Fuzz、L3 协议、L4 秒级并发背压、L5 恶意服务器/TLS MITM），全部进程内假服务器，**零网络、零凭据**。输出 `junit.xml` 与 `coverage.xml`。

- PR/main/develop：`--examples 500`（实测 24s）；
- nightly/release：`--examples 10000`（长尾输入）；
- 本地默认 2000（`QQBOT_FUZZ_EXAMPLES` 可控）。

**长时 L4 边界**：S4-03/08/10/11（24h RSS/句柄/任务稳定性）**不在云端执行**（配额限制），使用 `tools/soak_test.py` 本地跑，报告落 `reports/local-soak/`（gitignored）。

### 3 扫描

| 门禁 | 命令 | 阈值 |
|---|---|---|
| 静态 | `ruff check`（E/F/I/UP/B/ASYNC/S）+ `ruff format --check` | 0 |
| 安全静态 | `bandit -r src -ll` | Medium+ 0 命中 |
| 依赖 CVE | `pip-audit -l` | 0 已知漏洞（`security-audit-ignore.txt` 可评审豁免） |
| 密钥/危险调用 | `tools/check_secrets.py`（S1-01/02/03） | 0 |
| 覆盖率 | `coverage report --fail-under` | 默认 75%（当前 78%） |

产物：`reports/ci/{ruff,bandit,pip-audit,secrets}.json` + `summary.md`。`shell@agent` 的制品上传支持因 Gitee Go 版本而异：控制台若支持"制品"配置可直接归档 `reports/ci/` 与 `dist/`，否则报告保留在主机组工作目录并在日志中输出摘要。

### 4 发布

`ReleasePipeline.yml` 两段式：

1. **verify（自动）**：全量测试（10000）+ 全量扫描 + 构建；
2. **release（manual）**：控制台点击审核后执行 `gate.py release --publish`：
   - 三方版本一致性：tag（去 v 前缀）== `pyproject.toml` == `constants.__version__`；
   - `twine check` 校验元数据；生成 `SHA256SUMS`；
   - 可选上传：`PYPI_TOKEN` → PyPI；`GITEE_TOKEN` + `GITEE_REPO` → Gitee Release 及附件。

### 5 手动冒烟

`LiveSmokePipeline.yml`：`gate.py smoke` → `examples/smoke_test.py --gateway`（token → 资料 → 网关 → WS READY，只读不发消息）。凭据为控制台密文变量，永不用于 PR。

## 六、凭据与权限

| 项 | 策略 |
|---|---|
| PR/分支流水线 | 不注入任何密文变量；测试全用假服务器 |
| release / live-smoke | 密文变量仅授权给受保护标签/手动运行；release 阶段 `trigger: manual` |
| 变量 | `PYPI_TOKEN`、`GITEE_TOKEN`+`GITEE_REPO`、`QQBOT_APP_ID`（明文）+`QQBOT_CLIENT_SECRET`（密文） |
| 日志 | 密钥扫描 + 日志卫生测试双重保证；CI 日志不含 token/secret |

## 七、额度与耗时

- 云端只跑分钟级：gate 流水线 ≤5min（本地实测全门禁约 2.5min）；nightly ≤30min（Fuzz 10000 约 3~4min）。
- 长时 L4（小时级）只在本地：`python tools/soak_test.py --minutes 1440 --fail-on-growth`。
- 主机组侧缓存 `~/.cache/uv` 与 `~/.cache/pip`；不缓存 `.venv`（绝对路径不可移植，重建仅数秒）。

## 八、落地步骤

1. 推送代码后，Gitee 仓库 → Gitee Go → 启用，控制台会按 `.workflow/*.yml` 生成流水线（六个文件对应六条流水线）；
2. 主机管理创建 `qqbot-ci` 主机组并安装 Agent、Python 3.13.12、uv；
3. 设置变量 `CI_WORKSPACE`、`PYTHON_BIN`；发布/冒烟流水线追加对应 token 密文变量；
4. 仓库设置 → 分支保护：main/develop 要求合并请求通过流水线 + 1 review；标签 `v*` 仅维护者可推；
5. `NightlyPipeline` 的定时在 YAML 的 `schedule` 中（控制台可再确认）；`LiveSmokePipeline` 保持 `trigger: manual`。

## 九、本地复现

```bash
python tools/ci/gate.py all                  # 全链路演练（发布 dry-run）
python tools/ci/gate.py test --examples 500  # PR 档位
python tools/ci/gate.py scan                 # 扫描 + 覆盖率门禁
python tools/ci/gate.py release --tag v0.2.0 # 版本一致性 + 制品校验
python tools/ci/gate.py smoke                # 手动真实冒烟（需环境变量）
python tools/soak_test.py --minutes 60       # 长时 L4（本地专用）
```

## 十、演进路线

1. 覆盖率门禁 75% → 85%（补齐 `api/media.py`、`api/messages.py` 错误分支）；
2. 长时稳定性本地常规化（`soak_test.py`），发布前跑 ≥60 分钟；不进云端 nightly；
3. release 增加 SBOM（cyclonedx）与制品签名；
4. 主机组升级后，评估把门禁迁回云构建（若 `build@python` 支持 3.13）。
