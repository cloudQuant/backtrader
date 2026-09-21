# ADR-41-08：可选运行时插件、共享账户网关与可插拔传输

状态：`PLANNED / NO-GO`
日期：2026-09-21
关联：[迭代 27 I27-20260921-34～37](../迭代27-在途工作落库与遗留问题修复/执行记录.md)、[需求文档](需求文档.md)、[设计文档](设计文档.md)。

## 结论

`bt_api_execution`、`bt_api_risk`、`bt_api_monitor` 继续是按策略运行目录显式加载的运行时插件：未配置或
`enabled: false` 时不导入、不构造、不启动 worker，也不改变既有 Backtrader 直连下单。已启用的 risk/monitor
即使位于 `legacy_direct`，也必须在真实 Broker/Store 写入或控制边界发挥 hard-gate/freeze/drain 作用。

共享一个账户、一个 provider 会话和一份行情订阅，再向多个策略扇出的能力独立命名为
[`cloudQuant/bt_api_gateway`](https://github.com/cloudQuant/bt_api_gateway)。它是**中间件无关的账户网关核心**：
负责共享会话、订阅复用、事件路由、策略命名空间、correlation/idempotency 与受限命令交付；它不是第二套 OMS、
风险账本或 provider 账户真相。

ZMQ 不再是核心包名或 runtime plugin 名。首个传输实现是 `bt_api_transport_zmq`；未来若确有需求，才增加
`bt_api_transport_nats`、`bt_api_transport_redis` 等同一 port 的 adapter。当前 gateway GitHub 仓库已创建，但尚未
具备 package skeleton、wheel、submodule pin 或 consumer evidence，状态为 `NOT_PACKAGED / NOT_ATTACHED`；
`bt_api_transport_zmq` 也尚未创建，状态为 `NOT_CREATED / NOT_PACKAGED`。两者都不得被当作已可交易能力。

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

## 2. 拓扑与两条执行路由

```text
No config / all runtime plugins disabled and required:false
    Strategy → BtApiBroker → BtApiStore → bt_api_py/provider → provider

Enabled gateway client (one account gateway shared by strategies)
    Strategy A ─┐
    Strategy B ─┼─ Broker/Store → bt_api_py integration → bt_api_gateway client
    Strategy C ─┘                                      │
                                                        └─ bt_api_transport_zmq
                                                               ⇅
                                                    bt_api_gateway server
                                                        │  one provider session,
                                                        │  one subscription union
                                                        ▼
                                                    provider

managed_execution is orthogonal to transport:
    Broker adapter → bt_api_execution → provider dispatch port
                         ├─ optional bt_api_risk gate/reservation
                         ├─ journal/outbox/recovery
                         └─ immutable events → optional bt_api_monitor
```

`runtime.order_route` 仍只表达 execution route：`legacy_direct` 或 `managed_execution`。`runtime.account_access`
单独表达拓扑：`direct_provider` 或 `gateway_client`。启用 gateway client 不把 direct 伪装为 managed，也不自动授予
写权限。使用 gateway 的 client 侧 risk/monitor 不能充当账户级权威；若 gateway server 接受 provider 写入，所需的
risk/execution admission 必须在该 server-side write boundary 再次执行。

## 3. 运行时加载合同（schema v3）

`bt_api.plugins` 仍只用于 exchange/provider discovery，不能复用为策略级安全 composition。`bt_api_py` 新增
`RuntimePluginManager`，仅在核心 schema 已确认 `enabled: true` 后加载 execution/risk/monitor/gateway/transport_zmq
descriptor。只有 gateway 已启用且 transport 配置通过验证后，才允许加载 `bt_api_transport_zmq`。

```yaml
config_schema_version: 3

runtime:
  order_route: legacy_direct          # legacy_direct | managed_execution
  account_access: direct_provider     # direct_provider | gateway_client
  mode: shadow

plugins:
  execution:
    enabled: false
    required: false
    config: {}
  risk:
    enabled: false
    required: false
    config:
      enforcement: hard
  monitor:
    enabled: false
    required: false
    config:
      on_unhealthy: freeze_new_entries
  gateway:
    enabled: false
    required: false
    config:
      role: strategy_client           # strategy config may not start account_gateway
  transport_zmq:
    enabled: false
    required: false
    config:
      security_profile: local-ipc-v1
```

规则：

1. 缺少 `config.yaml`，没有 `plugins`，或所有 plugin disabled 且均 `required:false`：保留本地 direct path，
   零 runtime-plugin/transport import。`required:true && enabled:false` 是配置错误。
2. `execution.enabled=true` 必须搭配 `order_route=managed_execution`；managed 也必须启用 execution。失败绝不
   回退 direct。
3. risk/monitor 可单独或共同用于 direct；attach 成功后分别是 hard gate/control plane，而不是 advisory。
4. `account_access=gateway_client` 必须令 gateway 与恰一个实现的 transport plugin enabled；v3 仅允许
   `transport_zmq`。`transport_zmq.enabled=true` 也必须令 gateway enabled。反之 `direct_provider` 不得启动 gateway
   或任何 transport。
5. gateway client 只能连接已部署的 account gateway，不能从策略配置取得 provider secret、启动 provider session 或
   以 endpoint/client field 自行授权账户写入。gateway server 使用独立受管 deployment config；provider credentials
   仅在 server 的受管 secret source 中可见。
6. 任一 enabled plugin、gateway distribution 或 selected transport 的 descriptor/package/pin/schema/attach/preflight
   失败，均在 provider I/O 前失败；`required:false` 不降低此要求。
7. NATS/Redis 是未来 distribution 名称，未实现前必须在零 I/O 前拒绝，而不是通过 fallback 偷换协议。

schema v2 的 `plugins.zmq` 已废弃：它混淆了账户网关语义和 ZMQ 实现。唯一允许的迁移是显式 v2→v3 工具：
`plugins.zmq.config.role` 映射至 `plugins.gateway.config.role`，endpoint/security 参数映射至
`plugins.transport_zmq.config`；旧配置不能被 loader 猜测兼容。

## 4. 共享账户网关合同

| Gateway surface | 必须做什么 | 不得做什么 |
| --- | --- | --- |
| Market subscription registry | 对同一 account/provider/session 计算订阅并集，维护每策略 topic/symbol 权限，向每个消费者扇出带 generation/sequence 的行情。 | 把订阅缓存当作行情完整性或订单事实证明。 |
| Private-event router | 为 account/order/trade 事件附加 account fingerprint、connection generation、sequence、source timestamp；按 stable `strategy_id`、client ID、order correlation 交付。 | 靠 symbol 或本地 order ref 猜测多个策略的订单归属。 |
| Command router | 把 submit/cancel/query 转为经过 authentication/ACL、idempotency/correlation 和 server-side admission 的命令。 | 因 client 提供 account/strategy 字段而授予写权限，或直接绕过 execution/risk。 |
| Snapshot/recovery | 在 gap/reconnect/late consumer 后提供 cursor、snapshot request、dedupe 和 provider/execution reconcile 入口。 | 用 PUB/SUB 内存队列替代 durable journal/provider query。 |
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

`bt_api_gateway` 已创建为 public GitHub repository，但尚未 package；只有具备 `pyproject.toml`、`src/`、`tests/`、
wheel、审阅提交与 consumer evidence 后，才可加入 `D:/bt_api_py/bt_api/` 并记录 `.gitmodules` pin。首个
`bt_api_transport_zmq` 也必须满足同样的 `installable` 安全门。未来 NATS/Redis adapter 不提前创建空子仓。

## 6. ZMQ 的可靠性、安全与 CTP 边界

PUB/SUB 只可作有损 fan-out：late join、断线和慢消费者都可能丢消息。订单/成交/账户真相必须依赖 provider query、
execution journal、cursor、gap detection、snapshot/replay 与 reconcile；命令 timeout 必须进入 `UNKNOWN`，由
idempotency key、journal 和 provider query 收敛，不能盲目重发。

远端 `bt_api_transport_zmq` 需要 CurveZMQ/ZAP 或等价 mTLS/ACL、endpoint allowlist、principal 到
account/strategy/topic/command 的授权、key rotation、redaction 与审计。`allow_remote=True` 不是 authentication。
`enable_trading` 仅是 gateway command-channel 的默认拒写门：同进程若直接持有 provider adapter 仍可能绕过它，
所以它不能替代 process isolation、ACL 或 server-side risk/execution admission。

CTP gateway 写入在 direct CTP 会话、session generation、TradingDay、settlement、approval、query/reconcile 的
独立端到端验收前保持 `NOT_SUPPORTED`。ZMQ loopback、mock 或 SimNow connect smoke 均不能升级为 production CTP 资格。

## 7. 迁移与验收重点

1. 冻结 `cloudQuant/bt_api_gateway` 的 package skeleton、公开 contracts、pin 与 isolated wheel consumer；
2. 新建并验收 `bt_api_transport_zmq`，证明无 gateway 配置时不 import `pyzmq`，启用后只加载 ZMQ adapter；
3. 一个 gateway server + 两个以上 strategy clients 证明一个市场订阅、一条 account session、可区分的 strategy/order
   routing 和不跨租户的 cancel/query；
4. direct+enabled risk 的拒绝在 provider write 前发生；direct+enabled monitor freeze/drain 经过 Broker control gate；
5. managed execution 没有 execution package/pin 时零 I/O 拒绝，且不 fallback direct；
6. ZMQ 默认 write-disabled 下 place/cancel/cancel-all 的 provider write count 均为零；authentication/ACL 缺失的
   remote endpoint 不得启动写通道；
7. reconnect、duplicate、timeout、late ack、PUB/SUB gap、slow consumer、server restart 和 provider generation change
   都必须有 deterministic negative tests；
8. NATS/Redis 只能在另有实际需求、独立 contract vectors、security/recovery 验收后新增，不得影响 ZMQ 的 canonical
   gateway contracts。
