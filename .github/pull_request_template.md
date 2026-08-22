<!--
PR 治理说明（提交后请删除本注释块）：
1. 请先阅读 docs/source/developer-guide/branch-governance.md 确定唯一目标分支。
2. 风险级别 R0-R3 定义见分支治理文档 §4。
3. 目标 master 的 PR 必须使用 hotfix/master-* 分支，并携带 target:master-hotfix 标签与最小复现。
-->

## 问题与动机

<!-- 这个 PR 解决什么问题？为什么需要它？ -->

## 目标分支与原因

- **目标分支**: `dev` / `development` / `master`（三选一）
- **原因**: <!-- 为何落到该分支（见分支治理决策表） -->

## 风险级别

- **风险级别**: R0 / R1 / R2 / R3
- **说明**: <!-- 变更路径与风险依据 -->

## 兼容性影响

<!-- 是否影响公开 API？原始版（master）与优化版（development/dev）行为是否一致？ -->

## 执行过的命令与结果

<!-- 粘贴实际运行的命令与关键结果，例如：
make test-fast
make test-strategies   # R2/R3 必跑
make format-check
-->

## 关联 Issue

<!-- 例如：Fixes #123 / Related to #456；master hotfix 需关联 forward-port issue -->
