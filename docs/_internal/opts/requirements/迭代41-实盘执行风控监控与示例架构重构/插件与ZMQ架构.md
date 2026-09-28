# ADR-41-08：可选运行时插件、共享账户网关与可插拔传输

状态：`PARTIAL_LOCAL_GATEWAY_PROOF / LIVE_NO_GO`
日期：2026-09-22（必需配置与三模式修订）
关联：[迭代 27 I27-20260921-34～37](../迭代27-在途工作落库与遗留问题修复/执行记录.md)、[需求文档](需求文档.md)、[设计文档](设计文档.md)。

## 结论

所有Iter41 runtime必须有`config.yaml`，用户只选择backtest、simulation、live及相容preset。
受信registry将预设展开为只读执行拓扑与能力配置，用户无需拼插件布尔值。缺文件立即拒绝，不进入默认直连。
live及允许外部报单的sandbox强制execution+risk+monitor；本地回测/回放零网络、零外部写。
未选中的gateway/transport等能力仍不import/init；插件可选性不等于启动配置可选性。

当前 local proof 已有 typed ZMQ client/server：client 只发送 `GatewayCommand/WireMessage`、明确丢弃
Store legacy dispatch callback，server 是 execution/risk/provider 的唯一派单方；timeout 成为 UNKNOWN。
这不是可部署 gateway：没有 Curve/ZAP/ACL、远端 endpoint、真实账户 principal/provider、订阅扇出、
snapshot/replay、隔离 consumer 或 CTP 写入证据。gateway cancel 在 sealed server-owned command 交付前必须拒绝。

共享一个账户、一个 provider 会话和一份行情订阅，再向多个策略扇出的能力独立命名为
[`cloudQuant/bt_api_gateway`](https://github.com/cloudQuant/bt_api_gateway)。它是**中间件无关的账户网关核心**：
负责共享会话、订阅复用、事件路由、策略命名空间、correlation/idempotency 与受限命令交付；它不是第二套 OMS、
风险账本或 provider 账户真相。

ZMQ 不再是 gateway 核心包名。首个传输实现是 `bt_api_transport_zmq`，runtime key 是 `transport_zmq`；未来若确有需求，才增加
`bt_api_transport_nats`、`bt_api_transport_redis` 等同一 port 的 adapter。2026-09-21 核验 SDK `d3674e19` 的
gateway 已挂载至逻辑路径 `bt_api/bt_api_gateway`，pin `44fd2fe26b51f1d8b573c84415a6cff660f33dea`，但仅有 README，
没有 package/wheel/consumer evidence，且 `.gitmodules` 缺 `installable=false`，状态为
`ATTACHED / NOT_PACKAGED / INSTALL_GATE_MISSING`；先修此安全门，不能继续沿用旧 `NOT_ATTACHED` 结论。
`bt_api_transport_zmq` 在该历史基线时尚未创建，状态为 `NOT_CREATED / NOT_PACKAGED`。当前工作树已有
local implementation/test，但两者都缺 package/wheel/consumer evidence，不得被当作已可交易能力。

## 1. 为什么要分为 Gateway 与 Transport

同一账户运行多个策略时，问题不只是“把消息通过 ZMQ 发出去”：还包括一个 provider connection generation、
一份订阅集合、策略/订单归属、账户/订单/成交的可恢复投影、命令 correlation、重复命令处理和每策略的权限范围。
这些是稳定的账户网关语义，不能跟随 ZMQ、NATS 或 Redis 的 API 改名。

因此分层如下：

```text
bt_api_gateway
  ├─ shared account/session registration and connection generation
  ├─ subscription union + market-data fan-out
  ├─ account/order/trade event normalization and strategy-scoped routing
  ├─ strategy/client-order correlation, idempotency, snapshots and cursors
  └─ command admission port (does not decide risk or execution policy)

bt_api_transport_zmq
  ├─ ZMQ sockets, framing, topics, Curve/ZAP integration
  ├─ backpressure, heartbeat, reconnect and transport sequence/gap signals
  └─ implements the GatewayTransport port only
```

`bt_api_gateway` 通过受限 provider port 接收来自 `bt_api_py` integration 的 adapter；它不反向导入 SDK、
Backtrader、具体 provider、execution、risk 或 monitor。provider 真相仍来自 provider query/callback 与受管
execution journal；gateway 的快照/路由索引只服务交付、恢复和对账，不得形成第二份可独立授权下单的账本。

## 2. 三模式、预设与派生拓扑

以下为 schema-v4 的**唯一权威模式/预设矩阵**。每个 Iter41 runtime 必须先读取配置；缺少配置返回
`CONFIG_REQUIRED`，零网络、零 provider write，不启动策略、provider client、worker 或 socket。
不再支持“无文件即 direct”“省略 plugins 即 direct”或“全部关闭后直接实盘”。

| 用户 mode | 用户 preset | 派生执行/账户拓扑 | 网络、写入与结果语义 |
| --- | --- | --- | --- |
| `backtest` | `local_backtest` | 本地 BackBroker；provider `order_route/account_access=null` | 只读已登记本地历史数据，零网络/零外部写；可以有 backtest 模拟成交/PnL，必须标为历史假设结果。 |
| `simulation` | `replay` | 本地具名 fixture/replay adapter；provider route/access=null | 离线零网络/零外部写；是否生成 hypothetical fills 由冻结 fixture schema 明示，公式 fixture 不冒充策略回测或成交。 |
| `simulation` | `paper` | 本地 paper broker；provider route/access=null | 只允许 profile 声明的公共行情读取，外部写=0；本地假设成交/费用/PnL 与交易所成交严格分列。 |
| `simulation` | `shadow` | observation-only adapter；provider route/access=null | 可读取 profile 允许的公共行情，外部写=0，fill=0，actual PnL 不适用；仅输出信号/就绪性/健康事实。 |
| `simulation` | `sandbox` | 默认认证后的私有只读会话，order_route=null；account access与demo/SimNow环境由registry固定。显式可写profile才派生managed_execution | 默认external write=0；可写profile必须三能力及独立sandbox receipt/admission才允许sandbox write，production write始终=0。沙盒成交不等于生产成交。 |
| `live` | `managed_live_direct` | `managed_execution × direct_provider`；独立 execution supervisor 持有唯一账户 authority | execution+risk+monitor 必选，正式环境 receipt/研究/账户/provider 准入全部通过后才可写；gateway/transport 不加载。 |
| `live` | `managed_live_gateway` | `managed_execution × gateway_client`；server 持有唯一账户 authority | execution+risk+monitor+gateway+transport_zmq 必选；server 再验证正式环境权限，client 无 provider credential。 |

前三模式是用户操作概念；direct/gateway 是派生账户接入拓扑，`managed_live_direct` 的 direct 只表示无共享网关，
**不是 legacy_direct**。当前无 live-direct/legacy-direct preset。旧 SDK direct API 继续作兼容测试对象，不能被
Iter41 runner 用作缺配置、预检失败、能力包缺失或插件关闭后的运行入口。

`runtime.mode` 与 `runtime.preset` 不匹配时返回 `MODE_PRESET_MISMATCH`。受信 registry 按
`strategy.id + preset` 绑定 provider/environment/profile 与参数 schema；缺少绑定返回 `PRESET_POLICY_VIOLATION`
（reason=`preset_not_bound`），
不尝试目录搜索、凭据推断或选择“最接近”的模式。不存在跨 mode 自动升级，sandbox 也不会因传入生产 credential
变成 live。旧 replay/shadow/demo/simnow/production 只能经显式迁移工具映射，不能作为 v4 mode 别名。

非 provider 模式中的 null 是“此项不适用”，不是 direct 默认。加载器不得为了补齐这些字段构造可写 BtApiStore。
market-data profile 只注入 read-only port；zero-write gate 必须同时存在于 SDK integration 和 provider dispatcher，
不仅限制 UI/CLI。报告分别记录 `external_write_count/production_write_count/sandbox_write_count/
hypothetical_fill_count`，以及真实/模拟 PnL 的 evidence kind；零外部写不能误写成零模拟成交。

sandbox允许014/015等在隔离测试环境做认证、账户/订单查询和SimNow准备，默认registry
`write_policy=deny`，只有read-only port，未启动三能力不影响其零写观察。只有operator显式登记的
`write_policy=receipt_required`沙盒profile才可请求写入，必须解析为managed三能力并绑定独立receipt。
缺receipt拒绝该write profile，不能静默改为只读；只读profile也不会仅因发现receipt而升级写入。
两个profile保持相同simulation/sandbox模式，区别由可信registry版本/hash与effective config明确记录；
用户parameters/CLI不能改变write_policy。读/写profile变更要停止会话、更新绑定并重新preflight。

```text
mandatory config → strict v4 schema → trusted preset registry → immutable effective config
    ├─ local_backtest/replay: local input → local adapter
    ├─ paper/shadow: read-only public market port → local adapter (no provider writer)
    ├─ sandbox default: authenticated sandbox private-read port (no provider writer)
    ├─ sandbox with write admission / managed_live_direct: SDK supervisor → execution+risk → admitted provider
    └─ managed_live_gateway: SDK managed client → authenticated gateway server
                               (intent only)         └─ ONE execution/risk authority
                                                          └─ admitted provider
```

gateway client 只提交 intent/证据并消费投影，不建立账户 journal/lease 或第二 execution session。
server 拥有唯一 plan/child/permit/dispatch/reconcile；client/server mode、environment、profile hash、receipt scope
不一致即拒绝，不能转成 server 的另一个模式。同账户多个策略必须加入同一账户 authority，或因 lease/policy
冲突拒绝；单个策略目录不可改变全账户 writer 或预算。

## 3. 必需配置与运行时加载合同（schema v4）

### 3.1 用户最小配置与预设

以下是已实现 schema-v4 config-first CLI 使用的通用最小配置形状，完整模板由[templates](templates/README.md)维护。模板本身不登记 runtime，也不授予交易准入；当前默认 registry 共 16 条：13 条 source/example runner 只允许 simulation/replay（11 条 nonmanaged replay：8 个普通策略、007/010 legacy no-action 与 sample no-action；以及 2 条 fake-provider managed L2）、1 条配置绑定的 CTP SimNow simulation/sandbox 私有只读 route（无 runner、无 execution capability）、1 条公开 OKX simulation/shadow 只读观察，以及 1 条 package-owned backtest/local_backtest fixture。SimNow 私有 config.yaml 已在本机受保护并通过离线 doctor；I2 artifact pin 仅限该只读 route。最新 I2 TD retry 的七项查询均终态完成但 native Join shutdown incomplete，完整只读 preflight 仍拒绝；独立 I2 MD-only 在 one-second teardown grace 后仍因 request_id_mismatch / zero request ID strict reject，无 ACK/tick、零写入。当前 I2 provider/runtime/SDK 证据见[验证汇总](evidence/validation-summary-2026-09-24.md)。CTP live profile 未登记，默认 registry 尚未接入同一 CTP runner 的 live-mode dispatch。backtest fixture 是本地机械验收，不提供 live 或一般部署路线。

```yaml
config_schema_version: 4
strategy:
  id: example.strategy-id
runtime:
  mode: backtest
  preset: local_backtest
```

用户 schema 只接受上述版本、身份、模式、预设和可选 `parameters`、`secrets_ref`。dataset、candidate、策略入口、
默认参数及其 hash 通过受信 runtime registry 绑定；策略-specific 参数仅按其已登记 schema 读取。
普通用户不填写 `order_route/account_access/plugins/connection`，更不手工组合 10 个布尔值；提交这些 v3
控制字段返回 `CONFIG_SCHEMA_UNSUPPORTED`（reason=`field_not_allowed`）。高级参数只可调已声明策略参数或收紧风险上限，不能改变 mode、
preset、route/access、能力启用状态、账户环境或扩大写权限。

`secrets_ref` 只接受受信 secret registry 的不透明逻辑引用，不能包含凭据值、任意路径/URL、环境变量表达式或
Python import；backtest/replay/paper/shadow 的当前 preset 不接收 provider trading secret。sandbox/live 的引用
必须与已绑定 provider/environment/account 匹配；gateway client 只能持 client-auth 引用，provider secret 留在
独立 server/supervisor secret store。凭据读取在静态模式/schema/供应链检查之后，且不构成交易授权；配置文件
无论用户版还是服务端版均不存密钥原值。

预设是版本化、hash 绑定的已审核配置，不是模型生成的建议。registry 展开只读 `EffectiveRuntimeConfig`，包括
用户 config digest、preset version/hash、strategy/artifact/profile/candidate、execution adapter、mode/environment、
route/access、五能力 `enabled/required/config`、write policy、data source、参数与秘密引用的脱敏指纹。
这些 enabled/required 字段是运行时实现事实，不是第二套用户配置；所有需要的能力均为 true/true，冲突或缺包
必须失败。未使用的能力 false/false 且不 import/init；不能把导出 effective config 当成用户文件重新读入。

v4 的 local_backtest/replay 基础预设可不加载五个能力包，但 runner 仍先验证必需配置、注册身份和模式。升级到
paper/shadow 只增加已允许的 read-only 数据 port；可写sandbox/live 必须在三能力全部 attach 并验证账户 owner 后才
获得写 capability。没有 config 的零 import 是拒绝路径；有合格本地预设的零 import 才是成功运行路径。

### 3.2 两步启动与诊断

1. `bootstrap --strategy-dir <dir>` 已是配置生成操作：选择合法 mode/preset 并使用审核模板，写入前验证；
   以原子创建生成 `config.yaml`，已有文件绝不覆盖，默认不包含 secret、不连接 provider。
   已有文件返回`CONFIG_EXISTS`，原文件字节不变；并发 bootstrap 仅一个可原子创建成功。
   `bootstrap --runtime-set <审核名称>` 只接受 registry 固定集合，先预检全体，再逐目录原子创建；已有完全匹配文件跳过，
   内容不同明确冲突且不写入其他缺失目标。两种生成操作都不运行策略，也不能生成可写 live 默认值。
2. 当前 `run --strategy-dir <dir>` 重新校验配置、解析 sealed preset policy，再调度代码登记的 runner；它不执行
   provider/account preflight。`run` CLI 只选择运行目录，不提供 `--mode/--preset/--config` 或环境变量覆盖。
   配置无效、缺失或适用的 receipt 过期即停止并给出稳定原因码。CTP SimNow 账户/行情只读检查由单独的
   `preflight` 命令执行，必须先有代码登记的 binding 与受审 SDK pin；当前默认 registry 已登记配置绑定的
   CTP SimNow `simulation/sandbox` 私有只读 binding，但该 route 无 runner、无 execution capability。较早的
   `config.yaml` 缺失和约 10:53 UTC 的 SDK-origin gate 都是历史时点；当前配置含五组 sealed `front_pairs`。当前 I2 TD retry 七项 query 完成但 native Join 关闭不完整；I2 MD-only 在 one-second teardown grace 后仍因 request_id_mismatch / zero request ID strict reject。当前证据与 runtime/SDK 测试见[验证汇总](evidence/validation-summary-2026-09-24.md)，不授予 live/write route。
   `doctor` 离线通过。F 的 base+CTP 两个 code-owned pins 经独立 scoped review，仅供该只读 route；隔离 F pin
   dry run 通过。此前 F/G/H2 状态均为历史；I2 TD retry 的七项 native query 已完成，但 Join shutdown 仍不完整；独立 I2 MD-only 在 one-second teardown grace 后仍因 zero request ID 无法安全关联而 strict reject。当前结果见验证汇总。Managed 仍为 NO_PIN / NO_WRITE；production/live profile 未登记，亦未接入同一 CTP runner 的 live-mode dispatch。
   exact-target query 返回 83 条同交易所行，仅一条匹配目标，strict every-row gate 报
   `query_row_instrument_mismatch`，随后 Join shutdown incomplete，整体 preflight `FAIL`。完整 preflight 的 MD 阶段未运行；独立 MD-only provider 登录 15 秒超时报 `market_login_timeout`，无订阅/tick、Join pending/关闭未知、写入为零。
   managed 所需第三 `bt_api_py` parent pin 仍缺，managed 为 `NO_PIN / NO_WRITE`；production/live profile 未登记，也未接入同一 CTP runner 的 live-mode dispatch。
   模式切换必须修改配置后重新预检，涉及已有 writer 时先 freeze/drain/stop，不能热切至更高权限。

`validate` 为零网络、零外部 secret-store 访问的静态检查；受审 CTP 私有路径需在权限预检后读取本地
`config.yaml` 并脱敏。`doctor` 已展示有效 mode/preset、目的地、写/PnL 边界和下一条安全命令；普通路径
缺配置提示 bootstrap，CTP 私有路径提示准备受保护配置，默认同样离线。完整包/平台供应链就绪性仍属于后续 deployment preflight，
不得把 doctor 的本地摘要当作它已经完成。显式 `preflight` 才执行该 preset 允许的只读身份/连接检查，始终不报单/
撤单；当前 CTP `preflight` 只接受代码登记的私有只读 route，backtest/replay 的 `run` 不连接 provider。
输出原因码、YAML field path、脱敏实际值/允许值和下一步，不能只打印异常堆栈。`doctor` 展示解析后的模式、
目标环境、写入边界与下一条安全命令；`run` 在配置/preset policy 校验后调度现有 runner。live 确认只批准已绑定配置，
不选择或覆写 mode。完整 deployment/account preflight 仍是未完成的交付与验收项。

| 稳定错误码 | 触发与最低断言 |
| --- | --- |
| `CONFIG_REQUIRED` | 缺文件；零网络、零provider write，提示bootstrap/配置位置。 |
| `CONFIG_SCHEMA_UNSUPPORTED` | 空/非mapping/旧v3/未知或重复字段/缺必填字段；带field path+reason，零网络。 |
| `MODE_PRESET_MISMATCH` | 三模式与所选preset不匹配；禁止自动改成相容mode。 |
| `PRESET_POLICY_VIOLATION` | registry未绑定、不可信、live派生legacy route、缺必需能力或override扩权；拒绝启动。 |
| `ENVIRONMENT_MISMATCH` | secrets_ref/只读认证身份与已绑定sandbox/production环境不符；零provider write，禁止换mode重试。 |
| `CONFIG_EXISTS` | bootstrap目标已存在；不覆盖、不自动合并秘密或模式。 |
| `MIGRATION_REVIEW_REQUIRED` | 离线转换不能证明原mode/环境/参数的一一映射；输出待审差异，不执行runner。 |

### 3.3 定位、迁移与加载顺序

每个 Iter41 runtime 都登记唯一 canonical `<strategy-runtime-dir>/config.yaml`；缺文件统一
`CONFIG_REQUIRED`，空文件/非mapping/重复字段/未知字段/错误版本均拒绝。仅显式 runtime-dir 定位，
不搜索 CWD、父目录、模板或任意 `--config`，不读取 YAML include、env interpolation 或动态对象。
现有 tracked 策略参数 `config.yaml` 保留源码与 Git tracking；冲突示例新增独立 runtime-dir，由 registry
绑定旧参数 artifact/hash，不能把旧文件当新启动配置或全仓 ignore 同名文件。

schema-v3 的插件布尔输入及更旧 v2/modules/zmq 输入全部拒绝。唯一升级途径是显式迁移工具：
读取旧配置/CLI mode → 生成合法 v4 mode/preset+参数绑定候选 → 展示权限与语义差异 → 验证后原子写入新目录；
无法一一映射则 `MIGRATION_REVIEW_REQUIRED`，不猜测 live/sandbox 目标，不复制旧 receipt。
旧 mode 与 `--mode` 的行为只作为迁移清单和旧版本回归基线，不能继续控制已迁移 runtime。

加载顺序固定为：`runtime注册定位 → 必需文件安全打开 → v4严格schema → mode/preset映射 → 可信registry/
artifact seal → immutable effective config → enabled descriptor manifest → wheel/hash/schema兼容 → 构造/attach
→ 允许的read-only preflight → receipt/readiness → start/dispatch`。static错误零网络/零provider I/O；
只读preflight可能有网络但失败仍零provider write，不作虚假的“全部preflight零I/O”声明。

`bt_api.plugins` 仍是旧 exchange/provider discovery，不作为安全 composition。新增 `RuntimePluginManager`
与 `bt_api.runtime_plugins` 只加载 effective config 选择的能力；manifest绑定issuer allowlist、
distribution/version/wheel hash/module/entrypoint digest和contracts范围，恶意同名、editable/user-site歧义拒绝。
selected gateway必须成对加载gateway+恰一个受支持transport（本轮ZMQ）；direct provider不加载二者。
NATS/Redis未实现时拒绝，不fallback。attach输出实际gate/control状态，telemetry不算hard gate；失败逆序清理，
不留下半启动writer。G1/G2是manager/registry/hooks唯一实现owner；B7冻结port/composition前提。

## 4. 共享账户网关合同

| Gateway surface | 必须做什么 | 不得做什么 |
| --- | --- | --- |
| Market subscription registry | 对同一 account/provider/session 计算订阅并集，维护每策略 topic/symbol 权限，向每个消费者扇出带 generation/sequence 的行情。 | 把订阅缓存当作行情完整性或订单事实证明。 |
| Private-event router | 为 account/order/trade 事件附加 account fingerprint、connection generation、sequence、source timestamp；按 stable `strategy_id`、client ID、order correlation 交付。 | 靠 symbol 或本地 order ref 猜测多个策略的订单归属。 |
| Command router | 把 submit/cancel/query 转为经过 authentication/ACL、idempotency/correlation 和 server-side admission 的命令。 | 因 client 提供 account/strategy 字段而授予写权限，或直接绕过 execution/risk。 |
| Snapshot/recovery | 在 gap/reconnect/late consumer 后提供带high-watermark的snapshot、绑定principal/scope的cursor与replay port，重建完成后才恢复live消费。 | 用PUB/SUB或旧ack缓存替代journal/query；把snapshot请求成功等同于账户事实完整。 |
| Tenant isolation | 为 strategy、candidate、account/environment、instrument/topic 和 command scope 建立 allowlist。 | 允许一个 strategy 读取、撤销或关联另一个策略的订单。 |

每一个 gateway server 绑定一个明确的 account/environment/provider profile；多个策略只能作为已认证 clients 连接。
是否共享一个进程由 deployment profile 决定，但“同一账户一个写入 owner / session generation”不能被多个
strategy-local gateway 绕过。

## 5. Package dependency 与发布边界

```text
bt_api_base                         shared typed contracts; no transport dependency
       ▲
bt_api_gateway                      middleware-neutral gateway contracts/core
       ▲
bt_api_transport_zmq                ZMQ implementation; owns pyzmq dependency
       ▲
bt_api_py[gateway-zmq]              optional integration extra; injects provider ports

bt_api_execution / bt_api_risk / bt_api_monitor
       └─ depend only on compatible public contracts, never on a concrete transport
```

依赖方向以“上层依赖下层”为准。`bt_api_gateway` 不得依赖 `bt_api_py`；`bt_api_transport_zmq` 不得拥有 provider
client、execution journal 或 risk ledger。`bt_api_py` 可通过 provider port 将其现有 adapter 接入 gateway server，
但旧 `forwarding` / base gateway public APIs 在迁移期只能是有期限、**懒导入** compatibility facade。未启用
gateway/transport 的 core/direct runtime 不得因为 import 而需要 `pyzmq`。

`bt_api_gateway` 已有submodule pin，但尚未package，必须先补 `installable=false`；具备`pyproject.toml/src/tests`、
wheel、审阅提交与isolated consumer evidence后才可切为installable。transport_zmq尚未创建，未来创建时同样先设
安装安全门。repository URL/logical path/pin是可迁移身份，`D:/bt_api_py`只是本次resolved checkout。
NATS/Redis不提前创建空子仓。shared DTO/serialization/port固定放现有`bt_api_base`，不能再留“另建contracts包”分叉。

## 6. ZMQ 的可靠性、安全与 CTP 边界

本节为待实现wire v1合同；当前代码依据为SDK `forwarding/schema.py`、`state.py::SQLiteStateStore`、
`router.py::OrderRouter`、`transport.py::{ZmqCommandServer,ZmqCommandClient}`，以及
base子仓`src/bt_api_base/gateway/runtime.py`、`runtime_remote.py`。既有decimal字符串、请求fingerprint、
write-disabled gate和ROUTER/DEALER是迁移基础，不等于以下合同已满足。A5/G3须提供逐字段旧→新迁移vectors，
明确废弃字段和不支持组合，不能兼容不了时私建第三种协议。

### 6.1 Envelope、命令与响应

| 项目 | v1冻结规则 |
| --- | --- |
| serialization | UTF-8 canonical JSON；拒绝duplicate/unknown fields、不支持的major、NaN/Infinity、任意对象/pickle和不受限`extra`。数量/价格/金额为有限decimal字符串，时间UTC整型单位显式，单消息≤1,000,000bytes（沿现有MAX_MESSAGE_BYTES）；分页≤1000项且仍受字节上限。 |
| envelope | `protocol_version/message_type/message_id/correlation_id/stream_id/server_epoch/connection_generation/sequence/source_time/receive_time/payload`；command另有`command_id/idempotency_key/request_fingerprint/issuer_sequence/deadline/receipt_digest/expected_revision/runtime_mode/preset_digest/effective_config_digest`。server从认证session派生principal/scope，核对模式/环境/receipt绑定，不相信payload自报权限。 |
| topic | 行情按provider/instrument/type；私有事件按opaque tenant/account/strategy scope。客户端只持allowlist topic；禁止完整账户ID/secret进入topic。symbol normalize仅用于格式，不能用symbol猜订单归属。 |
| command channel | DEALER收发恰一个JSON payload frame；ROUTER收发恰两个frames `[routing_identity,payload]`；事件PUB/SUB恰两个frames `[UTF8_topic,payload]`，其他frame拒绝。transport identity不是principal，服务端经认证映射。相同socket只由同一I/O线程创建/使用/关闭，通过mailbox交接；stop/reconnect不跨线程直接操作socket。 |
| response | `RECEIVED`（仅交付）、`DURABLY_ACCEPTED`（唯一owner已记账、仍未等于provider接受）、`REJECTED`、`UNKNOWN`；最终provider ACK/fill/cancel为独立event，绑定原command/intent/order。`accepted=true`不能制造fill或风险退款。 |
| compatibility | 先read-only协商schema/capability/profile/owner；未知major或无法验证pin立即拒绝写channel。minor仅允许已声明、已测试且不改变权限/金额语义的变化；不能盲目忽略安全字段。 |

命令响应必须逐条核对correlation/command ID、principal scope、fingerprint、server epoch与expected owner；
超时后晚到ACK只归原命令，不被下个请求消费。client可并发请求但必须维护有界pending表，不能用“清空socket残留”
代替关联。query/cancel要验证所属strategy与明确order identity；跨策略cancel-all默认拒绝，账户operator能力另授权。

### 6.2 幂等与唯一发送者

client在发送前保存pending outbox的完整intent/signal payload与稳定key，收到绑定的durable admission ACK才推进
已处理cursor；重启按设计§9.3查原key/join，完整权威证明不存在才重送同key。server以
`authenticated account/environment + principal/strategy scope + idempotency_key`定位，绑定canonical request fingerprint。
同key/同body只返回原状态，不产生新provider write；同key/不同body为`IDEMPOTENCY_CONFLICT`。
nonterminal/UNKNOWN项永不因TTL自动删除；终态key tombstone至少覆盖admitted replay window及provider最大对账窗口，
两者数值随profile冻结，保留期耗尽只能拒绝过期命令或要求新proposal，不能当新单执行。

managed server在一个账户事务中写command→intent关联、风险reservation、dispatch claim与outbox后才返回
`DURABLY_ACCEPTED`。gateway delivery表只保存引用/交付状态，不独立决定订单terminal或释放额度。
v4可写gateway只接收受管sandbox/live与全部必需能力，不存在未启用execution仍可写的direct preset。
旧direct forwarding/risk记录仅作为迁移输入与历史兼容fixture，不能据此创建v4写入口。
既有forwarding.SQLiteStateStore中的command ACK/private events须映射到新的交付投影，不复制为另一个execution journal。

timeout表示结果未知，不表示provider未收到。client不得重发新的command/intent；通过同identity的`query_command`
读取server权威状态。server在恢复时查询provider/execution journal；只有确认未派发且claim未消费才允许发送。
server已发但失联时不允许client升格本地provider或接管账户。`UNKNOWN`恢复所有权仅归server的execution authority；
测试需覆盖持久化前后、发送前后、ACK前后和server重启，而不是只做socket重连。

### 6.3 Snapshot、cursor与私有事实重建

consumer持久cursor至少绑定 `principal/scope/stream/server_epoch/last_applied_sequence/schema`，服务端校验签名或
opaque token与expiry；更换账户/策略/凭据epoch时旧cursor不可复用。协议不要求暴露其他tenant的全局sequence。
private stream的sequence连续性由账户authority投影到scope后维护，不能将授权过滤产生的缺号误判为丢包。

恢复barrier按如下顺序：

1. consumer进入`CATCHING_UP`并停止alpha增加风险，记录最后可靠cursor；server为授权scope取得原子snapshot，
   包含source/revision、high-watermark S、generation、schema、完整性/分页证据与content hash。
2. 在本地冻结投影中安装snapshot，缓冲后续事件；请求从S+1开始的durable replay，按sequence/event ID去重连续应用。
   分页中generation变化、页缺失、hash冲突或日志已截断都废弃本轮，重新snapshot或provider reconcile。
3. 应用到server确认的live barrier并验证订单/成交/仓位守恒后，原子提交projection+cursor，再切`LIVE`。
   未完成前不得输出fresh=true或清除freeze；恢复的是读投影，不是新交易授权，仍需preflight。

没有provider完整查询或durable source能补齐的私有gap保持`RECONCILIATION_INCOMPLETE`；不能用当前balance
覆盖缺失fills后宣称完整PnL。market book采用snapshot+增量连续校验；bar/tick恢复仍需warmup与数据manifest。
snapshot、replay、行情缓存都不得创造订单成交，风险与实际funding事实缺失保持unknown/pending。

### 6.4 失效关闭、安全与配额

PUB/SUB 只可作有损 fan-out：late join、断线和慢消费者都可能丢消息。订单/成交/账户真相必须依赖 provider query、
execution journal、cursor、gap detection、snapshot/replay 与 reconcile；命令 timeout 必须进入 `UNKNOWN`，由
idempotency key、journal 和 provider query 收敛，不能盲目重发。

本轮首发 `bt_api_transport_zmq` 固定CurveZMQ+ZAP（含loopback写通道）；不以未实现的“等价mTLS”代替交付。
需要endpoint allowlist、principal 到
account/strategy/topic/command 的授权、key rotation、redaction 与审计。`allow_remote=True` 不是 authentication。
`enable_trading` 仅是 gateway command-channel 的默认拒写门：同进程若直接持有 provider adapter 仍可能绕过它，
所以它不能替代 process isolation、ACL 或 server-side risk/execution admission。

Curve认证后服务端以ZAP principal匹配签名allowlist；credential epoch轮换/撤销使旧session/cursor/command失效。
strategy YAML不能启动server或指定account authority/policy；server从独立受管部署配置注入凭据与provider port。
Windows默认 `tcp://127.0.0.1:<port>` + Curve profile，拒绝未认证的 `tcp://*`/remote写通道；loopback本身不是认证。
Linux IPC只有路径权限、owner及重连fixture通过才可选择，不强制Windows使用IPC。

参考容量profile固定：每principal≤64 outstanding commands、≤32 subscriptions、replay page≤1000项、
单consumer mailbox≤10,000 events且≤64MiB，任一先到即触发backpressure。命令超额在派发前返回
`RESOURCE_EXHAUSTED`，不能先接单再静默丢弃；read/replay限流独立于账户writer，恶意client不能耗尽其他strategy预算。
private queue overflow标记该scope `STALE/CATCHING_UP`并冻结增加风险，恢复按§6.3；若owner自身journal/outbox无法持久化
则账户级freeze。行情只可丢弃已允许latest-only的完整快照，并计数说明；增量流overflow必须断开并重新同步。
HWM、queue bytes、worker budget、timeout、heartbeat和shed计数都进入health/验收，不以无限队列隐藏故障。

freeze/drain仍按设计§9.2的OR/AND、durable command dedupe与target confirmation语义。gateway server是存活的
账户owner时可执行预授权处置；server也死亡/未知持仓时只能升级人工，不能由transport自行补偿。AI observer只读、
principal权限与actor审计按设计§12执行，不能因客户端称自己是“operator/AI”授予额外能力。

CTP gateway 写入在 direct CTP 会话、session generation、TradingDay、settlement、approval、query/reconcile 的
独立端到端验收前保持 `NOT_SUPPORTED`。ZMQ loopback、mock 或 SimNow connect smoke 均不能升级为 production CTP 资格。

## 7. 迁移与验收重点

1. 冻结 `cloudQuant/bt_api_gateway` 的 package skeleton、公开 contracts、pin 与 isolated wheel consumer；
2. 新建并验收`bt_api_transport_zmq`，证明有效non-gateway preset不import pyzmq、gateway preset只加载ZMQ；
   缺config必须CONFIG_REQUIRED零网络拒绝，不能把零import当成功启动；
3. 一个 gateway server + 两个以上 strategy clients 证明一个市场订阅、一条 account session、可区分的 strategy/order
   routing 和不跨租户的 cancel/query；
4. 两种live及可写sandbox profile均强制真实risk hard gate与monitor control；伪造preset省略必需能力在provider write前拒绝；
5. managed execution 没有 execution package/pin 时零 I/O 拒绝，且不 fallback direct；
6. ZMQ 默认 write-disabled 下 place/cancel/cancel-all 的 provider write count 均为零；authentication/ACL 缺失的
   remote endpoint 不得启动写通道；
7. reconnect、duplicate、timeout、late ack、PUB/SUB gap、slow consumer、server restart 和 provider generation change
   都必须有 deterministic negative tests；
8. NATS/Redis 只能在另有实际需求、独立 contract vectors、security/recovery 验收后新增，不得影响 ZMQ 的 canonical
   gateway contracts。
9. cross-wheel无checkout/ambient依赖验证gateway core不import pyzmq；base旧facade/direct import也通过零transport
   import测试。现有write-disabled兼容门通过只证明旧入口安全，不代表新gateway完成。
10. wire vectors覆盖duplicate/unknown字段、decimal/大小限制、晚到ACK错配、idempotency冲突/保留期、snapshot分页
    generation变化、授权过滤sequence、cursor跨tenant/credential重放、queue overflow、server fence切换和权限撤销。
    每例记录owner、实际provider write计数、journal/cursor/额度最终状态；不能用“连接成功”代替端到端恢复证据。
11. v4配置矩阵覆盖所有mode/preset配对、缺文件/旧v3/未知字段、CLI/env覆写、secrets_ref错环境、bootstrap覆盖拒绝、
    doctor脱敏建议、readonly effective config注入；sandbox的production write=0与paper的hypothetical fill非零分开验收。
