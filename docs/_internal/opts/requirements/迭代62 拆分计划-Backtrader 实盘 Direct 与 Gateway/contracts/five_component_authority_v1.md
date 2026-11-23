# 合同冻结件：五组件配置权威载体裁决 v1（T-010）

> 日期：2026-11-23　状态：**FROZEN_V1**
> 依据：已确认 `D62S-02`、`D62S-03`、`D62S-04`、`D62S-05`；关联需求 `R62S-05`；关联验收 `S-03`。

## 1. 唯一裁定结论

在设计文档 §6.3 三个候选中**唯一裁定方案 C（SDK 严格档位 + Gateway 签发 `GatewayReadinessProof`）**：

1. **策略配置层**：Backtrader 侧组合根（`backtrader/stores/btapi_composition.py`）先做严格静态校验（拒绝缺失/弱化的 `risk`、`execution`、非 CTP 场所、`DIRECT_PATH` 旁路与混配日历），轨道二在 `bt_api_py/gateway_strategy_config.py` 新增 `parse_gateway_strategy_config(raw, *, profile="strict_five_component")`（保留既有默认档位不破坏 SDK 非 BT 调用方）；
2. **部署全备证明层**：Backtrader 策略进程**不读取运维服务部署清单文件 `service_config.yaml`**，也**不直连 Monitor/Runtime RPC**；改为在启动只读预检阶段消费 Gateway 签发的带代次只读快照 `GatewayReadinessProof v1`（轨道一通过中立协议 `GatewayReadinessProof` 与契约替身验证，轨道二由 `bt_api_base` + `bt_api_gateway` + `bt_api_py` 补齐真实 RPC 签发）；
3. **Runtime 监督层**：策略进程通过受管启动参数（`--run-id` / `--heartbeat-interval` / `--stop-request-file`）与 `GatewayReadinessProof.registered_run_id` 对齐证明自身处于 Runtime 监督之下（维持 `D66-02`，避免与 `bt_api_runtime` 产生循环依赖）。

## 2. 版本协商与预检四类错误分类（禁止互相伪装）

| 预检失败类别 | 有限错误码 | 触发条件 |
| --- | --- | --- |
| 网络不可达 / 超时 | `GATEWAY_READINESS_UNREACHABLE` | 传输层连接失败、超时或心跳未达，不判定为协议不兼容 |
| 认证 / 主体鉴权失败 | `GATEWAY_READINESS_AUTH_FAILED` | CURVE 密钥、peer 身份或 scope 签名核验不通过 |
| 已确认版本不兼容 | `GATEWAY_READINESS_VERSION_INCOMPATIBLE` | 对端明确回报协议/Schema 版本不在兼容集合内（启动硬拒，对齐 `D68-02`） |
| 组件未就绪 / 绕过风险 | `GATEWAY_READINESS_COMPONENT_NOT_READY` / `GATEWAY_PRINCIPAL_BYPASS_UNSAFE` | 五组件任一状态非 `READY`、`monitor_required` 非 `true`、或 `strategy_principal_has_submit/reserve` 非 `false` |
