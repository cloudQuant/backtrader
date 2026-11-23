# 合同冻结件：九路径与旧混合清退表 v1（T-015）

> 日期：2026-11-23　状态：**FROZEN_V1**
> 依据：已确认 `D62S-07a/b`、`D62S-08a`、`D65-11`；关联需求 `R62S-12`；关联验收 `S-08`、`S-12`。

## 1. 九路径最终处置裁决

| 路径 | 定位 | 处置动作 | 审批与留痕要求 |
| --- | --- | --- | --- |
| 1 | 迭代 62 Direct（`DirectWriteCoordinator` + `live_state`） | **保留为 Direct 唯一实盘写路径** | — |
| 2 | 迭代 60 旧直连 SDK 写分支（`execution_config`/`DIRECT_EXECUTION_CONFIG_KEYS`） | SPLIT-04 在新入口与实盘 Direct 路径 fail-closed 拒绝并清退 | 历史未决须先只读核验；**审批人：项目/账户负责人（用户本人）** |
| 3 | 迭代 41/60 托管服务路径（`ServiceExecutionSession`/`ManagedExecutionAdapter`/`managed_runtime_session`/`ServiceRecoveryBrokerMixin`） | SPLIT-04 按 `D65-11` 清退退役 | 确认 0 生产调用与 0 未决后退役 |
| 4 | 迭代 63–65 Gateway（`state/gateway_execution_routing.sqlite`） | **保留为 Gateway 模式基线**（升级为方案 A + A2 严格五组件合同） | 严禁误删/误改 `gateway_execution_routing.sqlite` |
| 5 | 迭代 65 Direct+Execution 混合路由（`btapistore.py:_configure_execution_routing`、3 构造参数、`state/execution_routing.sqlite`） | **SPLIT-04 清退**：移除 `btapistore.py` 混合入口与 `_btapi_direct_mode.py` 路径 5 钩子；新增 `live_state/cli.py export-legacy-execution-routing` 只读导出 CLI；**严禁删库，保留路径 4 共用的 `_execution_parent_projection.py`/`_execution_routing_apply.py`** | 含未决记录的旧库迁移须由**项目/账户负责人（用户本人）逐案书面审批**并记入 `audit.jsonl` |
| 6 | 62.08 MarketHub+Direct 混合（`market_runtime_factory`/`forwarding_config`/`transport_mode`） | **`DirectBtApiStore` 与组合根显式拒收** | — |
| 7 | Cohort / 因子源（`cohort_source_mode`/`market_factor_source_binding`） | 仅保留于 Direct/研究路径；Gateway Feed 维持显式拒绝 | — |
| 8 | `ServiceReadProxy` 只读路径 | 剥离为独立非实盘类 `ServiceReadOnlyStore`（0 写能力），保留 `bt_api_runtime` 跨仓兼容评估 | — |
| 9 | `local_replay` 与无 SDK 预置数据夹具 | 剥离为独立非实盘类 `ReplayBtApiFeed`（强制 `store=None`）；测试替身注入走白名单 | — |
