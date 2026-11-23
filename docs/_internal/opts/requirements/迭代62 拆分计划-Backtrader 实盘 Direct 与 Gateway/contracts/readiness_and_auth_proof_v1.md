# 合同冻结件：`GatewayReadinessProof v1` 与派发前授权核对点（T-011）

> 日期：2026-11-23　状态：**FROZEN_V1**
> 依据：已确认 `D62S-01`（方案 A）、`D62S-02`、`D62S-03`、`D62S-04`、`D62S-05`（方案 A2）；关联需求 `R62S-04`、`R62S-05`、`R62S-06`。

## 1. `GatewayReadinessProof v1` 中立不可变 DTO 字段集

```python
@dataclass(frozen=True)
class GatewayReadinessProof:
    schema_version: int                      # 固定 1
    proof_generation: int                    # 正整数单调代次
    issued_at_ns: int                        # 单调/UTC 签发时间戳（正整数）
    expires_at_ns: int                       # 严格大于 issued_at_ns
    gateway_service_id: str
    gateway_instance_id: str
    gateway_scope_ref: str
    account_scope: str
    strategy_scope: str
    route: str                               # 首期仅 CTP___FUTURE 等 CTP 路由
    strategy_principal_has_submit: bool      # 必须为 False（D62S-03）
    strategy_principal_has_reserve: bool     # 必须为 False（D62S-03）
    delegated_cancel_enabled: bool           # 必须为 True
    risk_required: bool                      # 必须为 True（D62S-04）
    risk_service_ref: str
    risk_protocol_version: str
    risk_state: str                          # READY | DEGRADED | UNAVAILABLE | INCOMPATIBLE
    execution_required: bool                 # 必须为 True（D62S-05）
    execution_service_ref: str
    execution_protocol_version: str
    execution_state: str                     # READY | DEGRADED | UNAVAILABLE | INCOMPATIBLE
    execution_direct_path_disabled: bool     # 必须为 True（D62S-05 方案 A2 禁止 DIRECT_PATH 旁路）
    monitor_required: bool                   # 必须为 True（D62S-02）
    monitor_service_ref: str
    monitor_protocol_version: str
    last_acked_heartbeat_age_ms: Optional[int]
    monitor_stop_new_active: bool
    runtime_supervision_expected: bool       # 必须为 True（D62S-02）
    runtime_service_ref: str
    registered_run_id: Optional[str]         # 非空时须与受管启动 --run-id 精确匹配
```

## 2. 三处具名派发前授权核对点（方案 A + A2）

1. **核对点 1（BT `GatewayBtApiBroker` → Execution）**：核验 `run_binding.mode == "gateway"`、`not market_data_only`、存在有效未过期 `GatewayReadinessProof`、意图唯一 `request_key` 已落盘 `live_state`（W1）、行情资格有效；**拒绝任何返回 `DIRECT_PATH` 绕过 Execution 的结果（`GATEWAY_DIRECT_PATH_BYPASS_FORBIDDEN`）**；
2. **核对点 2（Execution → Risk）**：核验不可变母单/透传意图已持久化至 Execution 日志（W2 起点）、`account_scope/strategy_scope/route/run_id` 与有效 `risk_operation_id`/`valid_until_ns` 一致；
3. **核对点 3（Risk 代理 → Gateway 交易 owner）**：核验调用方为受权 Risk 代理 principal（非被撤权的策略 principal）、作用域与代次有效、无 `FREEZE`/`DRAIN`/适用 `STOP_NEW`、`DISPATCHING` 先于原生报单落盘（W3 起点）。
