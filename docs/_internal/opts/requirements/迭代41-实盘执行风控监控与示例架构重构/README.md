# 迭代 41：实盘执行、风控、监控与示例架构重构

状态：`PLANNED / NO-GO`
创建日期：2026-09-21
范围仓库：`backtrader`、`bt_api_py` superproject、已挂载的 execution/risk/monitor 子仓、已创建但尚未打包/挂载的
[`cloudQuant/bt_api_gateway`](https://github.com/cloudQuant/bt_api_gateway)，以及近期拟建的 `bt_api_transport_zmq`。
`bt_api_gateway` 当前为 `NOT_PACKAGED / NOT_ATTACHED`，`bt_api_transport_zmq` 为 `NOT_CREATED / NOT_PACKAGED`；二者
都不得以 ambient/PyPI fallback 冒充已加入。现有 provider submodule 仍是 provider 边界，不因本迭代改为上述能力的实现位置。
实施前提：每个 Git 身份（superproject、三个已挂载能力子仓、gateway、transport-zmq、Backtrader，以及被修改的 provider 子仓）必须在
独立、可归责的提交/工作树中执行。`bt_api_py` 只能通过明确的 optional dependency、版本约束和 integration
adapter 使用这五个包；不得把它们复制、vendor 或混入 `bt_api_py` 的单体源码包。本目录是跨仓契约，不授权
混合修改或真实交易写入。

当前 `bt_api_execution` 固定在空仓 pin `2700cb5`。在其具备 `pyproject.toml`、`src/`、`tests/` 和通过
包级验收前，`.gitmodules` 必须标为 `installable=false`：父安装器默认明确显示 `NOT_PACKAGED`，strict
显式选择 execution 必须非零退出，且绝不从 PyPI 或 ambient editable 安装回退。

本次登记的子模块基线为：`bt_api_execution` `2700cb5454ef4c3d1780eda28b6f33307a860998`、
`bt_api_risk` `b6c98e9bbd89c99f20ae49110b622e2730158f7a`、`bt_api_monitor`
`48fa8d2b35b2ccceb85e19fd440eec837d9d2a7c`；`bt_api_gateway` remote 为
`https://github.com/cloudQuant/bt_api_gateway`、当前 `NOT_PACKAGED / NOT_ATTACHED`；`bt_api_transport_zmq` 当前为
`NOT_CREATED / NOT_PACKAGED`。二者完成 skeleton 后均必须记录 pin、wheel/hash 与 consumer evidence。这些是可复现的源码指针，不代表任何能力已经实现、集成
或获准实盘使用。

## 策略运行配置合同

`config.yaml` 是运行时插件的**选择性**启用、参数和凭据入口，不是所有 Backtrader 实盘 runner 的强制
启动条件。每个采用该配置合同的策略目录，将本地 `config.yaml` 由 `.gitignore` 忽略且不被 Git 追踪，仓库则
提交同目录无秘密的 `config.example.yaml`；操作者复制模板后自行填写该策略/账户的凭据。

运行时存在两条明确、不能自动互相回退的路径：

- `runtime.order_route: legacy_direct`（或完全没有配置）保留既有
  `Strategy → BtApiBroker/BtApiStore → provider` 直接下单路径。没有 `plugins`，或所有插件关闭且均为 `required:false` 时，五个 runtime capability
  都不 import/init；如果 risk/monitor 被显式启用且 attach 成功，它们分别在真实 Broker/Store 写入边界执行
  hard gate 与 freeze/drain control，而不是 advisory/telemetry。
- `runtime.order_route: managed_execution` 必须有规范化的 `<strategy-runtime-dir>/config.yaml`，且
  `plugins.execution.enabled: true`。这时才校验 `config_schema_version`、strategy identity、
  插件组合、包版本/pin、capability 和 managed preflight；启用 risk/monitor
  时分别提供 hard gate/checkpoint 保障。`runtime.account_access` 另选 `direct_provider` 或 `gateway_client`；后者要求
  已启用 gateway 与恰一个 transport adapter，且 client 不能携带 provider credentials。

`legacy_direct` 与 `managed_execution` 都仍受交易所/CTP 的原生认证、网络、协议和账户限制约束；前者只是
不使用 execution 的 plan/journal，并不是绕过 provider 本身。execution/risk/monitor/gateway 可按需要独立选择，
transport 仅作为 gateway 的受限实现；组合状态只描述
当前保障，绝不替代 provider、账户、研究、时段或审批的独立交易准入。

被 Git 忽略的本地 `config.yaml` 可以在 provider-specific 严格 schema 中直接保存凭据；`.env`、操作系统
secret store 仍可作为替代来源。`config.example.yaml`、Git index、日志、报告、receipt、异常、metrics 和
config fingerprint 则绝不得包含凭据或可重放 capability。环境变量也不得覆盖 `plugins.*.enabled/required`、模式、
risk limit、lifecycle、transport 或 execution policy。完整结构见[模板](templates/config.example.yaml)、[插件、网关与传输架构](插件与ZMQ架构.md)、[需求文档](需求文档.md)、[设计文档](设计文档.md)和
[验收文档](验收文档.md)；本迭代计划阶段**不会创建任何 example 的真实凭据 `config.yaml`**。

每个迁移 runtime 的 `.gitignore` 至少包含 `/config.yaml`，而 `config.example.yaml` 保持受版本控制。现有被
追踪的 `config.yaml` 不能只靠新增 ignore 变安全：迁移必须先将其无秘密结构迁到模板、移除 Git index 中的
真实文件、再以 `git check-ignore` 和 `git ls-files` 证明本地配置确实没有被追踪。

## 一句话目标

建立一个可选择的受管执行中枢：策略可继续经 Backtrader 的现有 Broker/Store 直接写入 provider，或显式
启用 `bt_api_execution` 获得聚合、拆单、路由与对账；启用 `bt_api_risk` 可在任一路由加入真实写前风控，启用
`bt_api_monitor` 可加入独立监控/控制面；可选 `bt_api_gateway` 复用账户会话、行情和私有事件路由，
`bt_api_transport_zmq` 只实现其首个传输 adapter，不重定义执行或风控。随后为所有具备写入能力的 examples 明确记录其 `DIRECT`、
`MANAGED`、`DISABLED` 或 `NOT_APPLICABLE` 路径，而不是把 direct 路径误作异常旁路。

这不是让现有候选立即获得下单权限的计划。研究未准入、缺少日历/凭据、未完成外部验证、
`RESEARCH_REJECTED`、`NOT_ADMITTED`、production CTP 未受管等状态继续有效。

## 实施承诺

本迭代是**代码实施迭代**，不以文档、接口草图或 mock 作为完成替代。后续实际交付包括：

| 仓库 | 必须实际实现的代码交付 |
| --- | --- |
| `D:/bt_api_py/bt_api/bt_api_execution`（Git submodule；初始仓为空） | 实现新的公开 execution/OMS 包；复用并兼容现有 SDK execution session/journal/lease，提供 parent/child/aggregation/恢复/capability/lifecycle contracts 与最终 provider dispatch gate。 |
| `D:/bt_api_py/bt_api/bt_api_risk`（Git submodule） | 修复现有 fail-open/频率/额度/halt 缺口，实现 durable account-level `RiskPermit`、reservation/settlement/freeze/drain；作为 execution 可选接入的 hard-gate。 |
| `D:/bt_api_py/bt_api/bt_api_monitor`（Git submodule） | 实现 execution outbox consumer、durable checkpoint、health read model、告警与带授权的控制命令；不取得普通开仓能力。 |
| [`cloudQuant/bt_api_gateway`](https://github.com/cloudQuant/bt_api_gateway)（已创建，尚未 package/submodule） | 实现中间件无关的 shared account/session、订阅并集/fan-out、strategy/order correlation、snapshot/replay 和 command-routing contracts；不实现第二个 OMS、风险账本或 provider 真相。 |
| `D:/bt_api_py/bt_api/bt_api_transport_zmq`（近期拟建可选子仓） | 实现 gateway 的首个 ZMQ adapter：socket/framing、认证/ACL、背压、事件转发和 command relay；不拥有 account/session、provider client、execution journal 或 risk ledger。 |
| `D:/bt_api_py` superproject | 维护能力包 pin、兼容版本矩阵、optional extras/dependency lock、严格的 `config.yaml` runtime-plugin loader、组装 integration adapter 和 provider adapter 边界；不复制领域源码。 |
| `D:/source_code/backtrader` | 保留并归责 `Strategy → BtApiBroker/BtApiStore → provider` 的 direct route；为已启用的 direct risk/monitor 提供真实 hook/control 接点，并实现 managed execution 薄适配、allocation 回灌与 TradeLogger bridge。 |

每一项都必须包含源码提交、submodule pin、测试、隔离 consumer 验收和脱敏证据。只有这些代码交付与
[验收文档](验收文档.md)同时通过，才能称为 `ARCHITECTURE_ACCEPTED`；计划本身不构成完成声明。

## 为什么现在立项

迭代 27 的下列已登记事实是本迭代的直接输入：

| 迭代 27 记录 | 对迭代 41 的约束 |
| --- | --- |
| `I27-20260921-17`～`20` | 受控日历、研究准入、Windows CTP 运行时与 production CTP 不是 `.env` 可补齐项；新架构不得绕过它们。 |
| `I27-20260921-30` | CTP 的交易日边界与 crypto 7×24 生命周期必须分轨；3600 秒只能保留为工程观察/G3 证据边界。 |
| `I27-20260921-31` | 012 的短时 candidate runner 不能伪装成长期 watchdog；continuous shadow 必须是单独的零写入入口。 |
| `I27-20260921-32` | 账户级风险、策略局部风险、SDK budget 和 TradeLogger 告警当前重复且无统一写入权威。 |
| `I27-20260921-33` | 现有实盘 `parent/oco/transmit` 不具备 provider 级 bracket/OCO 语义；在能力协商完成前必须失败关闭。 |
| `I27-20260921-34`～`37` | `-34` forwarding router、`-35` base gateway 两条 runtime 的默认拒写门已有源码修复与定向回归；`-36` 补齐 risk/monitor 的直接依赖 metadata；`-37` 的双 protocol/runtime、懒导入/optional dependency、认证/ACL、恢复与 CTP gateway 收敛仍待完成。完整 isolated consumer 与本迭代 gateway/transport 验收也仍待完成。 |

完整原始证据见[迭代 27 执行记录](../迭代27-在途工作落库与遗留问题修复/执行记录.md:138)。

## 计划文档

| 文档 | 用途 |
| --- | --- |
| [初始需求](初始需求.md) | 保留用户立项诉求与不应被重构放宽的边界。 |
| [需求文档](需求文档.md) | FR41/NFR41、术语、外部模块基线和非范围。 |
| [设计文档](设计文档.md) | 模块边界、公共 contracts、状态机、不变量和兼容性决策。 |
| [插件、网关与传输架构](插件与ZMQ架构.md) | 运行时插件加载、direct hook、共享账户 gateway、首个 ZMQ adapter、可靠性与安全边界。 |
| [迭代计划](迭代计划.md) | 工作包、依赖、交付物、迁移顺序和 NO-GO 条件。 |
| [迁移矩阵](迁移矩阵.md) | 所有可写 examples 的盘点规则、分批迁移及 README 交付要求。 |
| [验收文档](验收文档.md) | 可执行验收门、负向合同、证据和最终裁决规则。 |
| [证据目录说明](evidence/README.md) | 后续脱敏 receipt、基线、fault 与迁移制品的命名和保留规则。 |

## 完成定义

只有同时满足以下条件，迭代 41 才能标记为完成：

1. 每个可写 example/runtime 入口均进入机器可读 inventory，并被标记为 `DIRECT`、`MANAGED`、`DISABLED` 或
   有证据的 `NOT_APPLICABLE`；direct route 是显式选择，不能在 managed route 故障时自动触发。
2. 每个 `MANAGED` 普通开仓、撤单、replace 和受控减仓均经 SDK 最终写入门、持久化 intent 与身份围栏；
   任一 unknown、持久化故障或围栏变化都冻结该 managed route 的新开仓。`DIRECT` 路径保留既有 Broker/Store
   写入语义，但不能被表述为经过该门。
3. managed 聚合执行保存 parent/child、策略归因、额度占用、部分成交和恢复证据；没有把多次普通写入称为
   原子 basket、OCO 或 bracket。
4. 在启用 `bt_api_risk` 的任一路由中，频率、每日次数、撤单、仓位、名义金额、损失、紧急额度和
   `freeze/drain` 均在真实写入/控制边界生效；managed route 另有 permit/journal/recovery。启用
   `bt_api_monitor` 时可从 durable event 或 direct runtime event 判断健康并经 Broker control gate 执行
   freeze/drain；TradeLogger 不是其替代品。
5. CTP 与 crypto 分别满足其交易日/连续运行契约；现有研究、审批和生产隔离门不因迁移而放宽。
6. 每份已迁移 example 的 README 说明策略逻辑、参数、模式、`runtime.order_route`、`runtime.account_access`、已启用插件及其参数、gateway role/transport、启动/停止/恢复、
   `config.example.yaml → config.yaml` 的复制方式、`.gitignore`/非追踪验证、凭据脱敏边界、证据位置和当前
   准入状态；没有把 replay、shadow 或本地测试表述为真实交易通过。
7. `bt_api_execution`、`bt_api_risk`、`bt_api_monitor`、`bt_api_gateway`、`bt_api_transport_zmq` 与 Backtrader adapter 均有实际源码实现、
   各自可安装制品、submodule pin 和跨仓 consumer 回归；`bt_api_py` 通过明确的 optional integration
   使用它们。不得以文档、mock、vendor copy 或 example 内重复实现替代。
8. 每个配置化 strategy runtime 的 `config.yaml` 都通过严格 schema/插件预检；任何 enabled plugin 缺失、未知字段、未被
   忽略或已追踪的真实配置、不兼容路由/插件组合、空 execution 子仓都在该配置化 route 中 fail-closed，
   且配置变更会形成新的 identity/preflight，不能热加载后沿用旧 permit。`DIRECT` runtime 可以没有该配置；
   若启用 risk/monitor，必须如实记录它们已经在真实 write/control boundary 生效；若选择 `gateway_client`，还必须
   验证 gateway + selected transport 成对、client 无 provider credentials 且没有回退本地 provider。不得虚报 execution
   journal、aggregation 或 recovery。

在这些条件之前，最终状态始终是 `INCOMPLETE / NO-GO`。
