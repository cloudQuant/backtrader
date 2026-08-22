---
title: 分支治理
description: 三分支模型、PR 分流、风险分级与 promotion/hotfix 协议
---

# 分支治理

> 状态：**实施中**（迭代 140；Ruleset 自 2026-08-22 起处于两周观察期）
> 适用仓库：`cloudQuant/backtrader`
> 长期分支：`master`、`development`、`dev`

本文档是分支角色、PR 分流、审查要求与跨分支修复传播的**权威来源**。它取代任何
早前的「`development` → `master` 发布链」表述。当其他文档（`README.md`、
`CONTRIBUTING.md`、`AGENTS.md`、PR/issue 模板）与本文档冲突时，以本文档为准。

## 1. 强制性分支事实

以下定义是本仓库治理的不可协商前提，**不遵循**常见 GitFlow。

| 分支 | 角色 | 允许进入的变更 | 禁止的变更 |
|---|---|---|---|
| `master` | 原始 Backtrader 基线 | 已在原始版复现的 Bug、兼容性或安全修复 | 日常功能、优化版重构、`dev`/`development` 的例行合并 |
| `development` | 改进与优化版本 | 优化版能力、架构优化、仅在优化版存在的回归修复、受控集成的日常开发成果 | 被当作 `master` 的发布候选或反向同步源 |
| `dev` | 日常开发入口 | 常规功能、普通 Bug 修复、文档、测试、重构、社区贡献 | 绕过评审直接进入 `development`/`master` |

## 2. 治理决策（D0–D4）

迭代 140 的已记录决策。未决项为阻塞项，不得静默默认假设。

| 编号 | 决策 | 结论 |
|---|---|---|
| D0 | GitHub 默认分支 | **保持 `development`**（2026-08-20 决策）。贡献者通过 PR 模板与 `pr-governance` workflow 显式选择目标分支，而非依赖默认分支。 |
| D1 | GitHub/Gitee 权威来源与同步 | **GitHub `cloudQuant/backtrader` 为审查权威；Gitee `yunjinqi/backtrader` 为受控镜像。** 镜像负责人在每次长期分支合并后核对 SHA（见 §8）。 |
| D2 | Owner 团队与管理员 bypass | **已于 2026-08-22 解决：**`@cloudQuant` 是对本仓库有管理员权限的真实 GitHub 用户，作为 CODEOWNER；Gitee 镜像使用真实 `yunjinqi` 身份。禁止占位 owner；任何紧急 bypass 必须在 PR 中留痕。 |
| D3 | 分支审批门槛 | `dev`：1 次批准 + `Lint` + `Test Summary`。`development`：owner 审查；R2/R3 需 owner + 第二位维护者。`master`：仅 R3（见 §4）。Ruleset 先以 `evaluate` 运行，在 2026-09-05 前不得转为 `active`，且需先审查观察证据。**未关闭例外：**当前只确认一名真实 GitHub maintainer，R2/R3 的第二位独立审批尚无法实施，因而阻塞这些路径的 active rollout。 |
| D4 | Merge Queue 阈值 | 本迭代不启用。仅在连续 4 周每天 ≥3 个待合并 PR 或频繁基线冲突后再评估。 |

## 3. PR 目标分支决策表

| 情况 | 默认目标 | 必需证据 | 合并后动作 |
|---|---|---|---|
| 文档、测试、常规功能、普通 Bug 修复 | `dev` | 关联测试、快速门禁、≥1 位维护者批准 | 纳入下一次 `dev → development` promotion 候选 |
| 仅在优化架构出现的问题或优化版功能 | `development` | 优化版最小复现、风险说明、领域 owner 批准 | 判断 `dev` 是否需要等价修复 |
| 原始 Backtrader 的真实 Bug / 安全问题 | `master` | 在 `master` 的独立复现、回归测试、原始 API 兼容性说明 | 创建前移 issue；不得以「已修 master」关闭 `dev`/`development` 风险 |
| 跨分支语义不同的修复 | 分别建 PR | 每个目标分支的独立实现与测试 | 交叉链接 PR/issue；禁止盲目 merge 或 cherry-pick |

## 4. 风险级别（R0–R3）

| 等级 | 典型路径 | 最低评审 | 最低验证 |
|---|---|---|---|
| R0 文档/测试 | `docs/`、测试注释、非行为性工具 | 1 位维护者 | 格式、受影响测试、文档构建 |
| R1 常规模块 | 单个 indicator/analyzer/feed 的局部修复 | 1 位模块 owner | 快速 CI + 新增/修改回归测试 |
| R2 核心/兼容性 | `lineroot`、`linebuffer`、`lineseries`、`lineiterator`、`cerebro`、`strategy`、`broker`、`brokers/`、`feeds/`、`metabase` | 领域 owner + 第二位维护者 | 快速 CI、`make test-strategies`、runonce/runnext 或兼容性证据 |
| R3 原始版/安全/发布 | `master` hotfix、供应链、安全、公开 API 破坏风险 | 核心维护者明确批准 | 目标分支全量测试、最小复现、回归、发布/安全检查 |

## 5. 目标工作流

```text
常规社区贡献
fork / feature/*  ── PR + 快速门禁 ──> dev
                                          │
                                          │  受控 promotion PR + 全量门禁
                                          ▼
                                     development

优化版专属问题
feature/* ── PR + optimization 门禁 ──> development

原始版真实 Bug
hotfix/master-* ── PR + original-baseline 门禁 ──> master
                                              │
                                              └─ 建立前移任务：分别评估并移植到 dev / development
```

## 6. Promotion 协议（`dev` → `development`）

Promotion 是**受控 PR**，不是例行合并。

1. 新建 `promotion/dev-YYYYMMDD` PR，目标 `development`。
2. 描述：变更范围、显式排除的内容、完整验证、性能/兼容性差异、回滚点。
3. R2/R3 内容需跑全量门禁（`make test-strategies`、runonce/runnext 一致性或策略基线比对）。
4. 按 §4 取得 owner + 第二位维护者批准。
5. 合并；在每周治理摘要中记录本次 promotion（§12）。

## 7. `master` hotfix 前移协议

每个 `master` 修复在治理完成前必须产生一个 **linked 前移 issue**。

1. 在 `master` 独立复现；落地 `hotfix/master-*` PR（R3 门禁）。
2. 创建 `forward-port-required` issue 描述修复。
3. 分别评估 `dev` 与 `development` 是否受影响。
4. 对每个受影响分支，实现**带独立测试的等价移植**——禁止盲目跨分支 merge 或 cherry-pick。
5. 每个受影响分支验证通过后才标记 `forward-port-complete`。

未完成前移的 hotfix **不算**治理完成。

## 8. GitHub / Gitee 镜像一致性

- GitHub 为审查权威；Gitee 为受控镜像。
- 每次长期分支合并后，验证两端同一 SHA：

```bash
git ls-remote --heads https://github.com/cloudQuant/backtrader.git master development dev
git ls-remote --heads https://gitee.com/yunjinqi/backtrader.git master development dev
```

- 镜像负责人使用 GitHub `@cloudQuant` 与 Gitee `yunjinqi` 两个真实身份。任何漂移必须
  告警并由该负责人处理；任何记录的差异必须有书面原因。

## 9. 标签

标准化标签分类（通过 GitHub 应用；见 §10 运行手册）：

| 前缀 | 取值 |
|---|---|
| `target:*` | `target:dev`、`target:development`、`target:master-hotfix` |
| `type:*` | `type:bug`、`type:feature`、`type:docs`、`type:tests`、`type:refactor` |
| `area:*` | `area:core`、`area:broker`、`area:feeds`、`area:indicators`、`area:analyzers`、`area:observers`、`area:tests`、`area:docs`、`area:ci` |
| `risk:*` | `risk:R0`、`risk:R1`、`risk:R2`、`risk:R3` |
| `status:*` | `status:triage`、`status:review`、`status:blocked` |
| 动作 | `needs-repro`、`needs-tests`、`ready-to-merge`、`blocked`、`backport-or-forward-port-required`、`forward-port-required`、`forward-port-complete` |

## 10. 外部设置运行手册（手动、仅管理员）

以下仓库内产物（manifest 文件、`CODEOWNERS` 与校验脚本）表达了预期的 GitHub 配置。
应用真实设置需要管理员权限，须通过 UI/API 手动完成——**CI 永不持有管理员凭据**。

### 10.1 默认分支（D0）

无需变更：保持 `development` 为默认分支。目标分支选择由 PR 模板与
`PR Governance` workflow 强制，而非默认分支。

### 10.2 Rulesets（D3）

按 `.github/governance/rulesets/{dev,development,master}.json`，为每个长期分支应用
一条 ruleset：

1. 仓库 → Settings → Rules → Rulesets → **New ruleset**。
2. 按 manifest 将目标设为分支（或 `fnmatch` 模式）。
3. 先以 `evaluate` 执行至 2026-09-05。manifest 要求 PR、≥1 批准、`Lint`、
   `Test Summary`、`PR Governance`、`Tiered Validation`，并禁止 force-push/删除、要求
   解决会话。
4. GitHub Ruleset 不能原生按 PR 源分支命名或标签判断。观察期结束后，required 的
   `PR Governance` check 才负责对 `master` 强制 `hotfix/master-*` 与
   `target:master-hotfix`；最小复现和 R3 证据仍由模板与人工评审把关。
5. 通过仓库 Rulesets API 或 UI 应用 JSON，然后用
   `scripts/ci/verify_github_governance.py` 验证；不得把管理员 token 交给 CI。

当前 manifest 有意只要求一次批准，因为目前只确认了一名真实 GitHub maintainer
（`@cloudQuant`）。这**不能**把同一人算作 R2/R3 所需的第二位独立维护者。启用这些路径的
active 规则前，必须新增并核验第二名 maintainer；在此之前记录例外并保持 Ruleset 观察模式。

### 10.3 CODEOWNERS（D2）

`.github/CODEOWNERS` 使用已确认的 GitHub 用户 `@cloudQuant`，不是组织占位符；截至
2026-08-22 它拥有仓库管理员权限。Gitee `yunjinqi` 身份不应作为 GitHub CODEOWNERS
条目。文件进入默认分支后，必须确认 GitHub `codeowners/errors` 响应为空。

### 10.4 标签

一次性创建 §9 的标签（Repository → Issues → Labels）。`classify_pr_risk.py` 脚本
输出建议标签；维护者保留最终覆盖权。

## 11. 验证

```bash
# 导出只读 API 响应，不提交到仓库。
gh api --paginate repos/cloudQuant/backtrader/rulesets > /tmp/backtrader-rulesets.json
gh api repos/cloudQuant/backtrader/codeowners/errors > /tmp/backtrader-codeowners-errors.json

# Ruleset + CODEOWNERS 一致性；观察期预期 enforcement 为 evaluate。
python scripts/ci/verify_github_governance.py \
  --rulesets-json /tmp/backtrader-rulesets.json \
  --codeowners-errors-json /tmp/backtrader-codeowners-errors.json \
  --expected-enforcement evaluate

# PR 风险分级
python scripts/ci/classify_pr_risk.py --paths backtrader/cerebro.py

# 两个脚本的单元测试
pytest tests/unit/scripts/ -q
```

## 12. 观察期与激活记录

管理员以 `evaluate` 创建三条 Ruleset，并在 **2026-09-05** 前保持
`GOVERNANCE_BLOCKING=false`。这段时间记录所有 Rule Insights、缺失 check context、
镜像漂移与 PR 分流例外，写入每周治理记录。只有维护者审阅证据后，管理员才能把三条
Ruleset 改为 `active` 并设置 `GOVERNANCE_BLOCKING=true`；激活的 commit/PR 必须关联该
证据。禁止按日期自动切换。
