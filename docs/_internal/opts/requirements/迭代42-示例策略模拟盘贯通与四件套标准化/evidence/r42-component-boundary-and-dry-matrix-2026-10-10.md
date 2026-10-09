# 迭代42 — 组件边界与 optional16 干跑矩阵复核（2026-10-10）

范围：按用户目标"继续测试这些策略使用 bt_api_gateway / bt_api_risk / bt_api_monitor /
bt_api_execution"对迭代42 各示例做**组件交互边界**复核（非组件正路径重收——组件正路径
的正式验收仍是迭代41 的 optional16 真实矩阵，本记录不重复其结论）。

## 执行与结果

| 项 | 命令/方式 | 结果 |
| --- | --- | --- |
| 入口导入边界 | 新测试 `tests/unit/test_iteration42_component_boundaries.py`（8 入口 × spec 加载，sys.modules 增量） | 42 passed：导入任一标准入口**不会**引入 bt_api_py/risk/monitor/execution/gateway 任一模块 |
| 组件挂载型 flag | 同上（8 入口 × `--execution/--risk/--monitor/--gateway`） | 全部 exit 2 `unknown_arguments_rejected`（无隐藏组件开关/静默挂载） |
| optional16 矩阵干跑 | `python run_matrix.py --dry --out <temp>`（不改写 `acceptance-matrix.json`） | 16 组合 × C01/T03 = 32/32 DRY(exit 0)：flag 管线与用例配置在当前仓库状态下无漂移 |
| 组件包导入 | dev 树（D:/bt_api_py）逐一导入四个包 + 关键符号 | 4/4 OK（来源均为 dev） |
| optional16 契约 | spec 模块：`matrix_specs()/combo_id/from_config`、`COMPONENT_FLAGS`、`TRANSPORTS` | 16 唯一组合、2 传输 × 2³ 组件全覆盖、默认 `direct-e0-r0-m0` |

## 边界事实（与计划一致）

- SimNow（013_x/014_x/015）本迭代写路径**故意不经过组件**：§5.1 决定直连 registered-sim；
  组件属于受管路线，保持关闭。入口一律拒绝组件型 flag。
- 012_x 的 demo 路径沿用既有 legacy 引擎（R2/R3 已验收接线）；组件正路径的 binance
  参考矩阵（16/16 真实 PASS）与网关能力验收仍是迭代41 交付，未在本轮重跑（需 demo 账户
  与外网；且其证据不受本轮源码变更影响——本轮未触碰 optional16 目录）。
- 未发现需要修复的组件侧问题（本轮全部检查通过）。若后续要做 012_x 的"fake 挂载深测"
  （components.py 以假 client 驱动真实 DurableRiskGate/ManagedExecutionFacade/DurableOutbox），
  属可选加深项，不改变现有验收结论。

## 证据层级

本记录为**离线**证据：边界测试、干跑矩阵、导入检查；不构成账户、provider 或成交结论。
