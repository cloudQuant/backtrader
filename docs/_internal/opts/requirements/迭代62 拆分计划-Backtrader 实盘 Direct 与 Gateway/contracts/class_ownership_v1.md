# 合同冻结件：全量类/Mixin/模块归属与 `isinstance` 方案 v1（T-012）

> 日期：2026-11-23　状态：**FROZEN_V1**
> 依据：已确认 `D62S-06`、`D62S-07`、`D62S-08b`；关联需求 `R62S-07`；关联验收 `S-06`。

## 1. 数学严谨的继承与 `isinstance` 兼容方案

- **Store**：`BaseBtApiStore(LiveStoreBase)`（显式 `__init__`，**不定义类属性 `params`**，规避 `StoreParams` 不合并陷阱）← `DirectBtApiStore(BaseBtApiStore)` / `GatewayBtApiStore(BaseBtApiStore)`；公开兼容壳 `BtApiStore` 继承 `BaseBtApiStore`（且经元类无关的兼容策略或把 `BaseBtApiStore` 作为实际共享基类，同时让 `DirectBtApiStore(BtApiStore)` / `GatewayBtApiStore(BtApiStore)` 或使用 `abc.ABC.register` 使 `isinstance(x, BtApiStore)` 为 `True` 且 `isinstance(direct, GatewayBtApiStore)` 为 `False`）。
  - **选定最简零元类冲突实现**：`BaseBtApiStore(LiveStoreBase)` 提供共享行为；`BtApiStore(BaseBtApiStore)` 作为薄兼容分发基类（`__new__` 在 `cls is BtApiStore` 时按模式分派，或保持直接构造兼容），`DirectBtApiStore(BtApiStore)` 与 `GatewayBtApiStore(BtApiStore)` 为兄弟具体子类——**无需 `ABCMeta`，天然保证**：
    - `isinstance(direct_store, BaseBtApiStore) is True`
    - `isinstance(direct_store, BtApiStore) is True`
    - `isinstance(direct_store, DirectBtApiStore) is True`
    - `isinstance(direct_store, GatewayBtApiStore) is False`
    - 同理适用于 `BaseBtApiFeed` ← `BtApiFeed` ← `DirectBtApiFeed` / `GatewayBtApiFeed`（兼容 `LiveFeedBase(DataBase, ABC)` 无元类冲突！）与 `BaseBtApiBroker` ← `BtApiBroker` ← `DirectBtApiBroker` / `GatewayBtApiBroker`（兼容 `BrokerBase(BrokerAliasMixin, ParameterizedBase)` 参数描述符，且 `DirectBtApiBroker` / `GatewayBtApiBroker` 隔离各自专属参数校验！）。
  - **独立非实盘类**：`ReplayBtApiFeed(LiveFeedBase)` 与 `ServiceReadOnlyStore(LiveStoreBase)` **不继承** `BaseBtApiFeed`/`BaseBtApiStore`，彻底隔离实盘写入面。

## 2. 全仓 7 处 `isinstance` + 3 处非绑定类方法调用迁移归属

| 位置 | 现行代码 | 目标归属 |
| --- | --- | --- |
| `_btapi_gateway_stream.py:361,365,367` | `isinstance(source, BtApiFeed)` + `BtApiFeed.historical_warmup_active/gateway_trade_qualification` | `isinstance(source, BaseBtApiFeed)` + `BaseBtApiFeed` 防覆写类方法 |
| `btapifeed.py:1995,2004` | `isinstance(store, BtApiStore)` + `BtApiStore.gateway_instrument_status` | `isinstance(store, GatewayBtApiStore)` + `GatewayBtApiStore.gateway_instrument_status`（兼容壳通过） |
| `service/gateway_config.py:410` | `isinstance(data, BtApiFeed)` | `isinstance(data, BaseBtApiFeed)` + Gateway 绑定校验 |
| `service/managed_runtime_host.py:374,377` | `isinstance(broker/store, BtApi*)` | SPLIT-04 随路径 3 退役 |
| `service/service_execution_session.py:702` | `isinstance(broker, BtApiBroker)` | SPLIT-04 随路径 3 退役 |

## 3. 核心模块归属摘要

- **Base**：`btapi_composition.py`、`base_btapi_store.py`、`base_btapi_feed.py`、`base_btapi_broker.py`、`_market_source_port.py`、`_calendar_query_port.py`、`_btapi_strategy_ledger.py`、`_btapi_strategy_events.py`、`_btapi_reconciliation.py`、`live_state/{identity,sequence,atomic,audit,state_dir,coordination,cli,_common}.py`、`live_trading/*`。
- **Direct 专属**：`direct_btapi_store.py`、`direct_btapi_feed.py`、`direct_btapi_broker.py`、`_btapi_direct_mode.py`、`live_state/{pending,waiting,waiting_notify,snapshot}.py`。
- **Gateway 专属**：`gateway_btapi_store.py`、`gateway_btapi_feed.py`、`gateway_btapi_broker.py`、`_btapi_gateway_{stream,notifications,projection,events}.py`、`_execution_{parent_projection,routing_apply}.py`、`service/{gateway_config,gateway_market_adapter,gateway_instrument_status}.py`、`live_state/gateway_*.py`。
- **独立非实盘（`D62S-08a`）**：`replay_btapi_feed.py`、`service_readonly_store.py`（封装 `ServiceReadProxy`）。
- **SPLIT-04 退役（`D62S-07a`）**：路径 2（旧直连 `execution_config` 写分支）、路径 3（`ServiceExecutionSession`/`ManagedExecutionAdapter`/`managed_runtime_host`/`ServiceRecoveryBrokerMixin`）、路径 5（`btapistore.py:_configure_execution_routing` 及 3 构造参数）、路径 6（`market_runtime_factory`/`forwarding_config`/`transport_mode` 拒收）。
