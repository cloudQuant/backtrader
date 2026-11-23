# 合同冻结件：公开 API 清单与兼容期合同 v1（T-013）

> 日期：2026-11-23　状态：**FROZEN_V1**
> 依据：已确认 `D62S-08a/b`；关联需求 `R62S-03`、`R62S-07`；关联验收 `S-01`、`S-06`。

## 1. 实盘公开导出清单（6 个具体类 + 组合根工厂 + 兼容壳）

| 公开符号 | 模块位置 | 职责 |
| --- | --- | --- |
| `LiveRunBinding`、`GatewayReadinessProof`、`LiveCompositionError`、`ProcessModeFence`、`create_live_store`、`create_direct_store`、`create_gateway_store`、`validate_live_config` | `backtrader.stores.btapi_composition` | 单一组合根、不可变运行绑定、就绪证明 DTO、配置校验与进程级单模式栅栏 |
| `BaseBtApiStore` | `backtrader.stores.base_btapi_store` | 薄公共 Store 基类（显式 `__init__`，不含类属性 `params`） |
| `DirectBtApiStore` | `backtrader.stores.direct_btapi_store` | Direct 模式专用 Store（拒收路径 2/3/5/6 服务透传键） |
| `GatewayBtApiStore` | `backtrader.stores.gateway_btapi_store` | Gateway 模式专用 Store（含 `GatewayReadinessProof` 校验，0 Monitor/Runtime RPC） |
| `BaseBtApiFeed` | `backtrader.feeds.base_btapi_feed` | 薄公共 Feed 基类（委托 `MarketSourcePort` / `CalendarQueryPort`） |
| `DirectBtApiFeed` | `backtrader.feeds.direct_btapi_feed` | Direct 模式专用 Feed |
| `GatewayBtApiFeed` | `backtrader.feeds.gateway_btapi_feed` | Gateway 模式专用 Feed（保留能力负例） |
| `BaseBtApiBroker` | `backtrader.brokers.base_btapi_broker` | 薄公共 Broker 基类（含统一 `get_shutdown_summary()`） |
| `DirectBtApiBroker` | `backtrader.brokers.direct_btapi_broker` | Direct 模式专用 Broker（含 `direct_params()` 与 `waiting_orders`） |
| `GatewayBtApiBroker` | `backtrader.brokers.gateway_btapi_broker` | Gateway 模式专用 Broker（全量经 Execution，禁止 `DIRECT_PATH` 旁路，不暴露 Direct 参数） |
| 兼容壳 `BtApiStore`、`BtApiFeed`、`BtApiBroker` | 原路径 `backtrader.stores.btapistore` / `feeds.btapifeed` / `brokers.btapibroker` | 保留原公开导入、注册与 `isinstance` 契约至 SPLIT-04 迁移完成，再按后续弃用期决定去留 |

## 2. 独立非实盘导出清单（`D62S-08a`，不暴露账户写能力）

| 公开符号 | 模块位置 | 边界 |
| --- | --- | --- |
| `ReplayBtApiFeed` | `backtrader.feeds.replay_btapi_feed` | 独立回放 Feed，强制 `store=None`、0 写入能力 |
| `ServiceReadOnlyStore` | `backtrader.stores.service_readonly_store` | 封装 `ServiceReadProxy` 的独立只读 Store，拒绝一切写入口 |

## 3. 诊断错误归属

- 模式选择、组合根与跨模式绑定错误统一归属 `backtrader.stores._btapi_errors`（`LiveCompositionError(BtApiStoreError)`，携带有限 ASCII `code` 与可读 `migration_hint`）。
