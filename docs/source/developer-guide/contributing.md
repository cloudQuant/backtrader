---
title: Contributing to Backtrader
description: Guidelines for contributing to Backtrader
---

# Contributing to Backtrader

感谢你对 Backtrader 的贡献兴趣！本文档是根目录 [`CONTRIBUTING.md`](../../../CONTRIBUTING.md)
与 [Branch Governance](branch-governance.md) 的收敛版，供开发者指南内阅读。

分支角色、PR 目标分支选择、风险分级与 promotion/hotfix 协议的**权威来源**是
[Branch Governance](branch-governance.md)。任何冲突以分支治理文档为准。

## 快速开始

```bash
# 1. Fork 仓库：https://github.com/cloudQuant/backtrader
# 2. 克隆并添加上游
git clone https://github.com/YOUR_USERNAME/backtrader.git
cd backtrader
git remote add upstream https://github.com/cloudQuant/backtrader.git

# 3. 安装依赖与开发模式（纯 Python，无独立 Cython 编译步骤）
pip install -r requirements.txt
pip install -e .

# 4. 验证
make test-fast
```

## 目标分支选择

本仓库使用**三分支模型**。先确定你的贡献属于哪一类：

| 情况 | 目标分支 |
|------|----------|
| 文档、测试、常规功能、普通 Bug 修复 | `dev` |
| 仅在优化架构出现的问题或优化版功能 | `development` |
| 原始 Backtrader 的真实 Bug / 安全问题 | `master`（`hotfix/master-*`） |

完整决策表与风险分级（R0–R3）见 [Branch Governance](branch-governance.md)。

## 分支命名约定

| 前缀 | 用途 | 示例 |
|------|------|------|
| `feat/` | 新功能 | `feat/websocket-reconnect` |
| `fix/` | Bug 修复 | `fix/indicator-calculation` |
| `refactor/` | 代码重构 | `refactor/broker-optimization` |
| `docs/` | 文档 | `docs/api-reference` |
| `test/` | 测试改进 | `test/coverage-increase` |
| `perf/` | 性能优化 | `perf/line-buffer-cache` |
| `hotfix/master-*` | 原始版热修复 | `hotfix/master-order-cancel` |

## 提交信息

遵循 [Conventional Commits](https://www.conventionalcommits.org/)：

```bash
<type>: <description>
```

有效类型：`feat`、`fix`、`refactor`、`docs`、`test`、`chore`、`perf`。

## 运行测试

```bash
make test-fast        # 日常开发反馈（~3.5min）
make test-strategies  # 改动 cerebro/strategy/line 系统后必跑（~9min）
make test-all         # 全量（~10min）
make format-check     # 格式检查
make lint             # 代码检查
```

## 代码审查标准

| 方面 | 标准 |
|------|------|
| 功能正确性 | 按预期工作，无回归 |
| 代码质量 | 可读、可维护、遵循约定 |
| 测试 | 覆盖充分，处理边界情况 |
| 文档 | 清晰的文档字符串，面向用户的变更已记录 |
| 性能 | 无显著退化，优化已记录 |

审批门槛（D3）：`dev` 1 次批准；`development` R2/R3 需 owner + 第二位维护者；
`master` 仅 R3。详见 [Branch Governance](branch-governance.md)。

## 报告问题

- **Bug**：使用 [Issue Forms](../../../.github/ISSUE_TEMPLATE/) 提交，包含环境、目标分支、最小复现、预期/实际行为、日志。
- **功能请求**：说明问题、目标用户、分支影响、替代方案。
- **安全问题**：走 [`SECURITY.md`](../../../SECURITY.md) 私密报告路径，不要公开提交。

## 许可证与 DCO

Backtrader 采用 GPLv3 许可。通过贡献，你同意贡献将在 GPLv3 下许可，并按
[Developer Certificate of Origin](https://developercertificate.org/) 认证你有权提交：

```bash
git commit -s -m "feat: add new indicator"
```

## 另请参阅

- [Branch Governance](branch-governance.md)
- [开发环境设置](setup.md)
- [代码风格](style.md)
- [测试指南](testing.md)
- [发布流程](release.md)
