# 合同冻结件：配置笛卡尔负例 Fixture 清单 v1（T-009）

> 日期：2026-11-23　状态：**FROZEN_V1**
> 关联需求：`R62S-01`、`R62S-02`、`R62S-03`、`R62S-09`；关联验收：`S-01`、`S-09`。

## 1. 合法正例 Fixtures（P-01 ～ P-05）

| ID | 形态 | 期望结果 |
| --- | --- | --- |
| `P-01` | Direct 正常态（`mode="direct"` + `exchange_kwargs` + `write_admission={route: True}`） | 返回 `DirectBtApiStore`，`run_binding.mode == "direct"`，0 网络连接 |
| `P-02` | Direct 白名单借用态（`mode="direct"` + 受控 fake unified facade） | 返回 `DirectBtApiStore`，`run_binding.mode == "direct"` |
| `P-03` | Direct 只读预演态（`mode="direct"` + `write_admission={route: False}` 或 `market_data_only=True`） | 返回 `DirectBtApiStore`，`run_binding.market_data_only` 生效，写入口 fail-closed |
| `P-04` | Gateway 正常态（`mode="gateway"` + strict `gateway_strategy` 含非 `"none"` `risk` & `execution` + `GatewayPendingHost` + `security_profiles` + 合法 `GatewayReadinessProof`） | 返回 `GatewayBtApiStore`，`run_binding.mode == "gateway"` |
| `P-05` | Gateway 只读预演态（`mode="gateway"` + `market_data_only=True` + 合法 Gateway 绑定） | 返回 `GatewayBtApiStore`，`run_binding.market_data_only is True`，0 写入 |

## 2. 负例 Fixtures（N-01 ～ N-14，全部要求网络连接前或只读预检阶段拒绝 + Mutation Check）

| ID | 输入构造 | 预期错误码 | Mutation Check 守卫目标 |
| --- | --- | --- | --- |
| `N-01a/b` | 缺 `mode` 或未知 `mode="hybrid"` / `mode="paper"` / 非字符串 `mode=1` | `MODE_REQUIRED` / `MODE_INVALID` | `_validate_explicit_mode` |
| `N-02` | `mode="direct"` + `gateway_strategy` / `gateway_host` / `gateway_security_profiles` | `MODE_CONFLICT` | `_reject_direct_forbidden_keys` |
| `N-03` | `mode="direct"` + `service_client_config` / `gateway_client_config` / `execution_parent_port` / `execution_order_routing` | `LEGACY_HYBRID_ROUTING_RETIRED` | `_reject_direct_forbidden_keys` |
| `N-04` | `mode="direct"` + `market_runtime_factory` / `forwarding_config` / `transport_mode` | `DIRECT_SERVICE_KEY_FORBIDDEN` | `_reject_direct_forbidden_keys` |
| `N-05` | `mode="direct"` + `execution_config` / `order_journal` / `managed_execution_adapter` / 显式 `risk` | `risk_requires_gateway` / `LEGACY_EXECUTION_PATH_RETIRED` | `_reject_direct_forbidden_keys` |
| `N-06` | `mode="gateway"` + `exchange_kwargs` / `write_admission` / `direct` / `ctp` / `api` / `api_cls` | `GATEWAY_CONFIGURATION_CONFLICT` | `_reject_gateway_forbidden_keys` |
| `N-07` | `mode="gateway"` + `gateway_strategy.risk == "none"` 或缺失 `risk` | `GATEWAY_RISK_REQUIRED` | `_validate_strict_gateway_section` |
| `N-08` | `mode="gateway"` + `gateway_strategy.execution == "none"` 或缺失 `execution` | `GATEWAY_EXECUTION_REQUIRED` | `_validate_strict_gateway_section` |
| `N-09` | `mode="gateway"` + 本地 `calendars.feed_scope` 或 `feed.calendar_*` | `CALENDAR_SCOPE_CONFLICT` | `_validate_gateway_calendar_exclusivity` |
| `N-10` | 跨模式/跨账户/跨令牌互挂（`DirectBtApiStore` 配 `GatewayBtApiFeed` 或伪造/不同 `binding_token`） | `RUN_BINDING_MISMATCH` | `verify_run_binding` |
| `N-11` | **正向术语防误杀**：`mode="gateway"` 配置中含合法 Gateway 挂载名 `application.direct_write` / `broker.direct_write` / `direct.delegated_cancel` | **必须通过**，不得按 `"direct"` 子串误拒 | 术语边界测试 |
| `N-12` | 动态预检失败：组件 `UNREACHABLE`、`AUTH_FAILED`、`VERSION_INCOMPATIBLE`、`strategy_principal_has_submit=True`、`monitor_required=False` | 分别返回对应有限错误码，不互相伪装 | `validate_gateway_readiness_proof` |
| `N-13` | 同进程先装配 `direct` 再装配 `gateway`（或反向，`D62S-09a`） | `PROCESS_MODE_CONFLICT` | `ProcessModeFence.claim` |
| `N-14` | Gateway 模式配置允许 `DIRECT_PATH` 旁路（`D62S-05`），或 Gateway 选择非 CTP 场所如 `OKX___SWAP`（`D62S-08c`） | `GATEWAY_DIRECT_PATH_BYPASS_FORBIDDEN` / `GATEWAY_VENUE_UNSUPPORTED` | `_validate_strict_gateway_section` |
