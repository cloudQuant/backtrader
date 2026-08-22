<!--
master hotfix PR 模板（仅 hotfix/master-* 分支，R3）。
适用：原始 Backtrader 基线的真实 Bug / 安全问题。
见 docs/source/developer-guide/branch-governance.md §7。
提交后请删除本注释块，并携带 target:master-hotfix 标签。
-->

## 在 master 上的独立最小复现

<!-- 仅基于原始版（master）复现的步骤与结果，不得依赖优化版环境 -->

## 回归测试

<!-- 目标分支全量测试 / 最小复现的回归测试命令与结果 -->

## 原始 API 兼容性说明

<!-- 确认不破坏原始版公开 API 兼容性 -->

## 关联前移 issue

<!-- 必填：每个 master 修复必须创建 forward-port issue，例如 Fixes #123 -->
- [ ] 已创建 `forward-port-required` issue
- [ ] 已分别评估 `dev` 与 `development` 是否受影响
