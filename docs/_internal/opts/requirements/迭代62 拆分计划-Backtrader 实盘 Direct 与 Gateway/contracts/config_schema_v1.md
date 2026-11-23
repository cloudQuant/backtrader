# 合同冻结件：配置分层 Schema 与显式 `mode` 合同 v1（T-008）

> 日期：2026-11-23　状态：**FROZEN_V1（轨道一冻结，待 SPLIT-01 实现验证）**
> 依据：已确认 `D62S-01`～`D62S-09`（G0 闭合）；关联需求 `R62S-01`、`R62S-02`、`R62S-03`、`R62S-09`；关联验收 `S-01`、`S-09`。

## 1. 显式 `mode` 字段路径与合法值

- **YAML 顶层字段**：`mode: "direct" | "gateway"`（必填、小写 ASCII 字符串、启动时不可变）。
- **Python 组合根参数**：`mode="direct"` 或 `mode="gateway"`（不可省略、不从 `gateway_strategy`/`write_admission`/`backend` 猜默认）。
- **写权限叠加状态（不是模式）**：
  - Direct 只读预演态：`mode: "direct"` + `direct.write_admission: false` 或 `broker.market_data_only: true`；
  - Gateway 只读预演态：`mode: "gateway"` + `broker.market_data_only: true`。
- **互斥粒度（`D62S-09a`）**：四层互斥（策略目录 `state/identity.json`、对象图 `LiveRunBinding`、账户作用域、操作系统进程单模式栅栏）。

## 2. 三层配置 Schema

| 配置层 | 合法键集 | 适用模式 |
| --- | --- | --- |
| **公共层** | `mode`、`symbols`、`contracts`、`feed`、`broker`（公共键：`position_mode`、`market_data_only`、`shutdown_timeout`、`cash`、`value`）、`strategy_params`、`logging`、`trade_logger`、`run_timeout_seconds` | Direct + Gateway |
| **Direct 专属层** | `direct`（`write_admission`、`market_clock_verification`）、`ctp`（或对应直连 provider 公开配置）、`exchange_kwargs`、`symbol_routes`、`calendars`（含 `root` 与 `feed_scope`）、`broker` Direct 专属参数（`strategy_dir`、`first_init`、`waiting_orders`、`direct_facts_timeout`、`stop_cancel_timeout` 等） | 仅 `mode: direct` |
| **Gateway 专属层** | `gateway_resource_provider`、`gateway_strategy`（`schema_version`、`exchange_name`、`client_config`、`binding`、`route`、`peer`、`requested_operations`、`execution_time_policy`、`instruments_by_ref`、`risk` 必填非 `"none"`、`execution` 必填非 `"none"`、`account_settings`、`market_settings`、`instrument_settings`、`calendar_settings`、`strategy_finance_currency`、`readiness_expectations`）、`calendars.root`（**禁止** `calendars.feed_scope`）、`gateway_host`、`gateway_security_profiles`、`gateway_readiness_proof` | 仅 `mode: gateway` |

## 3. 现行隐式判据迁移映射

| 现行代码判据 | 组合根行为 |
| --- | --- |
| 缺 `mode` 但含 `"gateway_strategy"` | 拒绝 `MODE_REQUIRED`，提示显式添加 `mode: gateway` |
| 缺 `mode` 但含 `exchange_kwargs`/`write_admission` | 拒绝 `MODE_REQUIRED`，提示显式添加 `mode: direct` |
| `backend="gateway"` / `backend="forwarding"` / `provider="forwarding"` | 拒绝 `LegacyGatewayMigrationRequiredError` |
| `api=ServiceReadProxy(...)` | 迁入独立非实盘类 `ServiceReadOnlyStore`，组合根拒绝作为实盘模式 |
| `provider="local_replay"` | 迁入独立非实盘类 `ReplayBtApiFeed`（保持 `store=None`），组合根拒绝作为实盘模式 |

## 4. 两模式精确拒收键清单（与两仓源码静态对齐）

- **Direct 拒收键**：`gateway`、`gateway_strategy`、`gateway_resource_provider`、`gateway_host`、`gateway_security_profiles`、`gateway_run_lock`、`gateway_readiness_proof`、`service_client_config`、`gateway_client_config`、`execution_parent_port`、`execution_order_routing`、`market_runtime_factory`、`forwarding_config`、`transport_mode`、`managed_execution_adapter`、`execution_authorization`、`settlement_authorization`、`execution_config`、`DIRECT_EXECUTION_CONFIG_KEYS`（除 `market_data_only` 外全部 11 键：`order_journal`、`require_order_journal`、`order_poll_interval`、`account_currency`、`account_currencies`、`account_ids`、`required_environments`、`strategy_id`、`strategy_identity_sha256`、`account_maximum_loss_bps`、`account_risk_max_age_seconds`）、顶层 `risk`、顶层 `execution`。
- **Gateway 拒收键**：`exchange_kwargs`、`direct`、`ctp`、`write_admission`、`api`、`api_cls`、`api_kwargs`、非空 `backend`、顶层 `risk`、顶层 `execution`、`gateway_strategy.risk == "none"` 或缺失、`gateway_strategy.execution == "none"` 或缺失、允许 `DIRECT_PATH` 旁路的配置、`calendars.feed_scope`、`feed.calendar_*`、`contracts.<sym>.calendar_*`、`managed_execution_adapter`、`execution_authorization`、`settlement_authorization`、`execution_config`、`service_client_config`、`gateway_client_config`、`execution_parent_port`、`market_runtime_factory`、`forwarding_config`、`transport_mode`、`waiting_orders`、`direct_facts_timeout`。
- **受控测试替身白名单**：仅 Python API 显式关键字参数 `direct_api_factory` / `api`（Direct 测试白名单）与 `gateway_api_factory` / `gateway_readiness_proof`（Gateway 契约替身测试白名单）；YAML 配置解析器一律禁止导入任意可调用对象。
