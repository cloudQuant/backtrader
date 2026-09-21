# AI 系统架构师审阅意见

状态：`REVIEWED / PLAN_AMENDMENT_RECOMMENDED / NO-GO FOR AI-LIVE-INTEGRATION`
审阅日期：2026-09-21
审阅对象：[迭代计划](迭代计划.md)、[需求文档](需求文档.md)、[设计文档](设计文档.md)、[验收文档](验收文档.md)、[迁移矩阵](迁移矩阵.md)、[插件与 ZMQ 架构](插件与ZMQ架构.md)。

## 结论

迭代 41 已为 `bt_api_py` 的受管执行、账户级风险门、监控、网关及 Backtrader 双路径迁移建立了较强的安全基线；`legacy_direct` 与 `managed_execution` 的区分、禁止自动回退、配置化插件的零 I/O 拒绝，以及 CTP/crypto 的准入边界均应保留。

但该计划尚未把 `backtrader-agent`、`backtrader-mcp`、`backtrader-skills` 作为正式的生产者或不可信调用主体建模。它没有定义以下关键合同：

- AI 生成或审阅的策略如何与实际代码、数据、引擎、回测、研究候选和部署配置形成一条不可混淆的证据链；
- AI 产品自身的“写文件/跑回测”审批如何与实盘账户的部署准入、逐 child 的 `RiskPermit` 严格隔离；
- AI/MCP/skill 在什么条件下只能读取受脱敏的运行事实，在什么条件下可提出人工处理请求，以及为什么它们永远不能直接成为 provider writer；
- AI 产物为何不能因“无 `config.yaml` 即兼容 `legacy_direct`”而意外进入有凭据的直接下单路径；
- 三个产品如何共享稳定、可测试的交接 schema，而不互相导入、复制运行时或把 AI 变成第五类 runtime plugin。

因此，当前计划足以继续推进执行基础设施重构，但**不能**据此声称“AI 已可安全使用 Backtrader 完成实盘策略”。建议在实施开始前纳入本文的 `WP41-I`、新增验收条件和 AI 专属 NO-GO。它们不会放宽任何既有研究、SimNow、HFT 或 production 准入门。

## 审阅依据与已核验基线

本次结论基于当前本地 checkout、迭代 41 文档和公开产品说明形成；版本/提交仅表示本次审阅快照，不构成发布或实盘认证。

| 对象 | 本次核验到的事实 | 对迭代 41 的含义 |
| --- | --- | --- |
| [`backtrader-agent`](https://github.com/cloudQuant/backtrader-agent) | `0.2.0`；离线优先、内容寻址数据、哈希绑定的变更/回测审批、固定子进程执行。`StrategySpec` 的 `entry`、`exit`、`risk` 在 P0 中会入 hash，但不会被翻译为实际 `next()` 逻辑。 | 适合生成和保存可审计的研究证据；现有 run approval 不能成为交易授权，且“自然语言策略意图”不能直接作为实盘行为证明。 |
| [`backtrader-mcp`](https://github.com/cloudQuant/backtrader-mcp) | `0.2.0`；本地 stdio、30 个 typed tools、P0 明确禁止 broker/store/credential/live order/network transport；审批在 MCP 工具之外的本地 CLI 中完成。 | 可增加**只读**的执行证据/健康查询和导出交接包；不应把 `place_order`、`resume` 或 provider credential 引入当前 MCP server。 |
| [`backtrader-skills`](https://github.com/cloudQuant/backtrader-skills) | `0.2.0`；离线 author/review/test；AST 限制候选使用 live store、网络、socket 和动态执行；run approval 只覆盖受控回测。 | 可提供部署就绪性审阅、证据包导出和宿主 eval；不能把现有 skill token 解释为账户或订单许可。 |
| `bt_api_py` | 现有 `_ExecutionSession` 已包含 journal、writer lease、fence、未知订单恢复、CTP approval/budget 等机制，但仍是私有且高度耦合的实现。 | `bt_api_execution` 必须做兼容迁移而非复制第二账本；AI 只接触稳定的公开 schema/read model，不能 import 私有 session。 |
| Iteration 41 schema-v3 | `config.yaml` 能标识 `strategy.id`、`candidate_id`、route、account access 与插件组合，但没有策略 artifact、回测数据、引擎、运行结果、AI producer 或部署授权之间的绑定。 | `candidate_id` 不是可验证的部署证据；需补充独立的 deployment-evidence/admission 合同。 |

MCP 的风险标注（例如 `readOnlyHint`）仅是客户端提示，不是授权边界；真实授权必须由服务端 policy、身份、scope 和执行时验证完成。该原则与 [MCP 架构的能力协商](https://modelcontextprotocol.io/specification/2025-11-25/architecture) 及 [MCP 对 tool annotation 限制的说明](https://blog.modelcontextprotocol.io/posts/2026-03-16-tool-annotations/) 一致。

## 建议的目标架构

AI 应处于“研究与辅助决策平面”，而不是执行 runtime-plugin 平面。它可以生成策略、解释受脱敏运行状态、准备人工审批材料和提出处置建议；执行路径仍由 `bt_api_py`、`bt_api_execution`、risk、monitor 与 provider 端控制。

```text
            Offline authoring / research plane
 ┌────────────────────────────────────────────────────────┐
 │ backtrader-agent | backtrader-mcp | backtrader-skills  │
 │ StrategySpec / code / dataset / backtest / review       │
 └─────────────────────────┬──────────────────────────────┘
                           │ immutable StrategyDeploymentEvidence
                           │ (evidence only; never an order authority)
                           v
 ┌────────────────────────────────────────────────────────┐
 │ Operator / deployment-admission plane                   │
 │ verifies hashes, research state, route, scope, policy   │
 │ -> issues short-lived DeploymentAdmissionReceipt        │
 └─────────────────────────┬──────────────────────────────┘
                           │ required_route=managed_execution
                           v
 ┌────────────────────────────────────────────────────────┐
 │ bt_api_py integration -> bt_api_execution               │
 │    -> RiskGate/RiskPermit -> journal/outbox -> provider │
 │    -> monitor/control plane                             │
 └────────────────────────────────────────────────────────┘

                 Redacted, versioned, read-only facts
 monitor/execution read model ───────────────────────────► AI/MCP/skills
```

### 必须冻结的架构决策

| ID | 决策 | 绑定规则 |
| --- | --- | --- |
| AD-AI-01 | AI 不是 Iteration 41 的 runtime plugin。 | 不在 `plugins.{execution,risk,monitor,gateway,transport_zmq}` 新增 AI 开关；无 AI import、worker、socket 或模型调用发生在 strategy 的下单热路径。 |
| AD-AI-02 | 使用通用的 `StrategyDeploymentEvidence v1`，不使用“AI order token”。 | schema 放在既有 shared contracts/base 层（建议 `bt_api_base` 的纯 JSON-schema/typed-contract surface），不得依赖任一 AI 产品或 provider。三个 AI 包以可选 schema-only extra 适配它，不反向导入彼此。 |
| AD-AI-03 | 证据、部署准入、逐笔风险许可三者绝不复用。 | AI evidence 只是可校验事实；`DeploymentAdmissionReceipt` 是人工/受信部署权威的短期 scoped receipt；`RiskPermit` 是 dispatch 前、每个 child 的一次性风险许可。任意一个都不能替代另一个。 |
| AD-AI-04 | AI 发起的部署只能进入受管路径。 | 含 `producer.kind=agent|mcp|skill` 的 evidence 必须绑定 `required_route=managed_execution`。缺 receipt、缺 config、schema/hash 不一致或 route 不符时零 provider I/O；不得因无 config 进入 `legacy_direct`。人类既有 direct 兼容性不受此规则影响。 |
| AD-AI-05 | `BtApi` 保持唯一面向业务调用者的 SDK façade。 | `bt_api_execution` 可公开 contracts 与受限 integration port，但 agent/skill/MCP 不得直接拿到 provider writer、gateway server router 或私有 `_ExecutionSession`。所有面向 AI 的调用经过固定的 read-only/prepare surface。 |
| AD-AI-06 | LLM 的输出是数据，不是权限，也不在交易热路径推理。 | prompt、模型回答、外部文本、市场注释和 tool output 都按不可信输入处理；不允许它们改变 route、risk profile、account scope、credential、permit 或 `resume`。运行时 LLM inference 是独立研究项目，不属于 Iteration 41。 |
| AD-AI-07 | 客户端声明的 account、strategy、risk 或 route 字段不授予权限。 | gateway/server 从 `PrincipalPolicy`、deployment receipt 与已认证 account scope 派生这些值；忽略客户端要求较弱风险组合或更宽账户范围的字段。 |
| AD-AI-08 | AI 可见性使用脱敏、游标化、版本化 read model。 | 仅输出 opaque account/strategy/candidate IDs、状态、原因码、健康等级、证据引用和有界摘要；不输出 provider credential、完整账户标识、可重放 capability、原始 journal 或任意文件路径。 |
| AD-AI-09 | AI 不可用不得影响已启动的执行会话。 | agent/MCP/skills 停机、host discovery 失败、模型不可用或 read-only tool 超时只能降低辅助能力；不得阻断 risk/execution 状态机，也不得自动解除 freeze/drain。 |
| AD-AI-10 | AI 受管账户不得与未协调的 direct writer 混用。 | 同一 account/environment 上存在 AI managed profile 时，任何并行 direct writer 必须经过同一 server-owned writer lease 和账户级风险投影；做不到即拒绝并发启动。这样保留人工 direct 兼容性，但不让它绕过同一账户的 reservation/unknown-order 状态。 |
| AD-AI-11 | 配置、能力包与证据必须在使用时可验证且可审计。 | capability manifest 绑定 distribution/version/hash/module/entry-point digest；配置以 regular file、owner/mode、`O_NOFOLLOW`/FD 读取和 fingerprint seal 验证；事件链含 actor/receipt/intent/permit/config/code/plugin digest、sequence 和独立锚定/保留策略。 |

## 交接合同：建议增加的最小模型

### `StrategyDeploymentEvidence v1`（非授权的可验证事实）

该对象由 AI 产品导出，或由非 AI 的同类研究工具导出。它必须 canonical serialize、带 schema version、可离线验证，且不含 credential、完整账户 ID、prompt 原文、模型密钥或 approval token。

| 分组 | 必填内容 | 作用 |
| --- | --- | --- |
| `producer` | 产品族、产品版本、schema compatibility、host 类型、可选 model identifier 的脱敏 digest | 追踪生成者，不把生成者身份当成交易权限。 |
| `artifact` | `strategy_id`、`candidate_id`、artifact/code hash、entrypoint、artifact manifest hash、语义状态 | 证明将部署的字节是什么。 |
| `semantics` | `exact`、`review_required` 或 `not_applicable`；规则到代码/IR 的 mapping digest 与未覆盖项 | 防止自然语言 `entry/exit/risk` 被误认为已经执行。当前 P0 renderer 至少应输出 `review_required`。 |
| `research` | dataset manifest/source hash、engine commit/environment hash、validation report hash、run manifests/results、comparison policy、candidate research state | 将回测与研究结论限定为证据，而非盈利或实盘许可。 |
| `requested_deployment` | 固定 `required_route=managed_execution`、目标 runtime identity、允许的 mode/profile、有效期、proposal ID | 约束后续 operator 审核；不得包含 account credential 或可自行选择风险上限的字段。 |
| `correlation` | trace/proposal ID、父 evidence digest、创建时间、replaces/revokes 关系 | 让 Backtrader order、execution event、monitor alert 和 AI 会话能以 opaque ID 关联。 |

`StrategyDeploymentEvidence` 可以带生产者自己的完整性签名，但签名只证明其私有记录未被篡改；它不能被 `bt_api_execution` 直接视为账户交易授权。

### `DeploymentAdmissionReceipt`（operator 侧权威）

部署接收端独立重新计算或验证 evidence digest，并在合格的研究/审批/账户前提下签发 receipt。最少绑定：

- evidence digest、artifact/code hash、runtime identity、`managed_execution` route、redacted config fingerprint 和 deployment profile；
- account/environment fingerprint、strategy/candidate scope、provider capability receipt、policy hash、TradingDay/epoch 与 connection generation；
- 审批主体/理由/审批链、issued/expiry、nonce、fence、revocation revision 和允许的操作范围；
- 受控 `TestExecutionProfile`、shadow/SimNow/production 的明确类别，不能以同一 receipt 跨环境升级。

`bt_api_py` 在启动和每次 dispatch 前验证仍有效的 binding。后续 `RiskPermit` 仍必须通过 `RiskGate.evaluate/reserve/commit` 获得；receipt 不能绕开额度、unknown order、freeze/drain、对账或 capability 检查。

### 语义完整性门

当前 `backtrader-agent` 的 P0 renderer 公开说明：`entry`、`exit`、`risk` 会被验证和哈希，但不翻译成可执行交易逻辑。因而：

1. 任何输出 `semantics=review_required` 的 artifact 最多可用于作者审阅、回测和 shadow；
2. 要进入受管写入，必须有受限 IR/代码映射的机械验证，或独立人工代码审阅 receipt，且其 hash 纳入 deployment evidence；
3. 不能以“StrategySpec 已审批”“回测通过”或“AI 说该规则存在”替代该语义门；
4. 若未来扩展 `StrategySpec v2`，应以受限可执行 IR、确定性 renderer 和 semantic coverage vectors 逐步完成，不能用自由文本即时编译实盘逻辑。

## 必须补齐的计划缺口

| 关联计划位置 | 发现 | 应写入的约束/交付物 |
| --- | --- | --- |
| WP41-A / AC41-01～05 | 基线只覆盖七个交易相关 Git 身份，未记录 AI producer、StrategySpec/schema、host adapter 与其独立的审批语义。 | A1 增加三产品 wheel/commit/schema/host discovery/状态根基线；A5 增加 AI trust-boundary ADR、schema ownership 和兼容矩阵。 |
| WP41-B B1～B3 / design §3 | `ExecutionScope` 提到 code/config hash，但没有 artifact、dataset、backtest、producer、语义状态和 operator receipt 的 canonical binding。 | 在 shared contracts 增加 evidence/receipt schema；在 execution 只消费其 digest 和 operator-issued admission，不反向依赖 AI 包。 |
| WP41-B B2 与 WP41-G G1/G4 | “public execution facade”和 gateway 容易成为 agent 直接写入的第二 API。 | 冻结 import/API boundary：`BtApi` 为业务 SDK façade；AI 只调用 read-only/prepare APIs；gateway server router 仅由 server-side integration 持有。 |
| §0、WP41-F F1、NO-GO | 无 config 合法进入 `legacy_direct`，对于 AI-produced strategy 是可带凭据逃逸的默认。 | AI evidence receipt 强制 managed route；runner 发现 AI deployment context 时缺 config 或 route 不符必须 `AI_DEPLOYMENT_ROUTE_REJECTED` 且 0 write。 |
| WP41-C C2～C6 | managed risk 可选，且无 actor/delegation chain；AI 自动化若被当作普通 SDK caller，无法追责或受最小权限约束。 | 对 AI/SimNow/production deployment profile 强制 `execution+risk+monitor` 均 `enabled=true, required=true`；新增 `ActorContext`、`PrincipalPolicy` 与 receipt 绑定。 |
| WP41-D D2～D6 | monitor 有控制命令但缺 read scope、角色矩阵、命令去重持久化和目标确认。 | 分离 read、freeze、drain、manual intervention、resume/break-glass；`resume` 需新的人工审批。AI 只可生成处置建议或创建待审批请求。 |
| WP41-A A6、WP41-B B6/B7、WP41-G G1 | pin/entry point/config 的计划虽已存在，但未把发行者、artifact、module/entry point、配置文件和使用时 seal 连为一条信任链。 | 使用签名 allowlist manifest；拒绝同名恶意 entry point、editable/user-site 歧义、hash 不符、symlink/权限异常和 preflight 后配置替换；每次 write 复核 seal。 |
| WP41-G G4～G6 | gateway 的 ACL 主要覆盖策略/client；尚未覆盖 AI principal、资源配额、credential rotation、相同账户 direct/managed 并发和 uncertain retry 的唯一 journal owner。 | Server-side `PrincipalPolicy`、credential epoch、每 principal/topic/command/cursor 配额、确定性 shed/freeze 行为；managed gateway client 只提交意图，server 独占 journal/lease/dispatch；同账户 direct 必须使用同一权威 lease/risk projection 或被拒绝。 |
| WP41-H H1～H7 | 验收没有 AI producer、跨仓 consumer、语义门、AI unavailable、prompt injection 或 tool authorization 的证据。 | 增加 AC41-47～55 与跨 wheel 的 conformance/eval matrix；失败保持 `FAIL`/`BLOCKED`，不可被 replay/wheel 替代。 |

此外，应解决下列非 AI 专属的实施可执行性问题：

- `B7` 与 `G1/G2` 同时拥有 `RuntimePluginManager`、registry 和 direct hook 的实现职责，且交付顺序将 G 放在 F 后。应指定 G1/G2 为唯一实现 owner，B7 仅保留 contracts/composition/precondition；
- 实施计划、设计和 README 内的 `D:/...` 路径不应成为跨平台的权威定位。ADR 应使用 repository URL、submodule logical path、commit/pin 与本机 resolved checkout 四项，而不是机器特定盘符；
- 路由语义应在计划首页保留一张 canonical matrix（四种 `order_route × account_access` 组合），后续工作包只引用该矩阵，避免文档在 direct、gateway 与 managed 的描述中漂移；
- 每一条 control command 应在持久化 `command_id + issuer sequence + receipt digest` 后才经过 control gate，并要求目标确认/超时升级，防止重启重放和“Broker 已停机但 drain 被假定完成”。

## 建议新增：WP41-I AI 研究证据与受管执行交接（P0/P1）

该工作包应位于 `WP41-B` 的 shared contracts 冻结后、任何 AI artifact 可由 runner 启动前；它可与 risk/monitor 的实现并行，但必须在 WP41-F 的 AI deployment path 前验收。

| 任务 | 内容 | 交付物 | 建议验收 |
| --- | --- | --- | --- |
| I1 | 冻结 `StrategyDeploymentEvidence v1`、`DeploymentAdmissionReceipt v1`、`ActorContext`、`PrincipalPolicy`、错误码和 canonical vectors。 | schema-only shared-contract release、compatibility policy、redaction rules | AC41-47 |
| I2 | 在 `bt_api_py` integration 与 `bt_api_execution` 实现 receipt/evidence binding、route 强制、scope/fence 检查与 audit correlation；不让 execution import 三个 AI 包。 | verifier port、preflight/readiness report、negative harness | AC41-48、49 |
| I3 | 为 agent、MCP、skills 分别实现 opt-in evidence exporter/adapter；保持 P0 离线与独立安装，且使用相同 vectors 验证字段级兼容性。 | 三个 producer adapter、isolated wheel consumer matrix | AC41-50 |
| I4 | 建立语义覆盖状态：P0 template 默认 `review_required`；受管写入只接受有机械 mapping 或独立人工 review receipt 的 artifact。 | semantic coverage report、code-review binding | AC41-51 |
| I5 | 为 MCP/skills 增加严格只读的 execution-observer/preflight surface：capability、readiness、脱敏 health、risk explanation、audit evidence reference。 | typed tool/resource schemas、bounded pagination/cursor、host discovery tests | AC41-52 |
| I6 | 实现 AI/host/gateway 威胁模型、principal policy、resource quota、credential rotation、证据防篡改和 operator command workflow。 | ADR、fault/injection tests、redacted receipts | AC41-53、54 |
| I7 | 将 AI product host eval 与 Iter41 fake-provider/full integration matrix 合并；AI 不可用、恶意输入和 producer schema drift 不得影响执行安全。 | cross-repo CI matrix、release checklist | AC41-55 |

推荐顺序如下：

```text
A (inventory + trust baseline)
  -> B/I1 (shared contracts)
  -> I2 + C (admission binding + durable risk)
  -> D (read/control model)
  -> F/I3/I4 (Backtrader adapter + AI evidence producers)
  -> G/I5/I6 (gateway/MCP observer security)
  -> H/I7 (cross-repo acceptance)
```

聚合、跨策略 netting、ZMQ 多客户端和 CTP gateway 写入仍应在单笔受管写入、AI deployment binding、risk、recovery 和证据链通过后再扩大范围。AI 交接不是把模型加入多腿执行器的理由，也不能缩短已有候选的研究门。

## 三个 AI 产品的具体演进边界

| 产品 | 本迭代可新增的能力 | 明确禁止新增的能力 |
| --- | --- | --- |
| `backtrader-agent` | 导出 deployment evidence；展示 semantic coverage、readiness 与人工审批待办；把 proposal/correlation ID 写入本地 provenance。 | 读取 provider credential、连接 gateway/provider、调用 execution writer、把本地 run token 转为交易 token、在 `next()` 中调用模型。 |
| `backtrader-mcp` | 可选 `execution-observer` profile，提供 `get_execution_contract`、`validate_deployment_evidence`、`get_preflight_status`、`get_monitor_health`、`get_audit_summary` 等只读、分页、脱敏工具。 | 在既有 P0 server 中暴露下单/撤单/恢复/凭据工具；依赖 tool annotation 作为授权；将 approval 参数开放给模型。 |
| `backtrader-skills` | 新增 deployment-readiness/review skill，检查 evidence、schema、策略语义覆盖、回测边界和 README/配置一致性；扩展 host eval。 | 允许 live store/network/socket 进入当前生成策略，或让 skill 的本地审批能力变成实盘权限。 |
| `bt_api_py` / `bt_api_execution` | 提供 schema-only compatibility、零 I/O evidence preflight、server-side verifier/read model 和稳定错误码；在执行事件中保留 opaque correlation。 | import AI runtime、运行模型、保存 prompt/credential、接受 AI 自报的 account/risk/route 权限、暴露私有 `_ExecutionSession`。 |
| Backtrader adapter | 在受管启动前验证 deployment receipt，并将 framework orders 映射为已归属的 execution intents。 | 将 AI evidence 自动转换成 `buy`/`sell`，或在 receipt/config 失败时启动 direct provider。 |

## 建议新增的验收条件

下列条件应加入[验收文档](验收文档.md)；所有本地、fake-provider、replay 和 shadow case 仍默认 `0 provider write`。

| ID | 主题 | 必须通过的条件 |
| --- | --- | --- |
| AC41-47 | AI 交接 contracts 与供应链 | 三产品与 execution consumer 使用相同 canonical vectors；未知/旧 schema、重复字段、secret、绝对路径、完整账户 ID、可重放 token 和不受支持 producer 均拒绝。capability distribution/hash/module/entry point 不在 allowlist、同名恶意 entry point、editable/user-site 歧义也必须零 I/O 拒绝。 |
| AC41-48 | Evidence/receipt/scope/config seal binding | artifact、语义状态、dataset、engine、environment、run result、candidate、runtime config、route、account/environment、policy、TradingDay/epoch/generation 中任一 binding 改变，旧 receipt 都失效且 write count 为零。替换 config、symlink、owner/mode 异常或 preflight 后 seal 变化同样拒绝。 |
| AC41-49 | AI route hard gate 与共享账户互斥 | AI deployment context 缺 config、选择 `legacy_direct`、缺 execution/risk/monitor、缺 admission receipt 或发生 managed preflight 失败时，runner 在 provider I/O 前失败；已有人类 direct regression 不倒退。同一账户的 direct/managed 并发必须共享 writer lease/risk projection，否则拒绝。 |
| AC41-50 | 独立 producer 保持独立 | agent/MCP/skills 在隔离 wheel 环境中生成可验证 evidence；三者均不 import/start sibling product、gateway、provider client 或 execution writer。 |
| AC41-51 | 语义完整性 | 当前 P0 renderer 的 artifact 标记 `review_required` 并拒绝 promotion；完整 mapping 或独立审阅 receipt 被篡改、过期、跨 artifact 重放时拒绝。 |
| AC41-52 | MCP read-only observer | 工具 schema、output schema、read-only/分页/游标、redaction、host discovery 与 stale-state 提示通过；tool annotation 缺失或撒谎不能绕过服务端 authorization。 |
| AC41-53 | Actor、principal 与控制命令 | AI/MCP/skill 的 actor 只能读取或创建待审批请求；伪造/过期/跨 tenant/跨 account/跨 strategy 的 delegation、freeze/drain 重放、未确认 drain 和自动 resume 全部拒绝或升级为 `manual_intervention`。命令必须先原子持久化 `command_id + issuer sequence + receipt digest`，Broker 停机时需在 deadline 后升级而不是假定执行。 |
| AC41-54 | Gateway 多主体隔离 | 恶意/慢速 AI client 的订阅、命令、cursor、CPU/内存配额不能影响其他 strategy；credential rotation/revocation 强制重新认证；uncertain command 仅由 server journal/reconcile 收敛。 |
| AC41-55 | AI 失效、输入攻击与审计完整性 | prompt injection、恶意 tool output、producer 不可用、模型超时、schema drift、篡改 evidence、事件链篡改/重排和 host discovery 失败均不创建/改变 provider 写入；已运行的 execution/risk/monitor 会话继续按独立安全状态机运行，且可验证 actor/receipt/intent/permit/config/code/plugin 的有序审计链。 |

## AI 专属 NO-GO

出现任一情形时，不得将 AI-assisted artifact 标记为 `managed_execution`、可写或已部署：

- 把 agent/MCP/skills 的本地 change/run approval、HMAC record 或 host approval 当作 `DeploymentAdmissionReceipt`、`RiskPermit`、provider authorization 或账户身份；
- AI evidence 缺 artifact/code hash、semantic coverage、engine/data/run evidence、研究状态、受管 route binding 或有效的 operator receipt；
- AI artifact 从无配置、失效配置、`legacy_direct`、direct provider、raw HTTP/ZMQ、private execution session 或 strategy-local gateway 取得写入能力；
- AI managed profile 与同账户的 `legacy_direct` writer 并发运行，却没有同一 server-owned writer lease、risk projection、unknown-order/reconcile 事实；
- 任一 AI/MCP/skill 进程可读取 credential、完整账户标识、provider adapter、gateway server secret、风险账本、原始 journal 或其他 strategy 的私有订单；
- 将 tool annotations、client 传来的 `strategy_id`/account/risk/route、AI 解释文本、长 timeout 或自动 retry 作为安全许可；
- capability 的发行者/hash/module/entry point 未受信任清单约束，或 `config.yaml` 在预检后可被 symlink、权限变更或替换而不使 seal 失效；
- 未知 order、provider capability receipt 过期、配置封印改变、receipt/permit 过期或 AI evidence/producer schema 不兼容时继续开仓；
- `execution+risk+monitor` 在 AI 的 SimNow/production deployment profile 中没有同时成为必选、服务器端真实生效的边界；
- 把回测、shadow、模型评语、静态审阅或 wheel installation 写成盈利、实盘成交、生产 CTP、HFT 或策略自然信号准入证据。

## 最终裁决建议

在不纳入本意见前，Iteration 41 可继续被描述为“交易执行基础设施与双路径迁移计划”，其上限是现有的 `ARCHITECTURE_ACCEPTED` / `MIGRATION_ACCEPTED` 定义；它不能声明 AI 产品已经安全进入实盘执行。

当且仅当 WP41-I 与 AC41-47～55 通过，且外部交易/研究门仍按原规则独立通过时，才可增加更窄的结论：

> `AI_ASSISTED_MANAGED_DEPLOYMENT_INTEROP_ACCEPTED`：AI 产品能够生成和解释经验证的研究/部署证据，并在人工、risk、execution、monitor 和 provider 准入之后辅助受管部署；这不等于自动交易授权、盈利、真实成交、HFT 资格或 production CTP 准入。

## 参考资料

- [Iteration 41 实施计划](迭代计划.md)、[需求文档](需求文档.md)、[设计文档](设计文档.md)、[验收文档](验收文档.md)、[迁移矩阵](迁移矩阵.md)；
- [cloudQuant/backtrader-agent](https://github.com/cloudQuant/backtrader-agent)（离线 authoring、provenance、P0 renderer 限制）；
- [cloudQuant/backtrader-mcp](https://github.com/cloudQuant/backtrader-mcp)（local-first、backtest-only MCP 工具边界）；
- [cloudQuant/backtrader-skills](https://github.com/cloudQuant/backtrader-skills)（offline author/review/test 与 host eval 边界）；
- [MCP Architecture, 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/architecture)；
- [Tool annotations 的风险语义与限制](https://blog.modelcontextprotocol.io/posts/2026-03-16-tool-annotations/)。
