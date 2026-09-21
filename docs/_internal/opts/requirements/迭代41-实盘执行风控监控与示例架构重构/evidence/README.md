# 迭代 41 证据目录

本目录只保存脱敏、可重放的计划与验收制品；不得保存本地 `config.yaml`、`.env`、密码、API secret、
完整账户标识、approval capability、恢复 token、原始成交敏感字段或可用于重新授权的材料。策略目录的
`config.yaml` 可以按严格 schema 保存本地凭据，但必须被 `.gitignore` 忽略；本目录和 Git 只允许保存无秘密
的 `config.example.yaml`。

建议制品命名：

```text
baseline-<repo>-<commit>-<yyyymmdd>.json
submodule-gate-<submodule>-<pin>-<yyyymmdd>.json
inventory-<commit>-<yyyymmdd>.json
contract-vectors-<version>-<yyyymmdd>.json
plugin-validation-<strategy-id>-<config-hash>-<yyyymmdd>.json
direct-route-<strategy-id>-<provider>-<yyyymmdd>.json
gateway-session-<profile>-<yyyymmdd>.json
gateway-transport-<adapter>-<profile>-<yyyymmdd>.json
fault-<scenario>-<commit>-<yyyymmdd>.json
monitor-checkpoint-<profile>-<yyyymmdd>.jsonl
migration-<example>-<commit>-<yyyymmdd>.json
external-<profile>-<yyyymmdd>.json
```

每份制品必须有 schema version、产生时间、Backtrader/SDK superproject/五个能力包身份与制品
hash、解释器、命令、模式、零写或外部写入
计数、脱敏失败码和相关测试 ID。外部原始资料由操作者保存在受管位置；本目录只保存其不可逆指纹和
审阅结论。

`plugin-validation-*` 适用于所有存在 `plugins` 配置的 route：它必须记录 canonical strategy runtime directory（可只保留
不可逆路径/identity 指纹）、`config_schema_version`、仅含非秘密字段的 redacted configuration fingerprint、
`runtime.order_route`、`runtime.account_access`、五个 capability 的 enabled/attach matrix、profile/版本/pin/contract resolution、组合校验、
`config.example.yaml` 的无秘密扫描，以及本地 `config.yaml` 已被 ignore 且未追踪的结论。它不得保存原始
`config.yaml`、完整账户 ID、credential/profile 的敏感映射、密码、API key/secret、token、DSN、approval
capability 或恢复 token。

`direct-route-*` 用于证明选择了 `legacy_direct`，而不是 execution 失败后的 fallback：它记录 strategy/runtime
identity、`account_access`、provider 类型或 gateway profile、direct route 选择时间、enabled capability/attach result 和脱敏结果。
无插件 `legacy_direct + direct_provider` 不需要 execution journal；已启用 risk/monitor 的 direct receipt 必须记录实际
gate/control 状态。若选择 `gateway_client`，还必须证明 gateway + selected transport 成对、client 没有 provider credential，
且 server-side account authority 的 admission 结果由 gateway session evidence 记录。

`gateway-session-*` 记录共享 account/session 的非秘密 identity、server connection generation、subscription union、
fan-out consumer count、strategy/client-order correlation、tenant-isolation/anti-spoof proof、server-side admission state 与
snapshot/cursor/reconcile 状态；它不得包含 provider credential、完整账户标识或可重放 authorization。

`gateway-transport-*` 记录 selected adapter（本轮 `transport_zmq`）的 endpoint 非秘密 identity、security profile、
principal ACL proof、HWM/backpressure、write-gate state、transport sequence/gap/reconnect/snapshot/replay 状态和 provider
write count；不得记录 endpoint secret、provider credential 或可重放 authorization。它不能单独证明 gateway core、
execution 或 risk 已经实现。

`submodule-gate-*` 必须记录 `.gitmodules` 的 `installable` 值、pin、子仓是否含 `pyproject.toml`/`src/`/
`tests/`、默认安装的 `NOT_PACKAGED` 输出、strict 选择的非零退出，以及“未触发 PyPI fallback / ambient
editable import”的可重放断言。当前 execution 基线为 pin `2700cb5` 的空仓；gateway remote 尚未 package/attach，
transport_zmq 尚未创建，故三者的安全门证据均为强制项。
