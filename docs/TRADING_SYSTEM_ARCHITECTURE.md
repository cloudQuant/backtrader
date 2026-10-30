# 交易系统架构与项目职责

本文记录 Backtrader、`bt_api_py` 及其子项目的职责建议和当前实现边界，供用户选择部署方式和项目维护者整理代码时参考。调研基线为 2026-10-30 的 Backtrader `dev` `64f3d5f0` 与 `bt_api_py` `dev` `fa8af9b5`；子项目的基线版本由后者记录的 21 个 gitlink 指定，本轮各子项目后续提交仅修改 README。Gateway 工作区另有原有未提交的源码和测试修改，未纳入本轮提交，不能将其未提交状态当作已验收基线。**目标架构是设计方向，不代表所有链路已经实现、部署或通过真实账户验收。**

行业并不存在唯一的交易系统分层标准。本文参考 [NautilusTrader 的运行与执行架构](https://nautilustrader.io/docs/latest/concepts/architecture/)、[CCXT 的统一 API 与场所差异](https://github.com/ccxt/ccxt/wiki/Manual)、[QuantConnect 的实盘部署与恢复说明](https://www.quantconnect.com/docs/v2/cloud-platform/live-trading/deployment)和 [FIA 自动交易风控实践](https://www.fia.org/sites/default/files/2024-07/FIA_WP_AUTOMATED%20TRADING%20RISK%20CONTROLS_FINAL_0.pdf)，再结合本项目代码确定职责；这些资料不意味着具体市场的法律适用性或本项目已达其全部实践要求。

## 1. 总体定位

```text
用户：xx_strategy.py + config.yaml + run.py
                   |
Backtrader：策略、因子、Cerebro、Feed、Broker、回测和框架投影
                   |
bt_api_py：统一 SDK、交易所插件加载、服务客户端和服务组合
                   |
                   +-- bt_api_runtime   可选预检和生命周期编排（规划）
                   +-- bt_api_gateway   可选账户/行情会话与读取
                   +-- bt_api_risk      可选风控许可和预留
                   +-- bt_api_execution 可选订单意图、派发与对账
                   +-- bt_api_monitor   可选监控、事件和告警
                   +-- venue adapters   CTP / Binance / OKX 等

bt_api_base 提供共享合同；bt_api_transport_zmq 提供可选通信。
```

这是职责图，不是每条请求必须经过的顺序或必须启动的进程。具体装配可以选择进程内直接 SDK 路径，也可以选择经明确配置的服务路径。安装一个包或在 YAML 中声明组件，并不自动等于已安装全部依赖、已加载、已连接或已获得写入授权。

## 2. Backtrader：策略与回测引擎

Backtrader 负责 `Strategy`、`Cerebro`、Feed、Broker、订单和成交通知、指标、观察器、分析器、回测撮合以及因子研究。Cerebro 持有 Feed、指标和策略时钟；实时因子可复用 `LiveFactorPlan` / `LiveFactorSet`，不再实现另一套调度器。框架的实盘桥负责把行情和执行事实投影到 Backtrader 的 Feed、Order、Position 等对象。

交易所协议签名、账户服务、provider 连接、风险许可和订单执行账本应由 SDK 及其组件承担；Backtrader 保留自身 Broker 校验、框架投影及正常回调。`ServiceReadProxy` 是只读桥，`ServiceExecutionSession` 是显式选用的框架侧 managed-execution 接口，它们并不证明服务或真实账户已部署。更多当前接口见 [只读代理](source/developer-guide/optional-service-read-proxy.md)和[执行会话](source/developer-guide/optional-service-execution-session.md)。

一般用户策略目标是以策略逻辑、公开配置模板和薄启动入口三个文件表达；每个文件目标不超过 800 个非空行。策略可定义因子、选标和调仓政策；通用连接、风险和恢复功能应通过已验证组件复用。具体重构和验收范围见[迭代 52 计划](_internal/opts/requirements/迭代52-精简策略与可选运行时/迭代计划.md)。

## 3. bt_api_py：统一接入 SDK 与组合层

[`bt_api_py`](https://github.com/cloudQuant/bt_api_py) 提供 `BtApi` 外观、交易所插件装配、直接 Feed 接入、标准化合同，以及服务端 `ServiceHost` 和客户端 `ServiceClientRuntime` 等组合能力。当前 direct SDK 和 service-v2 是不同路径；旧 `BtApi` ZMQ 转发参数不能当作 service-v2 的别名。服务端具体资源、认证身份、账户范围和 authority 必须由可信组合方提供，配置文件不能自行创建交易授权。

SDK 是集成框架，不是 Backtrader 的第二套策略引擎。插件加载或静态 capability 声明只表明源码注册或安装状态，不证明交易所数据覆盖、真实账户、订单闭环或生产就绪。父仓库的交易所支持矩阵和对应项目的证据应分别核对。

## 4. 基础与可选组件

| 项目 | 主要职责 | 边界 |
|---|---|---|
| [`bt_api_base`](https://github.com/cloudQuant/bt_api_base) | 共享接口、DTO、插件基础与服务协议 | 合同不提供账户身份、风险许可或交易所结果的权威；Base 的实际依赖和 Python 版本需按发行物核查 |
| [`bt_api_runtime`](https://github.com/cloudQuant/bt_api_runtime) | 拟承担配置校验、预检、组件装配、启动/停止、恢复协调与诊断 | **当前是占位仓库**，没有 runtime 或预检实现；不拥有第二套订单/风险状态，不调度 Backtrader 指标 |
| [`bt_api_gateway`](https://github.com/cloudQuant/bt_api_gateway) | 账户和行情服务、会话/订阅协调及本地读模型与受控路由 | provider 事实来自可信外部来源；本地 journal 或 lease 不证明全局 provider 状态或其他进程被约束 |
| [`bt_api_risk`](https://github.com/cloudQuant/bt_api_risk) | 风险政策、下单许可、预留、冻结及相关风险事实 | 需要可信账户/持仓/价格及策略事实；许可本身不等于交易所接受订单 |
| [`bt_api_execution`](https://github.com/cloudQuant/bt_api_execution) | 订单意图、派发记录、回报、未决状态、恢复及对账合同 | 不替代 provider、Risk 或 Monitor；派发结果未知时保留 UNKNOWN 并对账，不盲目重复提交 |
| [`bt_api_monitor`](https://github.com/cloudQuant/bt_api_monitor) | 遥测、指标、事件读取、健康观察和受控运维入口 | 监控事件不构成订单、账户完整性或风控许可的权威；启用的控制能力须有可信验证 |
| [`bt_api_transport_zmq`](https://github.com/cloudQuant/bt_api_transport_zmq) | 可选的 ZeroMQ 消息、身份认证、ACL 和传输 | 不拥有订单账本、provider 或风险策略；传输超时不证明订单未被接受 |

组件按配置选择不意味着安全检查可以无声消失。对于显式选用的交易路径，缺少其必需插件、授权或有效风险事实时，应明确拒绝或报告不可用；无关的只读、回测或监控功能可以依据各自合同运行。具体插件依赖和故障策略由部署合同决定，不把拟议行为当作当前实现。

## 5. 交易所与券商适配子项目

每个 venue 项目负责本场所的协议、签名、连接、字段和品种映射、已实现的行情及交易 API，并向共享接口报告自身能力。统一接口不能抹去精度、限频、分页、账户模型或错误语义差异。

| 项目 | 接入对象与当前注意事项 |
|---|---|
| [`bt_api_binance`](https://github.com/cloudQuant/bt_api_binance) | Binance；部分服务 provider 限定 Demo 或特定产品，不能外推全部产品或账户已验收 |
| [`bt_api_bitget`](https://github.com/cloudQuant/bt_api_bitget) | Bitget；插件注册 Spot/Swap，运行环境和具体接口仍须验证 |
| [`bt_api_bybit`](https://github.com/cloudQuant/bt_api_bybit) | Bybit；当前插件源码注明 market/account WebSocket 流尚未实现 |
| [`bt_api_coinbase`](https://github.com/cloudQuant/bt_api_coinbase) | Coinbase Advanced Trade；当前注册 Spot，WebSocket 支持需按实际实现核对 |
| [`bt_api_ctp`](https://github.com/cloudQuant/bt_api_ctp) | CTP 原生连接、行情、交易回调和期货协议；SimNow/期货账户、只读/写入分别验证 |
| [`bt_api_dydx`](https://github.com/cloudQuant/bt_api_dydx) | dYdX；已注册产品、订阅及未实现功能应分别核对 |
| [`bt_api_gateio`](https://github.com/cloudQuant/bt_api_gateio) | Gate.io；具体产品、REST 和实时订阅能力按实现验证 |
| [`bt_api_htx`](https://github.com/cloudQuant/bt_api_htx) | HTX；产品注册不等于所有行情及账户路径通过验收 |
| [`bt_api_hyperliquid`](https://github.com/cloudQuant/bt_api_hyperliquid) | Hyperliquid；运行时可能需要可选依赖，代码存在不等于插件已加载 |
| [`bt_api_ib_web`](https://github.com/cloudQuant/bt_api_ib_web) | Interactive Brokers Client Portal 接口；不等于完整 managed-service 账户或订单接入 |
| [`bt_api_kraken`](https://github.com/cloudQuant/bt_api_kraken) | Kraken；产品、行情流和账户功能须分别验证 |
| [`bt_api_mexc`](https://github.com/cloudQuant/bt_api_mexc) | MEXC；当前插件只注册 Spot，不能宣称当前注册了永续产品 |
| [`bt_api_mt5`](https://github.com/cloudQuant/bt_api_mt5) | MetaTrader 5；当前插件明确声明 provider 不可用，不能因仓库存在而宣称可交易 |
| [`bt_api_okx`](https://github.com/cloudQuant/bt_api_okx) | OKX；具体产品、实时流及账户能力按接口和环境分别验收 |

上述状态是调研时的源码/README 事实，不是对所有子项目的完整功能认证。各项目 README 应维护具体产品、操作、环境及证据级别；不能把 capability、安装或模拟测试描述为真实账户通过。

## 6. 目标状态所有权与恢复

| 事实或状态 | 所有者/来源 | 其他组件的职责 |
|---|---|---|
| 交易所订单、成交与账户事实 | 交易所或券商的可验证观察 | Adapter 翻译，Gateway/Execution/Backtrader 消费和投影；没有结果不等于零或失败 |
| 本地订单意图、派发、恢复与 UNKNOWN | `bt_api_execution` 的对应执行记录 | 拟议 Runtime 协调对账、Monitor 观察；同一账户范围只能有明确的派发 owner |
| 风险许可、预留与冻结 | `bt_api_risk` | 执行路径按合同验证许可；从可信来源获得账户、持仓及行情事实 |
| 账户/行情共享读模型 | `bt_api_gateway` 的本地状态，来源绑定 provider | 它不自动代表交易所原子快照或完整账户 |
| Backtrader Order/Position/Observer 投影 | Backtrader | 框架 session projection journal 记录该运行实例如何消费事实，与 Execution 的订单日志不同 |
| 运行健康和观测事件 | `bt_api_monitor` 和拟议 runtime 分别输出 | 新 runtime 当前尚无实现；心跳不证明订单完成、账户齐全或可交易 |

一个事实可以有多份用途不同的记录，但必须标明来源和权威。重启应分别处理策略预热、执行 journal 与 provider 对账；不能仅重跑策略或将 transport timeout 当作订单未发送。风险、监控和执行服务的可信组合需要逐路径验证，不假定跨进程、跨数据库的操作天然原子。

## 7. 当前迁移边界

Backtrader 当前仍随包提供 `backtrader_runtime`；新 `bt_api_runtime` 并未替代它。计划按职责迁移旧 runtime 全部功能：通用控制与编排归新 runtime；Backtrader 对象桥接和框架投影归 Backtrader；CTP 协议归 CTP 项目；共享合同和服务分别归对应 SDK 子项目；认证专用证据与 fixture 留在认证/测试工具。所有功能和调用方完成替代验证后取消旧 runtime 和旧门面，不保留旧 API shim。

Backtrader `examples/live` 和 `examples/unified` 中涉及模拟和实盘交易的示例都在重构范围，旧示例行为不作为兼容目标。各组件的生产功能、现存证据及未完成验收必须分别保留，历史记录不因重构改写；迁移方案本身不授权新的账户写入。实现、安装、真实行情和真实账户接受需要各自证据。

## 8. 分发与验证

各子项目是独立 Git 仓库/子模块，是否单独构建、安装和启用由各自发行配置决定；父仓库的 submodule 记录不等于父 wheel 已打包子项目。Backtrader 与 SDK 的 Python 支持范围不同，组合时需要明确版本矩阵、依赖、可选 extra 和失败行为。

建议将验证分为源码/单元、真实组件配合 fake 叶子、隔离安装、实际只读行情、获授权模拟账户和真实账户等级。包存在、插件注册、构建 wheel、连接 socket 或监控心跳都不能单独证明交易闭环已通过。风险控制不仅在启动前检查，还应在实际订单路径上执行，交易后监控和对账也有独立作用。
