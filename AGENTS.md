# AGENTS.md

当前 opts 开发为[迭代 63：Gateway 统一转发与多策略共享会话](docs/_internal/opts/requirements/迭代63-Gateway统一转发与多策略共享会话/迭代计划.md)，已获持续开发与验收授权，整期 IN_PROGRESS / 未验收；局部实现和证据见[分轮记录](docs/_internal/opts/requirements/迭代63-Gateway统一转发与多策略共享会话/实施基线与分轮记录-2026-11-08.md)。Gateway 独立于策略进程，策略通过 config.yaml 连接；本地 SDK/Gateway 存储及回环切片不能当作完整服务已可用。迭代 62（opts 线）：[问题修复——SDK 写入准入、direct 直连基础层、BT direct 模式与 007_ctp 示例](docs/_internal/opts/requirements/迭代62-问题修复/迭代计划.md)，实施修改见其[计划修改记录](docs/_internal/opts/requirements/迭代62-问题修复/计划修改记录.md)，各步状态为 REVIEW_PENDING，由用户验收。迭代 60（[统一交易数据容器与多路径接入](docs/_internal/opts/requirements/迭代60-统一行情容器与低转换数据链路/迭代计划.md)，共享规则见[公共约定](docs/_internal/opts/requirements/迭代60-统一行情容器与低转换数据链路/_公共约定.md)）的合同仍是接入基础。迭代 53 已由用户确认废弃（2026-11-02，未成功），其“重构后停止等待审阅”的约束不再适用；其文档仅作历史参考。逐项迁移位置、破坏性变更及未验收事项以职责规范和迭代 60 计划为准。

## 先读：职责、现状与证据

分析、审查、提出迁移建议或修改本仓库前，先读取
[仓库目录与文件职责规范](docs/source/developer-guide/repository-responsibilities_zh.md)。
涉及跨仓库交易接入时，还需读取
[交易系统架构与项目职责](docs/TRADING_SYSTEM_ARCHITECTURE.md)、
bt_api_py 的 SDK 家族职责表（本机为 `/Users/yunjinqi/Documents/new_projects/bt_api_py/README.md`，Windows 环境为 `D:/bt_api_py/README.md`）和
[迭代 60 计划](docs/_internal/opts/requirements/迭代60-统一行情容器与低转换数据链路/迭代计划.md)。
跨仓工作使用各自现有 checkout，并读取目标仓适用的 AGENTS.md 与 README。

按需要查阅[逐文件职责盘点索引](docs/source/developer-guide/文件职责盘点-2026-11-01/index.md)；
其中交易接入与服务、数据与分析组件分别覆盖 BtApiStore/BtApiBroker 与 BtApiFeed。
盘点是带日期的静态快照，分析前应核对当前源码、调用者、未提交改动与包构建配置。
回答须区分既定职责、当前实现、目标设计、未验收内容和本次建议；不能将路径存在、源码审查或 fake 测试当成账户能力已通过。文档不一致时标出来源和状态，遵循用户当前指令，不擅自裁定事实。

本文件精简前的完整工作区原文（包含历史进度、未提交的用户修改及运行限制）已按原字节保存在
[AGENTS 历史快照](docs/_internal/opts/历史指引快照/AGENTS-历史快照-2026-11-01.md)。
它是历史记录，不整体覆盖当前指令；涉及其历史流程、受保留 host、已消费调用或证据时必须先阅读相关段落并遵守仍适用的限制。

## 跨项目职责

当前 SDK 工作树仅保留 Base、CTP、OKX、Binance 在 `bt_api/` 活跃目录，其余子仓已整体移至 `bt_api/deperated/` 待审阅；已安装的发行包并未因此卸载。以下为家族职责及历史目标，不代表归档组件当前启用或直连已验收。

以下为约定/目标边界；目标本身不证明相应能力已实现或验收：

- **Backtrader**：策略与 Cerebro 生命周期、Store/Feed/Broker 框架接口、BT Order/Position/Trade、bar 聚合与数据线、回调和通知，以及中立数据到框架对象的投影。
- **bt_api_py**：统一 BtApi facade、provider 发现与选择、跨包组合、route 与会话调用及中立 SDK 工作流。Backtrader 经此接口集成，不按交易所建立专属 BT adapter。
- 账户配置的原生方法别名由 provider 按 route 声明，SDK 负责发现和调用；OKX/Binance 源码接线未行为或发行验收。
- SDK 结果集合字段由 provider 声明；Binance/MEXC 含 `symbols`，CTP/OKX 当前只用 `data`，其余九家保留旧选择待核实。字段收窄与跨包行为未验收。
- SDK 拥有启动恢复、审批字段、readiness、funding 中立快照、managed refresh、capacity、route 名称投影及中立命令结果的统一合同；Binance 原生资金周期选择及终态费用补全能力声明、响应子码字段由 provider 明确声明；除 OKX 外其余 12 家当前仅保留待核实的 legacy 字段；Store 保留路由、触发时机、生命周期和 BT 错误投影。缺失合同不应推断权限或恢复成功，具体源码状态与未提交项见职责规范和迭代计划。
- SDK `managed_execution` 保存不依赖可选 execution 包的中立 claim 委托，`execution` 仍提供显式 journal 能力；SDK 已有 direct provider 路由骨架，CTP direct 会话、订单身份和回报链尚未闭合。此跨仓变更为未提交、未行为验收 WIP。
- **bt_api_base**：共享中立 DTO、协议、接口和基础组件；合同本身不证明账户、provider 或授权事实。 执行配置字段合同归 base，实际别名、环境要求与场所区域规则归 provider，SDK 按 route 装配；源码未验收。
- **bt_api_ctp / bt_api_okx / bt_api_binance 等 provider**：各自交易所的 native/session、鉴权、字段、请求、查询、回报、原生规则及向中立合同的转换。 CTP 的自动选择前置地址、quote V2 时间字段与原生回执验证由 provider 实现，SDK 保留流配置接线、队列绑定与证明签发；跨仓变更未验收。
- SDK CTP 凭据绑定 verifier 仍依赖已退役的 runtime 审核适配器；历史实现依赖旧 registry/配置/只读准入，其 direct 信任来源与 scope 迁移仍 OPEN，不以替换导入放宽校验。
- CTP 恢复查询行的原生账户/交易日字段和活动订单状态选择由 provider 实现；SDK 保留查询、会话栅栏与中立投影。旧状态语义尚待审阅后验收。
- CTP 恢复审批动作及剩余额度字段匹配由 provider 实现；SDK 保留审批、会话和授权生命周期。源码未行为或发行验收。
- CTP 原生查询类型到方法映射及公开会话字段选择归 provider；SDK 保留 route、transport 与调用控制。源码未行为验收。
- CTP 查询终包和原生账户行检查在 provider，SDK 保留查询前后会话授权栅栏；跨仓源码未提交、未行为验收。
- SDK 的 `bt_api_py._ctp_ingress` 拥有入口队列视图、封印及私有事件栅栏组件；`BtApi` 保留实例级绑定与授权时机。源码未行为验收。
- CTP 原生活动前置和 Trader/MD 身份关联检查在 provider；SDK 仍拥有实例、订阅、ingress 状态及授权入口。跨仓源码未提交、未行为验收。
- CTP 隔离连接探针由 provider 持有，SDK `bt_api_py.ctp_probe` 仅作惰性委托；源码未提交、未运行或验收。
- **bt_api_execution**：显式启用的可靠执行、journal、派发、对账与恢复；聚合、拆单和算法调度是目标能力，不能假称已实现。
- **bt_api_risk**：显式启用的业务风险政策、准入、额度与风险计算；选择后故障 fail-closed。SDK 旧风险分析拆分实现已迁入本包，旧顶层 SDK facade 惰性委托；分析合并和发行未验收。
- **bt_api_gateway**：可选的账户范围命令与读取路由、共享会话/读模型合同；按 SDK README 区分服务装配和 transport，不假定本包自行提供 provider client、凭据加载或 socket server。
- **bt_api_monitor**：可选监控、事件、指标和告警；观察不自动证明账户或订单真值，也不授予写权限。监控配置、指标和默认 registry 等由 Monitor 持有，SDK 旧入口引用它们；跨仓源码未行为或发行验收。
- **bt_api_runtime / bt_api_transport_zmq**：分别承担可选 SDK 服务装配和传输职责；两者不应成为默认 direct 的隐式前置，也不拥有交易所事实。
- 本地直接交易仍须执行基础身份、协议、会话、请求与回报关联、安全及 UNKNOWN 处理；未选择可选组件时不能强制依赖它们。选中组件失败不得静默回退。

## Backtrader 主要模块

- Store 已移除无调用的旧缓存时效工具、无读取的逐交易所缓存计时及单客户端持仓模式回退；只读服务和 SDK 分支仍保留。源码未行为验收。
- Store 合约规格、资金费率、手续费、账户配置、交易就绪和逐交易所余额使用统一 SDK；只读服务保留已配置合约元数据。旧单客户端回退移除，未行为验收。
- Store 持仓/开放订单读取仅使用 SDK 快照或只读服务 facade；旧缓存 TTL 参数仍接受但不生效。SDK 命令 dispatch 不再使用旧私有 `legacy` 名称，源码未行为验收。
- Store 已退役的 forwarding 客户端及路由分支已移除，旧配置仍明确拒绝；SDK 可选 gateway 另有独立职责。源码未行为验收。
- `store.py` / `stores/`：Store 公共接口、实例级生命周期、route 和 Feed/Broker 协调；不拥有 provider 原生协议真值。当前 Store 非强制单例，行为以源码和验收为准。
- `brokers/`、`broker.py`、`order.py`、`position.py`、`trade.py`、`commissions/`：BT 订单、成交、持仓、费用投影与通知；provider 原始账户/订单事实经 SDK 提供。
- 订单状态字段候选由各 provider 显式声明：Binance/OKX/CTP 原声明不变，其余十家各自声明 `status`、`order_status`、`state`；Base 旧策略不再声明候选。这是字段归属迁移，不证明原生状态覆盖，行为未验收。
- SDK 负责已验证中立提交回执的状态/错误码字段投影；Broker 保留订单错误标记。旧无调用原始响应拆包已移除，字段标记不证明回执来源。源码未行为验收。
- SDK 检查中立对账持仓归零和风险视图的不完整状态；Broker 保留检查时机、容差及本地订单/持仓。跨仓源码未提交、未行为验收。
- Store 直接绑定 SDK funding 刷新控制器，旧 `service/funding_refresh.py` 兼容层已移除；缓存标签和生命周期回调仍由 Store 提供。源码未行为验收。
- Store 直接持有 SDK metadata 探测服务；BT 桥保留 Store 回调、异常和结果映射，不再重复持有 SDK 服务锁或包装器。源码未行为验收。
- 中立对账、费用和状态合同与 SDK 调用归 base/SDK；BT 保留本地订单关联、状态投影、通知及费用分配。metadata 探测与 funding 刷新的通用工作流归 SDK，BT 保留 Store 回调和结果投影；合同和 DTO 不证明 provider 事实。
- SDK 统一加载中立订单命令类型，BT 执行适配器负责框架订单关联准备；Store 保留路由、单次绑定注册表与生命周期。跨仓源码未行为验收。
- `execution/reconciliation_projection.py` 持有 BT 对账结果及本地订单、Feed、Store 代际绑定的投影与消费前一次性校验；Store 保留委托和绑定注册表，SDK 持有中立校验。源码未行为验收。
- SDK `order_preflight.OrderPreflightCoordinator` 持有规则与经济性决策绑定和校验；BT 保留 Store 弱引用上下文及订单投影。跨仓源码未提交、未行为验收。
- SDK `execution_identity_fence` 持有宿主代际与身份向量的栅栏历史；Store 提供自身 generation 和当前 API 回调。身份 DTO 不证明账户权威；跨仓源码未行为验收。
- SDK `route_identity_projection` 负责中立路由集合比较和精确路由选择；BT 保留 Store 实例、模式和生命周期检查。路由名称不授予账户或写权限，源码未行为验收。
- 中立品种键字段检查和既有比较键由 SDK 提供；Broker 保留本地 Feed、订单和持仓关联。跨仓源码未提交、未行为验收，比较键不证明身份或授权。
- SDK 协调中立命令完成、丢弃和 UNKNOWN 状态，BT 保留订单引用与回执投影；跨仓源码未提交、未行为验收。
- Direct execution 配置字段提取、命令队列与 funding 刷新选项规范化由 SDK 持有；Store 保留自己的会话和框架投影。源码未行为验收。
- 账户风险的中立读取、单实例缓存、锁和刷新预约归 SDK；BT 持有 Store 代际与身份回调，业务风控政策仍归可选 risk。跨仓源码未提交、未行为验收。
- BT 的单币种余额约束由余额投影模块统一，Store 委托检查并保留缓存；SDK/provider 仍拥有账户事实。源码未行为验收。
- SDK 余额读取工作流检查配置与实时 route 一致性及批次完整性；Store 提供实例 route 和 BT 结果投影，路由名称不证明账户权威。源码未行为验收。
- SDK 的 account balance/position 读取工作流拥有中立端口、快照及 lease 校验；Store 直接构造 SDK 工作流，BT 保留 Feed 绑定与 Position 投影。服务观察的中立类型、配置与异常也直接从 SDK 导入。该跨仓迁移是未提交、未行为验收的 WIP。
- `feeds/`、`feed.py`、`filters/`、`resamplerfilter.py`：Feed 生命周期、BT 数据线、数据时钟、过滤与 bar 聚合；不伪造来源时钟或交易授权。
- `LiveFeedBase` 继承 `DataBase` 并定义实盘 Feed 抽象合同，`BtApiFeed` 经其继承框架 Feed；生命周期委托、MRO、参数和数据线初始化尚未行为验收。
- `strategies.ctp_future.CtpFutureStrategy` 经 `BtApiBroker` 和 Store 查询主力、次主力；SDK `futures_contract_lookup` 组合参考行情快照与选择，`futures_selection` 持有中立选择模型和算法，BT `futures/` 保留日历网格及换月等框架投影。默认实时查询因新鲜度不可证明而不可用，显式参考模式不证明实时性。旧六个 `feeds/futures_*` 模块已移除；不自动换月或下单，跨仓导入、发行及行为未验收。
- `BtApiFeed` 已移除内置的服务恢复报价绑定及其配置；Broker 仍要求恢复路径提供并验证 Feed/bar 报价绑定，不能以缺失绑定放宽校验。SDK 保留中立合同供现有调用方使用；源码变更未行为验收。
- SDK 只读 bar 历史/实时衔接组件持有每个消费流的 bootstrap、去重、顺序和历史重叠状态；BT 注入 bar 恒等投影并绑定 Feed。源码未行为验收。
- SDK 只读 bar 流 session 持有 bootstrap epoch 与序号，BT 保留 bar 投影和 Feed 绑定；跨仓源码未提交、未行为验收。
- SDK `service_market_bindings` 拥有中立 bar/订单簿绑定类型；BT 服务桥和可选 SDK runtime 使用该类型。runtime 的旧 Store 路径已更新，旧测试仍待审阅后处理。
- 只读服务的中立绑定集合、账户覆盖与客户端去重检查归 SDK，BT 保留 Feed/持仓映射；跨仓源码未行为验收。
- SDK 行情订阅 session 持有每个消费者独立的句柄映射和恢复/退订状态；BT 提供 Store route、生命周期及健康投影回调。跨仓源码未提交、未行为验收。
- 中立行情事件时间字段选择与 UTC 转换归 SDK `market_tick_contracts`；Feed 保留日志和 BT 数据线。时间转换不建立时钟证明，源码未行为验收。
- SDK 拥有中立行情 clock/freshness、质量、连接/订阅代际分类、stream 合同及事件连续性投影；BT 保留 token、路由、投递计数、本地序列、价格网格及 bar 时钟。投影不建立来源证明，跨仓源码未行为验收。
- Store 行情投递状态集中管理 SDK 队列观察的 BT 丢弃和健康投影，移除重复的私有转发模块；源码未行为验收。
- SDK 事件到 BT Broker、Feed 和通知的分发归 `service/store_event_dispatch.py`，未验证订单回报的本地绑定及 UNKNOWN 投影归 execution；Store 保留事件消费锁。源码未行为验收。
- `service/store_lifecycle.py` 协调 BT Store 启动、重启、API 就绪及关闭，Store 持有实例状态，SDK 各组件保留其资源；生命周期、锁和异常行为未验收。
- SDK `market_stream_contracts` 负责中立行情频道和盘口深度的输入规范化；`market_tick_contracts` 统一中立行情数值规范化，Feed 保留数据线和 bar 投影。Store 负责订阅时机与生命周期。跨仓源码未行为验收。
- `execution/`、`factor_execution/`、`service/`：当前迭代的 BT 执行适配、策略/因子事实和框架生命周期桥接候选；durable journal、provider authority 与通用服务能力归相应 SDK owner，逐函数确认，当前工作树仍有未验收迁移。中立账户簿 route 类型直接从 `bt_api_py.service_route_selection` 导入，BT 不再重导出。
- SDK 负责因子订单中立客户端 ID 查重与关联；BT 提供本地事实并构造框架关联结果。跨仓源码未提交、未行为验收。
- 显式订单身份字段由 Binance/OKX/CTP 按 route 声明，其余十家显式选择旧集合；未声明的已知别名产生 execution_unknown 错误，行为未验收。
- 订单来源中立字段归 Base，13 家 provider 各自声明原生字段及别名并选用 v5/v6；Risk/group 证明仅使用 v6，v1–v4 旧合同已移除。Bybit/dYdX/Kraken 的成交原生别名为空、字段覆盖待查；源码为未提交 WIP，行为与发行尚未验收。
- SimNow 原生订单、撤单、查询及回报投影和原生查询组织归 CTP provider；SDK 保留会话来源核对与统一请求接线，源码未行为验收。
- CTP native gate 的 SDK 审批与凭据 scope 检查已提取至 SDK，provider 保留原生会话检查且仍调用 SDK gate 入口；旧 runtime 凭据来源和剩余反向依赖仍 OPEN，源码未行为验收。
- CTP 风险预算 journal 的数值、行状态投影及转换规则位于 Risk；SDK 保留会话来源、锁、预留能力与持久化栅栏，源码未行为验收。
- 因子本地归属账本的 SQLite schema、核验、幂等写入和容量记账/读取位于 `bt_api_execution.factor_position_attribution`，经 `bt_api_py.factor_position_attribution` 提供；BT 保留 Broker 持仓比较。BT journal 端口按实例显式组合，进程默认注册须单独显式安装。它不证明 provider 事实，当前为未提交、未行为验收的 WIP。
- `cerebro.py` / `_cerebro/`、`strategy.py`、`line*.py`：引擎唯一调度、策略回调、线运算与多数据时钟；不新增第二套策略调度器。
- `research/`、`indicators/`、`observers/`、`analyzers/`、`sizers/`：各自的研究、指标、观察、分析和仓位计算；不私自创建账户事实或绕过执行/风控边界。
- `strategies/factor_strategy.py`：离线因子研究策略与网格采集；因子、研究协议、面板和 sink 仍归 `research/`。迭代 61 源码迁移和图驱动修复尚待验收；按用户决定不保留旧 `backtrader.research.FactorStrategy` 与 `backtrader.research.factor_strategy` 入口。
- `tests/` 是验证，`examples/` 展示使用，`scripts/` / `tools/` 为任务入口，`docs/` 解释和记录；产品代码不依赖这些目录作为运行时实现。

## 持久开发流程

- Backtrader、`D:/bt_api_py` 和各 SDK 子仓在各自现有 `dev` checkout 开发，用户未要求时不新建 worktree；不直接推送 master 或 development。
- 小轮推进：实现、完成本轮约定的检查、仅暂存接受的文件或 hunks、提交相应 dev、记录范围/结果/仓库/分支/commit；SDK 子包先提交，再更新父仓 gitlink。保留所有无关 dirty 修改与用户文件。
- 检查历史工作区中与目标相关的已验证工作；不要因成果留在其他 checkout 重复开发。验收失败继续修复，明确源码、fake、安装包及真实账户证据级别。
- 同一适用策略跨 backtest、replay、shadow、paper、live 复用是架构目标，不表示当前模式全部可用；切换依配置与相应 Feed/Broker/Store，模式名不授予写权限。
- 迭代 62 按 62.01–62.09 推进：写入准入只在 SDK（默认关闭），execution/risk/gateway/monitor 为可选组件；BT direct 模式在 `BtApiBroker` 内（`brokers/_btapi_direct_mode.py`），策略目录本地状态在 `backtrader/live_state/`；SimNow/demo 证据只说明模拟账户行为，必需项为 GAP/NOT_RUN 时不得声称完成。
- 迭代 60 按阶段推进（阶段一 60.01–05、阶段二 60.06–07、阶段三 60.08–10）；每步交付说明记录范围、仓库/commit、检查结果和证据等级，最终接受由用户确认。迭代 53 已废弃，不再作为前置或约束。

## 私密输入与历史限制

真实忽略的 `.env`、`config.yaml`、凭据和私密捕获不属于源码审查材料。子代理和普通审查只用公开源码、模板、测试及脱敏公开快照；授权账户读取须使用受保护的有界 reader，仅输出有限类别或布尔值，不输出值、原始行或凭据哈希。
用户已授权删除相关已冻结历史证据及无用旧 API；该授权不包括清空已消费 generation、重跑已接受实际调用、账户操作或处置 retained host。保留相关 retained host 与源/结果身份；不得自行退出、kill 或手动释放。具体限制和结果见历史快照及相关迭代证据；遇到不确定状态不得假设已关闭或批准重试。

## 子代理

用户允许委派时，优先使用 `model="gpt-6.1-terra"`、
`reasoning_effort="xhigh"`、`fork_turns="none"`，并在任务中提供明确上下文、适用职责资料与写入范围；用户另有指示时从其指示。遵守用户设定的子代理数量上限。主代理模型不因该偏好改变。

## 开发与验证

- Python 以源码和 `setup.py` / `pyproject.toml` 为准；当前核心构造使用 mixin/显式 factory，不重新引入 metaclass。
- 相关命令：`make test-fast`、`make test-slow`、`make test-strategies`、`make test-all`、`make test-performance`；针对变更选择必要验证。指标注册、多 Feed 时钟或 minperiod 的变更需特别覆盖策略回归。
- `make format-check`、`make lint`、`make type-check` 可用于相应质量检查；不以测试数量代替实际合同覆盖，也不重复已接受的历史 QA。
- 新建或更新中文 Markdown 默认 UTF-8 BOM，尊重冻结证据和既有格式例外；严格 UTF-8 解码、确认无替换符，并用 Windows PowerShell 5.1 默认读取确认中文可读。
