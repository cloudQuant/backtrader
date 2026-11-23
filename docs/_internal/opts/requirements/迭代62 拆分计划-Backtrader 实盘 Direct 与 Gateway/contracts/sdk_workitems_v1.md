# 合同冻结件：轨道二跨仓 SDK 工作项登记表 v1（T-017）

> 日期：2026-11-23　状态：**FROZEN_V1（跨仓接口冻结，SDK 代码在 `D:/bt_api_py` 及其子仓按既定顺序实现）**
> 提交顺序：`bt_api_base` → 子仓 → `D:/bt_api_py` 父仓 gitlink → `d:/source_code/backtrader`。

| 编号 | 负责子仓 | 对应决定 | 核心内容与阻断说明 | 轨道一契约替身接口 |
| --- | --- | --- | --- | --- |
| `T-R2-01` | `bt_api_py` | `D62S-04`, `D62S-05` | `gateway_strategy_config.py` 新增 `profile="strict_five_component"`（拒绝 `risk:"none"`、`execution:"none"`、允许 `DIRECT_PATH` 配置） | BT 组合根先执行同口径静态校验 |
| `T-R2-02` | `bt_api_base` + `bt_api_gateway` + `bt_api_py` | `D62S-02`, `D62S-03` | 中立 `GatewayReadinessProof v1` DTO、Gateway 服务端签发与策略 principal 默认无 `SUBMIT`/`RESERVE` | `backtrader.stores.btapi_composition.GatewayReadinessProof` 协议替身 |
| `T-R2-03` | `bt_api_py` + `bt_api_gateway` + `bt_api_risk` | `D62S-01`, `D62S-04` | 打通 v2 Gateway journal 首创证明，解除 `gateway_api.py:869–873` `_risk_reserve()` 恒返 `UNKNOWN` 阻断 | 合成 fake Risk/Gateway 契约替身 |
| `T-R2-04` | `bt_api_py` + `bt_api_execution` + `bt_api_risk` | `D62S-01`, `D62S-05` | 实现 `risk_parent_port.py:126–137` `reserve_child()` / `dispatch_child()` 真实受权子单写路径 | 合成 fake Execution/Risk 契约替身 |
| `T-R2-05` | `bt_api_py` + `bt_api_execution` | `D62S-01`, `D62S-05` | 生产宿主 `execution_parent_service_host.py:397` 的 `AtomicIntakeService` 接入 `risk_port` 并满足 W2 先落盘母单再预留 | `S-04` W2 故障注入模拟 |
| `T-R2-06` | `bt_api_risk` + `bt_api_gateway` | 迭代 64 剩余门 | 补齐默认自成交检查 `R-05` 所需真实活动订单/回报共同切点数据与来源证明 | 轨道二合龙门禁 |
| `T-R2-07` | `bt_api_py` | `D62S-07` | `direct_api_assembly.py` + `bt_api.py` Direct strict 构造模式显式拒收 `market_runtime_factory` / `forwarding_config` / `transport_mode` / `execution_order_routing` | BT `DirectBtApiStore` 先行在框架边界拒收 |
| `T-R2-08` | `bt_api_runtime` + `bt_api_monitor` | `D62S-02` | 补齐迭代 66 007 监督启停、Windows B 类安全原语及迭代 68 五组件联合健康快照 | 轨道二合龙门禁（Gateway 实盘放行前置） |
| `T-R2-09` | `bt_api_execution` + `bt_api_py` + `bt_api_base` | **`D62S-05`（方案 A2）** | 为 Execution `PASS` 算法扩展市价/条件单透传支持（扩展 `D65-07`），并在严格 Gateway 档位禁止 `ExecutionOrderRouter` 返回 `DIRECT_PATH` 旁路 | `S-03a` 契约替身覆盖限价/市价/条件单 `PASS` 透传与 `DIRECT_PATH` 拒绝 |
