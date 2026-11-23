# 合同冻结件：有限错误码与迁移指引文案表 v1（T-016）

> 日期：2026-11-23　状态：**FROZEN_V1**
> 关联需求：`R62S-01`、`R62S-02`、`R62S-05`、`R62S-11`；关联验收：`S-01`、`S-08`。

| 错误码（ASCII 有限常量） | 触发条件 | 迁移指引摘要 |
| --- | --- | --- |
| `MODE_REQUIRED` | 实盘配置或组合根未显式提供 `mode` | 请显式指定 `mode: direct` 或 `mode: gateway` |
| `MODE_INVALID` | `mode` 非 `"direct"` / `"gateway"` | 仅允许 `direct` 或 `gateway`，不支持混合/占位模式 |
| `MODE_CONFLICT` | Direct 中出现 Gateway 键或跨模式键共存 | 请按模式分离配置，勿混用 `direct` 与 `gateway_strategy` |
| `PROCESS_MODE_CONFLICT` | 同进程先后装配不同实盘模式（`D62S-09a`） | 请为 Direct 与 Gateway 使用独立操作系统进程 |
| `DIRECT_SERVICE_KEY_FORBIDDEN` | Direct 出现 `market_runtime_factory`/`forwarding_config`/`transport_mode` | Direct 模式禁止接入远端服务/MarketHub，如需服务行情请迁至 Gateway 模式 |
| `LEGACY_HYBRID_ROUTING_RETIRED` | 传入 `service_client_config`/`gateway_client_config`/`execution_parent_port`/`execution_order_routing` | Direct+Execution 混合路由已退役；请先执行只读导出 `export-legacy-execution-routing` 并空仓迁移至 Gateway 模式 |
| `LEGACY_EXECUTION_PATH_RETIRED` | 传入旧直连 `execution_config`/`order_journal` 或 `managed_execution_adapter` | 请使用迭代 62 Direct 写入准入与 `live_state`，或迁至五组件 Gateway 模式 |
| `risk_requires_gateway` | Direct 配置中出现 `risk` | Risk 微服务仅用于 Gateway 模式 |
| `GATEWAY_CONFIGURATION_CONFLICT` | Gateway 出现 `exchange_kwargs`/`write_admission`/`ctp`/`direct`/`api`/`api_cls` 等直连键 | Gateway 模式禁止配置本地 provider 直连参数 |
| `GATEWAY_RISK_REQUIRED` | Gateway 缺失 `risk` 或 `risk == "none"`（`D62S-04`） | 严格 Gateway 模式必须绑定 Risk 服务 |
| `GATEWAY_EXECUTION_REQUIRED` | Gateway 缺失 `execution` 或 `execution == "none"`（`D62S-05`） | 严格 Gateway 模式必须绑定 Execution 服务 |
| `GATEWAY_DIRECT_PATH_BYPASS_FORBIDDEN` | Gateway 配置允许未命中回落 `DIRECT_PATH` 或运行时路由返回 `DIRECT_PATH`（`D62S-05` A2） | 严格 Gateway 全部订单必经 Execution（普通单走 `PASS`），禁止绕过旁路 |
| `GATEWAY_VENUE_UNSUPPORTED` | Gateway 模式配置非 CTP 场所（如 OKX/Binance，`D62S-08c`） | Gateway 首期仅支持 CTP（`D63-10`），OKX/Binance 请使用 Direct 模式 |
| `CALENDAR_SCOPE_CONFLICT` | Gateway 混配本地 `calendars.feed_scope` 或 `calendar_*` | Gateway 模式仅使用 `gateway_strategy.calendar_settings` 网络查询 |
| `RUN_BINDING_MISMATCH` | Feed/Broker 与 Store 的 `LiveRunBinding` 令牌/模式/作用域不匹配 | 请由同一组合根或同一 Store 工厂创建整套对象 |
| `GATEWAY_READINESS_UNREACHABLE` | 预检连接/超时失败 | 检查 Gateway 服务与 ZMQ 网络连通性，不降级不切 Direct |
| `GATEWAY_READINESS_AUTH_FAILED` | 预检 CURVE/主体鉴权失败 | 检查受保护密钥文件与注册 principal |
| `GATEWAY_READINESS_VERSION_INCOMPATIBLE` | 对端明确声明协议版本不兼容（`D68-02`） | 按版本矩阵升级对应服务组件 |
| `GATEWAY_READINESS_COMPONENT_NOT_READY` | 五组件任一状态非 `READY` 或 `monitor_required` 非 `true` 或 `--run-id` 失配 | 先使五组件全部就绪并由 Runtime 监督拉起策略 |
| `GATEWAY_PRINCIPAL_BYPASS_UNSAFE` | 就绪证明显示策略 principal 仍持 `SUBMIT`/`RESERVE`（`D62S-03`） | 在 Gateway 服务端账户配置中撤除策略 principal 的直接报单权 |
| `LIVE_STATE_MODE_MISMATCH` | `state/identity.json` 不可变 `mode` 与当前启动模式不符（`R62S-11`） | 禁止跨模式共用目录；空仓核验后新建目录或按审批流程迁移 |
| `LEGACY_EXECUTION_ROUTING_DB_UNEXPORTED` | 策略目录残留含未决记录的 `state/execution_routing.sqlite` 且未走审批清退 | 先执行 `export-legacy-execution-routing` 并取得项目/账户负责人书面审批 |
