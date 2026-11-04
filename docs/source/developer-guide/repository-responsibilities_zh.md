# 仓库目录与文件职责规范

> 当前 SDK 工作树的直连范围保留 Base、CTP、OKX、Binance，其余 17 个子仓整体迁入 `bt_api/deperated/`，仍是 Git 子模块且未卸载发行包。旧路径的部分历史验收和治理基线待单独审阅；本次目录迁移不证明直连或安装行为通过。

> 持仓模式写入确认码由 provider 显式声明；Base 默认不再选择原生码。Binance、CTP 和 OKX 非 SWAP 保留原有 `200`，OKX SWAP 保留 `0`，其他十家通过历史策略保留 `200`；这些旧值不证明各场所能力或实际协议。第三方仅继承 Base 时不再隐式获得确认码；动态策略、发行及行为待审阅后验收。

> Binance/OKX 绑定式只读 runtime 的路由注册、精确 owner 和配置校验归各自 provider；Base 中立路由携带 SDK 注入的 API 类型，SDK 负责组合及有限错误转换。旧 SDK 专用注册模块和 `compose_binance_read_only_runtime` / `compose_okx_read_only_runtime` 已移除；按配置创建新 owner 可用中立 `compose_read_only_runtime`，它与复用已有 owner 的语义不同。跨包入口、线程、清理和行为待审阅后验收。CTP runtime 的路由、环境和合约字段校验归 `bt_api_ctp.managed_runtime_route_validation`；SDK 保留授权期限、会话与生命周期。该 CTP 专用 SDK 模块导入需要 provider，来源和行为未验收。CTP 自动结算确认的预检配置解析与禁用归 `bt_api_ctp.preflight_settings`，SDK 保留路由选择、调用时机及原错误类型；仅 CTP 路由按需加载 provider，缺失时无法完成预检，跨包与行为待审阅后验收。

> 执行账本的凭据绑定身份格式由 `bt_api_base.execution_ledger_identity_policy` 定义，并由 provider 级入口声明；SDK 不再以 OKX/Binance 名称硬编码。内置 13 家保持原格式选择（两家凭据绑定，其余沿用历史格式），这不证明账户身份。声明缺失或插件不可发现时执行身份路径失败，历史迁移和自定义 provider 属破坏性变化；成功选择在进程内缓存。账本兼容、安装发现与行为待审阅后验收。中立风险读取是否仍需原生账户绑定由独立 provider 合同 `account_risk_source_policy` 声明；CTP 仍不可用，其他 12 家沿用旧分支，声明本身不证明来源。未注册 provider 的风险读取会失败，发现和行为待审阅后验收。

> Gateway SDK 组合器仅接受中立 `GatewayMarketBinding` 和受信 provider 工厂；删除 `GatewayOkxMarketBinding` 与 `okx_market` 参数，OKX 调用方显式提供 `bt_api_okx.market_provider.OkxTickerQueueMarketProvider`。原绑定要求每个主体覆盖全部 key，通用绑定允许非空子集；OKX key 在订阅时校验，队列/连接参数在 provider 构造时校验，校验时机发生变化。旧调用及行为待审阅后验收。

> CTP 受管风险订单 payload 的构造、schema 和撤单目标匹配归 `bt_api_ctp.risk_dispatch_binding`；Base 声明可选的 provider 合同，SDK 保留证据选择，Risk 日志保留 claim、事件链和 writer fence。带 schema 的目标订单现在要求对应 provider 显式声明并校验，其他尚未接入的 schema 会失败，是破坏性变更。日志兼容、provider 缺失、跨包和行为待审阅后验收。CTP 原生报单字段一致性、派发绑定、零成交观察载荷及零成交字段对照归该 provider；SDK 保留会话、类型与来源核对、日志写入和失败状态。provider 是字段对照的信任依赖。风险订单持仓维度是否需要原生投影由所选 provider 策略声明；CTP 的方向/开平码及维度一致性归 `bt_api_ctp.risk_source_position_projection`，SDK 按路由调用策略，不再按交易所名称分支。CTP 声明需要投影，其他 12 家保留历史通用路径；无声明或无投影时拒绝，第三方策略需更新。SDK 保留来源/会话与错误类型，provider 是字段判断的信任依赖；入口发现、动态策略和行为待审阅后验收。

> 中立盘口最优报价检查和中间价计算归 SDK `market_stream_contracts.orderbook_midpoint`；Feed 保留事件丢弃、分发及 bar 数据线写入。盘口来源、时间与行为待审阅后验收。tick 交易日/行动日字段由 provider 声明：CTP 保留中立字段及原生 `TradingDay`/`ActionDay`，其余十二家显式仅声明中立 `trading_day`/`action_day`，Base 默认为 None；旧十家的大写候选已移除，属于破坏性收窄，动态字段覆盖及行为待审阅后验收；Base 的盘口序列与审计默认不再包含 Binance 原生字段，十家历史策略保持原值。Base 的账户权限、持仓模式、事件标识和合约符号默认也只保留中立字段；余额、持仓、订单、成交、状态和持仓模式别名中的部分场所原生字段从中立默认移至显式历史策略；其中还包括 CTP 容器字段 `all_traded`、`order_sys_id`、`yd_position`、`volume_multiple` 和 `trade_fee_symbol`。三家已声明策略保持各自字段，其余十家显式沿用旧字段，四家原引用 Base 默认映射的 provider 已改为引用历史映射。第三方继承 Base 的行为会改变，字段覆盖与行为待审阅后验收。

> 订单状态与成交费用字段候选由选定 provider 策略声明；订单状态候选由 13 家 provider 各自显式声明，Binance/OKX/CTP 原声明不变，其余十家声明 `status`、`order_status`、`state`，Base 旧策略不再声明状态字段候选。成交费用仍按相应策略选择。该字段归属迁移不证明原生状态覆盖；未声明的策略明确报错，第三方策略、动态字段及行为待审阅后验收。下单持仓模式并发栅栏也按 provider 路由声明：OKX/Binance 沿用启用，其余内置路由沿用旧不启用行为；缺少声明的路由拒绝下单，属于破坏性变更。声明不证明其他场所的持仓模式能力。

> 13 家 provider 显式声明 `trade_id_fields`，包含中立字段及容器源码确认的本场所原生字段；Base 默认为 None，SDK 负责按所选策略读取。Bybit/dYdX/Kraken 无额外原生字段，未确认的通用 `id`/`tradeId` 不再跨场所猜测；字段收窄或新增是破坏性变化。`group_fill` 来源证明别名合同独立，Gateio/HTX/MEXC 等 ID 仍待核实，归一化不证明其来源；动态输入与行为未验收。

> 中立持仓行与已配置路由、合约身份的匹配归 SDK `bt_api_py.broker_event_envelope.resolve_neutral_position_route`；Broker 继续收集框架 Feed/订单绑定和维护本地持仓。匹配不证明账户来源，跨包及行为待审阅后验收。

> 未验证执行事件的中立标识字段投影归 SDK `bt_api_py.execution_event_projection`；Backtrader 保留本地订单绑定、UNKNOWN 更新和丢弃记录接线，旧投影入口委托 SDK。Store 的已完成 bar 队列及其框架投递状态继续归 Backtrader。跨包导入及行为待审阅后验收。

> CTP 受管订单与撤单身份值类型归 `bt_api_ctp.managed_request_identity`；SDK 通用请求在使用这些字段时惰性引用原类型，旧 SDK 导出保留类型别名。类型模块名、序列化、注解解析、来源绑定及可选依赖发行兼容性待审阅后验收；身份值不授予执行权限。

> 显式订单身份字段与方向候选按 route 选择：Binance/OKX/CTP 声明各自别名，其余十家显式选择旧合同；所选策略未声明的已知身份别名触发标记执行未知的错误，避免静默忽略冲突。第三方策略、动态字段、entry point、账本和行为待审阅后验收。

> 订单来源投影的中立字段归 Base，13 家 provider 各自声明原生字段和别名并选用 v5/v6；Risk/group 证明仅使用 v6，绑定路由及所选别名摘要，group 来源事件持久记录并重验摘要。v1–v4 旧合同已移除；Bybit/dYdX/Kraken 的成交原生别名为空，字段覆盖待查。SDK 按 route 选择，字段收窄改变摘要和版本；本项为未提交源码 WIP，动态别名、旧记录处理、证明链、跨包行为和发行待审阅后验收。

> SimNow 原生订单、撤单、查询请求、回报与开放委托行类型/投影及七类原生查询组织归 `bt_api_ctp.simnow_execution_projection`；SDK `ctp_simnow_execution` 注入统一请求类型与查询入口，保留会话前后来源核对。开放委托投影参与身份一致性检查，是信任依赖。原 SDK 类型和结果映射导出同一对象，撤单构造入口为注入 SDK 请求类型的薄桥，CTP 模块导入依赖、类型模块名和行为待审阅后验收。

> CTP native gate 的 SDK 审批上下文、凭据绑定、选定前置 scope 及 entry/recovery scope 检查归 SDK `ctp_gate_approval_validation`；provider 仍在原锁内调用，并负责原生会话与前置状态。旧 runtime 凭据来源与 provider 对 SDK 的剩余反向依赖仍 OPEN；跨包信任、锁和行为待审阅后验收。

> 中立行情连接代际和订阅代际的有效性、先后及变更分类归 SDK `market_tick_contracts.classify_market_scope`；Feed 保留已观察代际、bar 清空和质量标记。该分类不证明来源，旧字段及行为待审阅后验收。

> CTP 风险预算 journal 的数值、序列化、行状态投影及预算转换规则归 `bt_api_risk.ctp_budget_journal_projection`；SDK 会话继续持有来源绑定、预留 capability、锁、writer fence 与持久恢复。Risk 延迟加载，旧 journal、依赖及行为待审阅后验收。

> 因子执行 journal 的 BT 桥按 journal 实例显式组合端口及 provider authority；仅显式安装使用 Execution 的进程默认注册。端口实例绑定、并发与旧调用兼容性待审阅后验收。

> CTP 受管开放订单和终态订单的原生查询行解析及目标字段一致性检查归 `bt_api_ctp.managed_order_query_projection`；SDK 保留查询栅栏、回调窗口、会话和证据签发。provider 是目标字段判断的信任依赖；来源、授权和行为待审阅验收。

> CTP 受管订单查询的原生字段集合、文本与整数检查、方向/开平和目标请求字段投影归 `bt_api_ctp.managed_order_query_projection`；SDK 保留查询栅栏、来源检查、会话和证据签发。provider 代码参与原有 intent/会话字段一致性检查，不单独建立授权；源码信任、跨包与行为待审阅验收。

> CTP 终态订单查询的字段和不可用结果类型归 `bt_api_ctp.terminal_order_query_contract`；SDK reader 保留会话、查询、签发与原实例 readback，旧 SDK 导出同一类型。类型不自行证明来源；类模块名、证据引用、managed extra 与行为待审阅验收。

> CTP 原生 ExchangeID/OrderSysID 的受管订单标识编解码归 `bt_api_ctp.managed_order_identifier`；SDK 会话与对账保留原调用边界并引用同一函数。该值不证明订单或授权；需 Execution managed extra，来源绑定和跨包行为待审阅验收。

> 费用事实 journal 端口的字段完整性与 provider 来源租约委托归 SDK `fee_pair_facts_journal_port`；BT 子类注入精确框架事实类型，SDK 保留显式 provider authority。缺失费用事实仍不可用；继承、跨包导入和行为待审阅验收。

> 受管 owner 线程的有界同步邮箱、开始前取消与开始后不确定超时机制归 SDK `managed_execution_mailbox`；具体运行时保留原线程、就绪/租约状态、锁和维护/关闭时机。邮箱不授予执行权限；MRO、并发与行为待审阅验收。

> 已归一化持仓数量与平仓状态的共同投影归 SDK `account_risk_projection.normalized_positions_are_flat`；调用方保留查询、账户绑定、完整性和原错误类型。持仓审计阻塞后的订单方向、平仓数量判断归 SDK `account_risk_projection.position_audit_close_error`；Broker 保留审计状态、BT 订单和本地持仓，并以延迟回调提供事实。该判断不建立账户来源或写入授权；跨包行为待审阅验收。

> Feed 的配置合约元数据价格最小变动查找归 SDK `instrument_metadata_aliases.configured_metadata_price_tick`；Feed 保留显式配置优先级、价格网格及 bar 判断。历史别名不证明来源；跨包导入和行为待审阅验收。

> CTP Trader 前置地址和连接配置类型归 `bt_api_ctp.trader_connection_config`；SDK CTP 受管执行模块导入同一类型并继续装配生命周期和授权。此专用 SDK 模块导入需要 CTP provider，类型模块名、Python 版本与发行行为待审阅验收。

> Execution 事件、撤单记录和执行记录的有限来源投影归 `bt_api_execution.source_projection`；SDK `service_execution_risk_journal_bridge` 在显式使用撤单来源时惰性调用，Risk 日志保留摘要和 writer fence。投影不证明远端或授权；跨包发行及行为待审阅验收。 Execution 撤单事件筛选及形状校验归 `bt_api_execution.cancel_observation_projection`；SDK Risk 桥保留 claim/目标身份、证明、摘要及 fence，并注入原错误类型。缺少新 Execution 模块时会在身份检查后导入失败；跨仓源码及行为未验收。

> Risk CLOSE 证明持久载荷的编解码归 `bt_api_risk.order_proof_payload`，持仓方向及桶维度解析归 Risk `position_payload`；SDK 日志保留 source/scope、writer fence、原序列化格式注入及错误转换。载荷校验不证明来源或授权；旧数据、错误边界和跨包行为待审阅验收。

> 订单来源快照格式及摘要一致性核对归 Base `order_provenance_projection`；订单估值摘要与汇率字段匹配归 Risk `order_valuation`。SDK 日志注入既有序列化与摘要函数，保留来源绑定、事件链及 writer fence。字段一致性不证明来源真实性；跨包导入、异常及行为待审阅验收。

> 行情 V2 schema 由选定 provider 策略声明，CTP 自行提供其 schema；Base 默认无声明。SDK 负责按 route 识别并保留原 CTP 父证明核验，未声明的 `*.quote.v2` 拒绝，避免通用行情降级。其他 provider 的证明能力尚未实现；跨包合同、schema 命名保留规则和行为待审阅验收。

> 订单身份的 Binance 用户流嵌套 `o`/`S`/`ps` 形状由 Binance provider 声明；Base 仅执行选定策略的中立提取，其他 provider 不再默认解析该嵌套对象。未排除其他 provider 动态使用相同形状，顶层历史别名仍待逐场所核对；源码、字段冲突和发行行为待审阅验收。

> CTP 执行身份的 I9 类型来源、scope/OrderRef 及 journal 镜像核对归 SDK `_ctp_execution_identity_bridge`；执行会话继续持有锁、日志和使用时授权。该桥不分配身份或授予权限；类型模块名、源码绑定和行为待审阅验收。

> SDK _ctp_recovery_query 负责 CTP 恢复查询绑定、双轮一致性和入口栅栏及公开计划过滤；BtApi 继续持有会话、授权、队列和锁。恢复行的合约字段选择、买卖/持仓方向、开平标识、活动订单判断、订单与意图匹配和成交键生成归 `bt_api_ctp.recovery_row_projection`；SDK 注入原取值及合约解析，保留证明、日志和授权状态。provider 是字段判断的信任依赖；迁移不建立来源或账户事实，跨包导入和行为待审阅验收。

> Base 合约规则与元数据默认字段不再选取 baseAsset、quoteAsset、marginAsset、contractType、stepSize；Binance provider 显式保留。其他 provider 源码搜索未见这五项，但无法证明动态输入完整；旧默认字段收窄、跨包发行与行为待审阅验收。

> service/_service_execution_recovery.py 负责服务恢复与 Backtrader 订单、策略持仓、交易通知及框架错误的绑定；SDK 持有恢复流与持久状态。适配器继承该桥并重导出相同错误类；类型模块名、私有导出、MRO 和行为待审阅验收。

> 配置持仓数量单位的别名查找、合约键匹配和唯一性检查归 SDK instrument_metadata_aliases；Store 提供配置及 Feed 名称，继续负责 Feed/route 绑定和框架持仓投影。配置匹配不证明 provider 身份，源码及跨包行为未验收。

> 因子本地持仓快照的 journal 端口入口位于 bt_api_execution.factor_position_journal_port，经 SDK 继承；BT 端口子类注入框架错误类型。它使用调用方数量，不建立 provider 事实；源码及跨包行为未验收。

> 因子本地归属结果与调用方数量的比较由 bt_api_execution.factor_position_attribution 持有，bt_api_py 提供统一入口与容量错误转换；BT journal 端口只负责框架接线。该比较不证明 provider 账户状态；旧 BT 模块和导出退役，源码与事务行为未验收。

> execution/store_reconciliation_bridge.py 负责 Store 本地订单引用、实例会话、队列与 SDK 对账结果的框架接线；Store 保留实例状态，SDK 保留对账接口、句柄签发和验证。14 个方法经 mixin 使用 Store 状态；模块导入、MRO 和行为待审阅验收。

> Base 合约元数据投影消费 provider 给出的中立默认值；Binance provider 负责其 filters 解析。严格合约规则的最小名义价值由所选 provider 返回，SDK 不解析原生过滤器。OKX/CTP provider 暂保留旧兼容字段；入口返回合同、异常顺序、跨仓发行和行为待审阅验收。

> CTP 执行合约标识、组合合约和原生报单字段的规范化归 `bt_api_ctp.execution_instrument`；SDK 惰性调用它，并继续独立持有证明和授权状态。原生 client 使用同一解析，解析不授予权限；共用解析对信任边界、行为和发行的影响待审阅验收。

> SDK `queued_command_runtime` 负责开平仓优先级和当前队列代际内未发送开仓项的字段匹配；Store 注入自身订单引用及当前代际并保留绑定状态、回执和通知。匹配不证明远端状态，跨仓源码未行为或发行验收。

> `service/_store_managed_bridge.py` 负责 Store 到显式注入的 managed execution/group 适配器及 Broker 投影的框架绑定；Store 保留实例和连接状态，SDK/Execution 保留调度、持久化和授权。`stores/_btapi_errors.py` 提供 Store 错误类型，原 `btapistore` 模块仍导出同一类；类型模块名、MRO 和行为未验收。

> 中立配置元数据及最新行情快照的历史别名匹配、InstrumentSpec 兼容字段补齐归 SDK `instrument_metadata_aliases`；BT Store 保留缓存写入、快照复制、锁和 SDK 调用。别名匹配不证明合约身份；跨仓源码未行为或发行验收。

> 配置元数据的中立 `MarketInstrumentKey` 候选选择、类型/一致性及原生名称匹配归 SDK `instrument_metadata_aliases`；Store 保留 Feed 名称、route 和实例模式检查。配置匹配不证明 provider 合约权威；源码未行为或发行验收。

> `feeds/_btapi_cohort.py` 负责 Backtrader 实时 bar cohort 的 Feed 成员准备、时间槽、Cerebro 批次交付和本地数据线绑定；`BtApiFeed` 通过 mixin 保留实例状态并与其共享唯一缺失值 sentinel。行情数据和中立合同仍归 SDK/provider；源码未行为或导入验收。

> `feeds/livefeed.py` 的 `LiveFeedBase` 继承框架 `DataBase` 并定义实盘 Feed 抽象合同；`BtApiFeed` 经该基类取得框架 Feed 功能。抽象生命周期方法委托 `DataBase`；MRO、初始化和行为尚未验收。

> 报价窗口的中立 tick 字段及时间投影归 SDK `market_tick_contracts.quote_capture_mapping`；Feed 提供显示品种名称并保留窗口容量、bar 和投递。投影不证明行情来源或时钟真实性；跨仓源码未行为或发行验收。

> `brokers/_btapi_reconciliation.py` 负责中立 SDK 对账结果到框架 Order/Position、Broker 状态和回调的投影；SDK 继续持有查询和对账事实。方法经 Broker mixin 使用同一实例状态；源码未行为或导入验收。

> `brokers/_btapi_recovery.py` 负责 Backtrader Order/Position 恢复、策略绑定和通知投影；`BtApiBroker` 通过 mixin 持有相同实例状态，中立恢复合同及持久 journal 归 SDK/Execution。源码迁移未行为或导入验收。

> 订单来源有限字段投影、标量处理及摘要算法归 `bt_api_base.order_provenance_projection`；SDK 按 route 选择来源字段和 schema 并保留行对齐；13 家 provider 的声明及待核查字段覆盖见上文。投影或摘要不证明来源真实，源码未行为或发行验收。

> 中立账本订单显式身份字段、值规范化及冲突比较归 `bt_api_base.execution_identity_projection`；SDK 提供自身账本字段集合、route 及 provider 数量单位解析，保留账本状态和更新。比较不证明身份或授权；跨仓源码未行为或发行验收。

> SDK 订单身份核对的 native 数量单位由选定 route 的 provider 归一化策略提供，不再按交易所名称推断；缺失或无效声明明确失败。其他 route 目前部分继承旧默认单位，实际单位和跨包行为未验收。

> 持仓风险事实的重估、策略汇总、一致性检查和精确 account 合计归 `bt_api_risk.position_baseline`；SDK 订单日志保留摘要格式回调、Gateway 来源收据、快照摘要、日志与 writer fence。该重估不证明来源，跨仓源码未行为或发行验收。

> CTP 行情父会话证明的 seal、签发与核对归 SDK `_ctp_market_attestation`，`BtApi` 在自身入口签发，通用归一化调用其核对；provider 只执行字段投影，不能签发 SDK 父证明。类型的模块名已变更，源码未行为或发行验收。

> 配置合约元数据的历史别名候选算法由 SDK `instrument_metadata_aliases` 持有；BT Store 保留输入文本转换和本地匹配调用。该启发式不证明场所或合约身份，源码未行为或发行验收。

> 状态：现行开发约定；盘点基准：2026-11-01 的 `dev` 工作区，包含尚未提交的迭代 53 迁移。本文不是逐文件代码审计报告，也不证明未验收代码可用。首次使用和每次准备修改本仓库前，先读本文，并以实际代码、构建配置及适用的 `AGENTS.md` 为准。

> SDK 订单方向解析器由 route 选出的 provider 接收完整行；Binance 的 `o` 嵌套字段选择在 Binance provider。base 旧字段解析器与第三方 projector 的入口签名已变更，源码尚未行为及发行验收。

> 受管恢复的中立 paper fill 字段、事件身份、绑定和经济字段核对，以及恢复上下文的标量编码与精确 decimal 检查由 `bt_api_py.service_recovery` 提供；Broker 保留框架 Feed/bar、佣金和本地账户簿事实的关联及框架浮点转换。此源码接线未行为验收。

> 中立恢复报价修订与成交的字段关联归 `bt_api_py.service_recovery_quote`；Broker 保留报价与 Feed/bar 的绑定校验。`BtApiFeed` 已移除内置报价绑定，因此其依赖该绑定的恢复路径不可用；字段相等不证明来源真实性。此源码变更未行为验收。

> 受管服务运行时的安全状态、计数、错误码投影及多 runtime 汇总归 `bt_api_py.service_execution_assembly`；Backtrader session 保留框架生命周期、清理错误归类及报告。此源码接线未行为验收。

> Store 的行情投递状态 owner 负责 SDK 轮询结果的 BT 连续性、丢失和交付投影；SDK 仍持有上游订阅和队列。此源码接线未行为验收。

> SDK 与 Monitor 日志关联标识的共享 ContextVar 归 `bt_api_base.logging_context`，共享日志级别解析及显式配置归 `bt_api_base.logging_setup`；Monitor 负责日志采集和输出，共享标识不证明账户或授权。此源码接线未行为验收。

> Monitor 阈值规则与 worker 归 Monitor，将其包装为 SDK Host 资源的组合入口归 `bt_api_py.monitor_threshold_composition`；旧 Monitor 装配导出已移除。此源码接线未行为验收。

> 指标类型、默认 registry、collector、system_metrics、exchange_health、grafana、装饰器、Prometheus 和 ELK 由 Monitor 唯一持有；SDK 旧监控入口引用这些 owner，相应旧子模块路径退役。监控配置归 Monitor，并选用原 SDK 配置校验和启动失败清理；SDK 旧配置子模块路径退役。跨仓源码未行为或发行验收。

> SDK 合同 mapping/dataclass 与嵌套映射复制归 `bt_api_py.contract_mapping`；Store 惰性委托并保留自身错误类型，旧 BT 私有模块移除。新增 SDK 接口依赖，源码未行为或发行验收。

> 受管恢复的策略持仓引用和本地键引用格式校验由 `bt_api_py.service_recovery` 唯一提供；BT 仍按 Feed 名称与 tradeid 生成本地键并负责框架对象绑定。源码未行为或发行验收。

> SDK 旧风险分析模块已按职责迁至可选 `bt_api_risk`，使用原 SDK 拆分版覆盖 Risk 包中的分析副本；独立准入和账本模块保留。SDK 保留惰性顶层 facade，旧风险子模块路径退役。此合并可能改变 Risk 分析行为，跨仓源码未行为或发行验收。

> SDK 原 `bt_api_py.backtrader.BtApiBroker` 只是 mock adapter 占位，已退役；BT 框架 Broker/Store 属于 Backtrader，SDK 保留中立 facade 和适配能力。旧导入路径为破坏性变更，源码未发行验收。

> SDK 原 Gateway `FeedBrokerAdapter` 依赖旧订单模型，仅有旧测试调用，已从源码导出和分发入口移除；其后续盘点显示旧 `bt_api.adapters` 仅内置 mock、未接入 SDK 的交易所插件和服务路径，旧 broker 注册、模型和模拟实现也已退役。旧插件 API 属于破坏性移除；源码未发行或行为验收。

> Binance/OKX 订单请求映射只归各 provider，SDK 通过 route 注册发现；原 SDK 场所转发模块已移除。旧 CTP 映射测试仍引用退役路径，实际 provider 合同尚待审阅后处理。源码未行为或发行验收。

> 中立持仓方向读取、订单事件的外部/客户端标识读取、数量单位规范化和旧订单字段比较文本规范化归 SDK `broker_event_envelope`；Broker 保留 Position/Order 绑定与投影；方向和文本规范化旧方法已移除，标识读取保留薄委托。源码未行为或发行验收。 SDK `bt_api_py.broker_event_envelope.confirmed_terminal_observation_status` 持有已确认终态观察的中立字段判断，Broker 保留本地前置条件、订单状态及通知；旧私有代理已删除。缺少新版 SDK 时导入失败时点提前，子类覆盖 `_normalize_remote_order_status` 不再影响该判断；跨仓源码和行为未验收。

> 因子执行目标与中立合约快照的覆盖计数归 `bt_api_py.account_execution_snapshot`；Backtrader 仍校验 Strategy/Broker/Feed 绑定并读取本地持仓和订单。覆盖计数不证明行情或账户权威，源码未行为或发行验收。

> 中立订单观察结果及其有限来源字段的合同类型归 `bt_api_base.order_observation_contracts`；SDK 归一化保留原类型导入别名，风险及组合服务直接引用同一类型。数据类型不证明来源真实性；跨仓源码未行为或发行验收。

> Risk 派发证据声明合同归 Base，SDK `risk_dispatch_evidence` 按风险账户 scope 的 provider 精确发现声明；CTP provider 声明既有字段、schema 和校验函数，日志保留 claim、事件链与 writer fence。旧 CTP 字段未改名；其他 provider 尚未声明该路径，源码、插件安装与行为均未验收。

> risk-only direct 订单日志的 SQLite 表、事务、OS 锁、writer fence、事件链及领域校验归 `bt_api_risk.risk_order_journal` 与 `risk_order_journal_storage`；SDK 负责 provider 路由和 Gateway 来源校验组合。Execution 相关分支仍按需加载且职责待拆分；源码未行为或发行验收。

> 原 SDK CTP 路径预算的业务风险评估、额度公式和 CNY 常量归 `bt_api_risk.ctp_budget`；SDK 会话保留预留 seal、持久状态和摘要绑定，选择预算时惰性加载 Risk，缺包明确失败。该源码拆分未行为、发行或账户验收。

> CTP 交易流名称选择及原生 Trader/feed 会话一致性投影由 `bt_api_ctp.trade_stream_readiness` 负责；SDK 保留订阅标记、流注册表、读取时机及审批权威。该检查不创建授权，跨仓源码未行为或发行验收。

> CTP 受管派发请求、绑定、原生回执/发送协议和原命令 ID 计算归 `bt_api_ctp.managed_dispatch_contracts`，报单准备、OrderRef 与绑定核对，以及 SDK 执行 owner 的原生队列回执、请求/撤单目标匹配和回执构造归 `bt_api_ctp.managed_dispatch_worker_binding`；SDK 保留线程、会话及授权生命周期，Execution 单 worker 持有状态并负责 durable claim、UNKNOWN 和完成状态。provider 参与 native 字段与授权绑定一致性检查，MRO、源码信任和行为待审阅后验收。SDK 相关引用已切换，旧 Execution 导入保留同一类型；类型模块名变化和跨仓行为未验收。

> CTP 回调会话适配、原生回调来源桥和回调到账本适配由 `bt_api_ctp.ctp_callback_session`、`ctp_callback_source_bridge`、`ctp_callback_ledger_adapter` 持有；Execution 保留其账本、租约、事件类型及惰性兼容入口，SDK 的 CTP 组合直接引用 provider。类型模块名、可选包安装与行为未验收。CTP provider 的 `query_named_scalar` 提供原生回调命名参数读取；Execution Store 保留请求 ID/终包、来源、序列、摘要、事务及授权检查。首次惰性导入可能发生在事务内；跨包、并发与行为待审阅后验收。CTP 原生撤单目标字段校验归 `bt_api_ctp.cancel_target_projection`；Execution 保留 DTO、OrderRef、来源、session、lease 和授权检查。判断位于自身事务前；上层锁及首次导入并发待审阅后验收。

> CTP callback ingress 快照 schema、摘要和字段读取归 `bt_api_ctp.callback_ingress_projection`；Execution Store 保留原调用入口，注入摘要形状检查及错误类型，并持有 owner、事务和持久状态。CTP 路径需要对应 provider，该 provider 参与来源字段校验；源码绑定、安装及行为待审阅后验收。CTP 原生订单、撤单、报单错误和成交回报字段读取与映射位于 `bt_api_ctp.execution_callback_mapping`；Execution 保留相关类型、关联和延迟委托入口，SDK 的 CTP 回报验证器直接引用 provider 映射。需同时安装相应源码版本；数据映射不证明来源，未行为或发行验收。CTP 原生持仓窗口字段读取及同合约行筛选归 `bt_api_ctp.position_window_projection`；Execution Store 保留来源、事务、lease/fence、授权和持仓数量决策。provider 检查是信任依赖，不证明来源；首次惰性导入可能发生在事务内，导入锁/并发、发行及行为待审阅后验收。

> CTP 原生报单与撤单结构构造归 `bt_api_ctp.native_order_fields`，SDK 执行 owner 保留已声明 payload 的读取、会话绑定、授权与原错误类型。该迁移不验证账户或 native 行为。

> Gateway 账户持仓来源收据与 Risk 持仓事实的跨包核对归 SDK `gateway_risk_position_source`；journal 保留错误类型、摘要算法和 writer fence，Gateway 继续拥有原始收据。此源码迁移未行为或发行验收。

> 风险持仓事实、合约元数据、汇率、Greeks 与持仓覆盖 payload 的解码归 `bt_api_risk.position_payload`；SDK 日志负责自身错误映射及 Gateway 收据、日志和 fence，解码不证明来源。此源码迁移未行为或发行验收。

> risk-only 订单日志的持久状态、事件链、风险证明与账户 writer fence 归 `bt_api_risk.risk_order_journal`、`risk_order_journal_storage` 和 `risk_order_journal_contracts`；SDK `service_risk_order_journal` 的子类组合 provider 证据选择、Gateway 来源验证及 Execution 撤单来源桥，缺失组合时 Risk 默认拒绝相应路径。CTP 原生证据归 provider。Execution 撤单来源类型、数据核对及投影调用由 SDK 跨包桥按需接线，Risk 日志不直接导入 Execution；模块路径、原类型、源码绑定、跨包安装、旧日志、并发与行为均待审阅后验收。

## 1. 如何使用和维护

新增或移动文件前，先确认其运行者、生命周期、依赖方向和是否随发行包交付，再按下文最具体的规则选择位置。修改已有文件前，先检查现有调用者、公开 API、打包、文档和测试；位置不合适不等于可以直接移动。新职责没有合适位置时先说明方案，避免随意增加顶层目录。目录职责变化时同步更新本文和 `AGENTS.md`；行为变化同步更新用户文档和测试。本文不覆盖用户的具体指令，不授予账户操作、数据删除或迁移授权。

判断次序：具体文件和子目录规则优先于上级目录规则；测试夹具、历史证据和生成物按实际用途而非扩展名分类。不能确定归属的文件应标为“待核查”，检查生产导入、调用者、打包和维护者后再定，不应凭名字推断。这里定义所有文件的**归属规则**，并单列关键文件；历史文件不因此自动认定为合规或已逐个核查。

### 共同边界

- `backtrader/` 是发行包：放框架运行所需的接口、实现及明确需要的包数据。生产路径不依赖 `tests/`、`examples/`、`scripts/` 或 `docs/`。`__init__.py` 负责有意公开的导出与必要的包初始化，不承载任务执行或不必要的外部副作用；公开符号变更须考虑兼容性。
- `tests/` 证明合同，`examples/` 展示调用，`scripts/` 提供仓库维护入口，`docs/` 解释和记录；这些目录不能成为框架运行时的隐式依赖。复杂可复用的生产逻辑应归入适当的包模块，脚本和示例负责参数、装配与入口。
- 实验、性能结果和历史证据与受支持产品区分，标注条件、版本、证据等级与入口；模拟测试不能冒充真实账户验收。用户已授权删除相关已冻结历史证据及无用旧 API；受保护输入和已消费调用不得随整理改写或重跑，该授权不涉及账户操作或 retained host 处置。
- 回测、数据、订单、账户和时钟合同需明确；不支持的能力显式拒绝，不能静默降级或伪造成交。模式名本身不授予写权限。SDK 与服务进程由各自项目负责，框架接入以明确接口、边界和生命周期为准。
- 依赖按职责与实际合同设计，并以测试验证；不要将目录名字直接当成已实施的严格分层，尤其是历史模块。私有模块下划线不是公开 API；兼容入口、可选依赖及包导入副作用需单独核查。

## 2. 仓库根目录

| 路径或文件类型 | 应承担的职责和放置规则 |
| --- | --- |
| `README.md` | 用户入口、安装与快速开始、功能边界及主要文档链接；详细设计放 `docs/`。 |
| `AGENTS.md` / `CLAUDE.md` | 面向相应工具的开发指引；本规范是职责规则入口。现有目录摘要应随结构变化同步核对，避免继续复制并产生分叉。 |
| `CONTRIBUTING.md`、`SECURITY.md`、`CHANGELOG.md`、`LICENSE` | 分别记录贡献方式、安全报告、变更历史和许可；各自维护，不混放运行逻辑。 |
| `pyproject.toml`、`setup.py`、`requirements*.txt`、`Makefile` | 构建元数据、安装依赖和开发任务入口；确认实际生效配置，避免多处冲突。 |
| `pytest.ini`、`conftest.py` | 测试发现、标记、跨测试共享配置；特定测试支持优先放就近的 `conftest.py` 或 `tests/`。 |
| `.github/`、质量工具配置、`.gitattributes`、`.gitignore` | CI、格式检查、版本控制与平台规则；精确保护冻结字节及私密输入。 |
| `backtrader/`、`tests/`、`examples/`、`docs/` | 分别为产品代码、验证、用例和文档，详见下文。 |
| `scripts/`、`tools/`、`test_support/` | 仓库任务、辅助工具、跨测试支持；新增前先寻找现有入口，不因名称不同重复实现。 |
| `archive/` | 明确退役的历史材料；默认不参与运行、测试或分发，不作为兼容回退。 |
| `studies/`、`promotion/`、`assets/` | 研究材料、推广材料和项目资源；区分源文件、第三方许可和生成物，不当作运行时依赖。 |
| `reports/`、`artifacts/`、`_bmad-output/` | 报告、交付物和工作流产物；逐项辨别有意跟踪的历史材料与本地产物，新增时注明生成方式及是否需版本化。 |
| `.codex-tmp/`、缓存、虚拟环境、`build/`、日志等 | 本地工作或生成目录；不放唯一权威源码，不默认提交。已跟踪的例外按其明确用途和冻结要求处理。 |
| `.env.example`、示例配置 | 不含凭据的模板。真实 `.env`、账户配置和私密捕获不属于源码审查材料，遵守 `AGENTS.md` 的受保护读取规则。 |

根目录新增文件应是项目级入口或配置；临时补丁、一次性测试输出和个人环境文件应另行分类，不因当前存在就获得长期职责。

## 3. `backtrader/` 产品包

本项目保留现有平铺包布局。以下是职责边界，不要求为迎合模板立即重排公开模块。

| 目录或文件 | 职责 |
| --- | --- |
| `__init__.py`、`version.py`、`errors.py` | 明确的包入口与导出、版本、共享异常合同；避免入口强制加载不需要的可选依赖。 |
| `cerebro.py`、`_cerebro/` | `Cerebro` 公共装配入口与引擎执行、生命周期、通知、注册和运行循环的内部实现；保持普通引擎生命周期为唯一调度权威。 |
| `metabase.py`、`parameters.py` | 对象构造、参数与 owner 机制；保留当前显式构造合同。 |
| `lineroot.py`、`linebuffer.py`、`lineseries.py`、`lineiterator.py`、`dataseries.py` | 线数据接口、存储、组合、迭代及时钟依赖；改动要覆盖多数据、最小周期和两种引擎运行方式。 |
| `feed.py`、`resamplerfilter.py`、`feeds/`、`filters/` | 数据源抽象、具体 Feed、数据过滤和时间聚合；提供数据与时间语义，不负责策略或真实下单决策。 |
| SDK 账户配置方法发现 | `bt_api_py.account_config_composition` 按 route 发现 provider 声明的原生读取别名；OKX/Binance 声明 `get_config`，其他 route 默认只用标准方法。跨仓源码未行为或发行验收。 |
| `bt_api_py.market_stream_contracts` / `stores/btapistore.py` | SDK 规范化中立频道与盘口深度配置；Store 负责订阅时机、路由和生命周期。跨仓源码未提交、未行为验收。 |
| `bt_api_py.market_tick_contracts` / `feeds/btapifeed.py` | SDK 统一中立行情数值规范化，选择事件时间字段并转换为时间戳或 UTC；BT Feed 负责日志、数据线和 bar 处理。既有数值阈值和时间 fallback 不构成来源证明，跨仓源码未行为验收。 |
| `bt_api_py.market_cohort`、`feeds/market_factor_source.py` | SDK `market_cohort` 独立实现 neutral event cohort 校验，BT 调用方直接使用 SDK 类型；旧 `feeds/market_cohort.py` 门面已移除。`market_factor_source.py` 仍投影 SDK session-resolver 合同。二者不解析 CTP 原生字段或创建时钟证明；CTP 真实 source-clock 当前未就绪，本轮 source move 未行为验收。 |
| 015 示例及迭代 27 历史来源摘要 | 历史摘要仍将已移除的 `feeds/market_cohort.py` 列为必需输入；015 工件检查和迭代 27 验收脚本因该输入缺失而不可继续。需审阅新的跨仓 SDK 来源绑定，不能只删摘要项来延用旧证据。 |
| `bt_api_py.market_tick_contracts` / `feeds/market_tick_adapter.py` | SDK 校验中立行情既有的时钟与 freshness，处理通用 tick schema、质量标记、成交量、报价与事件/接收时间字段，并分类既有执行资格；不签发新证明。BT adapter 保留字段/时间映射，Feed 提供 legacy schema、replay 绑定状态、年龄配置和时钟回调，保留价格网格、K 线水位及框架时钟决策。tick 预处理现在包括 legacy 路径均依赖新 SDK 接口；跨仓源码未提交，缺失 SDK、行为与发行兼容性未验收。 |
| `bt_api_base.reconciliation_protocol` / `bt_api_py.reconciliation` / `brokers/btapibroker.py` | base 统一校验中立订单状态与终态标记，SDK 对外公开并将中立费用字段校验为 `CommissionAmount`；二者不证明事实来源。BT Broker 保留本地订单关联、状态投影、通知与费用分配。该接口和调用为未提交 WIP，未行为验收。 |
| `bt_api_py.query_composition.select_query_facade` / `stores/btapistore.py` | SDK 负责中立 query selector 检查、调用及返回类型核对；Store 保留 API 实例、route/currentness 与错误类型映射。该路径为跨仓未提交 WIP，未做导入及行为验收。 |
| `bt_api_py.route_identity_projection`、`bt_api_py.reconciliation` / `BtApiStore` | SDK 检查对账 route 集合、选择精确 route 并检查调用方设定的超时上限；Store 保留活跃 API 对象和生命周期绑定。route 名称不代表账户权限；跨仓源码未提交、未行为或发行验收。 |
| `bt_api_py.reconciliation.ReconciliationClient` / `service/sdk_reconciliation_adapter.py` | SDK 负责选择中立对账 facade、准备和检查 opaque handle、发起快照及委托 lease 校验；BT adapter 只做框架错误转译，Store 保留本地 route、订单绑定与命令线程。该接线为未提交 WIP，未行为验收。 |
| SDK 中立风险/对账检查 / `brokers/btapibroker.py` | SDK 生成既有风险视图的不完整标记，并在调用方干净执行检查通过后按传入容差检查中立持仓归零；Broker 决定触发时机、容差及本地订单/持仓状态。该检查不创建账户或对账事实；跨仓源码未提交、未行为验收。 |
| `bt_api_py.reconciliation_projection_inputs.has_clean_execution_projection` / `brokers/btapibroker.py` | SDK 检查旧中立对账投影中的场所覆盖、代际、时间与未决项形态；BT 保留停机时的本地平仓/持仓判断。字段一致性不证明对账来源或账户事实；跨仓源码未提交、未行为验收。 |
| `bt_api_py.reconciliation_projection_inputs` / `execution/reconciliation_projection.py` | SDK 校验中立对账输入、订单身份、成交与父单关联及成交金额和持仓字段；BT 执行投影负责本地引用、Feed 绑定、Store 代际、Broker 信封和消费前一次性验证，Store 委托调用并持有绑定状态。跨仓源码及 facade 依赖仍为未提交 WIP，未行为验收。 |
| `bt_api_py.bounded_metadata_probe` / `service/bounded_metadata_probe.py` | Store 直接持有 SDK 探测服务，SDK 负责线程、时限、合同校验、中立 session 结果及只读 summary 字段谓词；BT 桥负责 Store 调用、回调、错误和结果映射。旧 SDK 缺少该谓词时明确报依赖错误。此工作流不授予交易权限；跨仓源码未行为验收。 |
| `bt_api_ctp.query_result_evidence` / `bt_api_py.BtApi` | provider 校验 CTP 查询终包、请求代际、账户指纹并投影原生行；SDK 保留查询前后的会话授权栅栏、请求与有限错误转换。该分离不证明真实查询、账户或授权；provider 依赖和行为待审阅后验收。 |
| `bt_api_ctp.query_result_evidence` / SDK 查询接线 | provider 选择原生查询方法和公开会话字段；SDK 保留 route、transport 检查和查询调用。结算确认读回的就绪作用不因迁移改变；源码未行为验收。 |
| `bt_api_ctp.query_result_evidence` / `bt_api_py.BtApi` | CTP provider 选择恢复查询行的原生账户、交易日字段和活动订单状态；SDK 保留查询、会话栅栏与中立投影。既有状态语义及跨包行为未验收。 |
| `bt_api_ctp.recovery_plan_validation` / `bt_api_py.BtApi` | provider 比较 CTP 恢复审批动作和剩余平仓/撤单额度；SDK 保留审批、授权、会话状态和调用时机。字段匹配不授予权限，源码迁移未行为或发行验收。 |
| `bt_api_py._ctp_ingress` | SDK 入口队列视图、封印和私有事件同步组件；实例级生命周期与授权时机由 `BtApi` 持有，CTP 原生协议仍归 provider。源码未行为验收。 |
| `bt_api_ctp.credential_binding_fronts` / `bt_api_py.BtApi` | provider 检查 CTP 原生交易客户端、认证行情身份和前置连接的一致性；SDK 惰性委托并提供自身 Feed、订阅流、ingress 队列及错误类型，保留状态和授权所有权。跨仓源码未提交，异常、并发、发行与账户行为均未验收。 |
| `bt_api_py.ctp_probe` / `bt_api_ctp.simnow_probe` | CTP provider 持有隔离子进程、原生客户端和输出脱敏；SDK 仅在调用时加载并委托。示例及离线测试引用已切换，旧私有路径退役；跨仓源码未提交，子进程、安装和账户行为均未验收。 |
| `bt_api_base.execution_configuration_policy` / SDK execution configuration / provider | Base 定义字段声明合同；Binance/OKX 负责各自凭据别名及环境要求，OKX 另声明环境区域规则；其他 11 个 provider 暂显式选择旧无专项策略。SDK 按精确 route 加载、校验并保留散列和会话绑定；缺少声明时拒绝执行配置。该工作区跨包入口尚未提交或行为/发行验收，不证明账户身份、凭据有效性或权限。 |
| SDK result collection / provider normalization policy | Base 声明中立 `data` 容器；Binance/MEXC 显式声明原生 `symbols`，CTP/OKX 选择 `data`，其余九家显式保留旧 `symbols` 候选待核实。SDK 按所选 route 的声明展开结果，保留源行关联；字段声明缺失时不推断账户事实。CTP/OKX 字段收窄、其他场所覆盖、跨包安装及行为均未验收。 |
| SDK response error / provider normalization policy | SDK 选择响应子码字段并执行中立错误分类；13 个 provider 显式声明字段，OKX 声明原生 `sCode`，其余 12 家保留旧字段待核实，base 不默认选择。策略不可用且响应表面成功时，读操作报错、写入保持 UNKNOWN。跨包源码未提交、未行为或发行验收，其他场所字段归属仍待收敛。 |
| `bt_api_py.order_fee_projection` / provider normalization policy | SDK 按中立成交字段核对终态订单并汇总费用；base 默认不启用，Binance provider 显式声明旧路径。policy 不可用时不补全；跨包未提交、未行为或发行验收，不证明费用完整。 |
| `bt_api_binance.funding_schedule` / `bt_api_py` funding facade | Binance provider 选择原生资金费率行、结合 fundingInfo 或历史结算补全周期；SDK 按 route 选择 policy，提供中立快照和错误投影。缺失周期不假设默认值；跨仓源码未提交、未行为或发行验收。 |
| `bt_api_py.broker_event_envelope` / `brokers/btapibroker.py` | SDK 投影已验证中立提交回执的状态和错误码；Broker 标记 BT 订单。旧无调用的原始响应拆包已移除，字段标记不建立来源证明；源码未行为验收。 |
| `bt_api_py.service_recovery_quote` / Broker 恢复桥 | SDK 保留中立行情 revision 合同和消费流游标；Broker 仍要求 Feed 提供报价与当前 bar 的绑定并验证。`BtApiFeed` 不再提供内置绑定或相关配置，依赖该绑定的恢复路径不可用；自定义 Feed 合同不证明来源可信。源码未行为验收。 |
| `bt_api_py.service_market_bindings` / `service/service_read_proxy.py` | SDK 拥有中立 bar 和订单簿绑定类型；BT 保留其到框架 Feed 的映射。可选 `bt_api_runtime` 的旧服务代理导入已更新；源码未行为或发行验收。 |
| `bt_api_py.service_market_bindings.validate_service_market_bindings` | SDK 校验服务账户覆盖、市场客户端实例去重与中立绑定类型；BT 保留 Feed 名称到持仓的框架映射和生命周期。检查不证明账户权威，跨仓源码未行为或发行验收。 |
| `bt_api_py.service_market_history` / `service/service_read_proxy.py` | SDK 持有每个 bar 消费流的历史/实时衔接、去重和顺序状态；BT 保留 bar 投影和 Feed 绑定。跨仓源码未提交，未行为验收。 |
| `bt_api_py.funding_refresh` / `stores/btapistore.py` | SDK 持有中立 funding 缓存、刷新线程、超时与 generation；Store 直接绑定路由、生命周期回调和既有结果标签，旧 BT 兼容层已移除。源码未行为验收。 |
| `bt_api_py.account_balance_read`、`bt_api_py.account_position_read` / `stores/btapistore.py` | SDK 拥有各 route 余额缓存/持仓读取、port 选择、快照与 lease/currentness 校验；Store 构造时直接惰性创建 SDK 工作流并注入框架错误类型，BT 保留 API/route 生命周期、Feed 绑定和 Position 投影。仅转发构造的两个 BT 模块已移除。跨仓源码未提交、未行为验收，不证明账户状态。 |
| `stores/btapistore.py` 旧读取残余 | 无调用的旧缓存时效工具、无读取的逐交易所缓存计时和旧单客户端持仓模式回退已移除；服务/SDK 入口保留。源码未行为验收。 |
| `stores/btapistore.py` 统一读取 | 合约规格、资金费率、手续费、账户配置、交易就绪和逐交易所余额只从统一 SDK facade 读取；只读服务可读取已配置合约元数据，未提供其余能力时明确不可用。旧单客户端回退已移除；源码未行为验收。 |
| `stores/btapistore.py` 持仓与开放订单 | direct 通过 SDK 已验证的持仓/对账快照读取，只读服务使用其明确 facade；旧非 SDK 直接客户端读取和缓存回退已移除。历史 `positions_cache_ttl`/`open_orders_cache_ttl` 参数仍接受但不生效；调用未初始化 SDK 或只读 facade 明确失败。源码未行为验收。 |
| `bt_api_py.account_balance_read` / `stores/_account_balance_projection.py` | SDK 校验配置与实时 route 一致性、余额批次完整性及中立余额/估值快照形态；BT 投影模块统一单币种约束、cash/value 和场所结果映射，Store 提供自身 route 和调用时机。跨仓 WIP，未行为验收。 |
| `bt_api_py.broker_event_envelope` / `brokers/btapibroker.py` | SDK 持有中立品种键字段检查和既有比较键投影；Broker 负责配置 Feed、订单及持仓绑定。比较键不是品种、账户或授权事实；跨仓未提交、未行为或发行验收。 |
| `bt_api_py.account_position_read` / `stores/_account_position_projection.py` | SDK 检查持仓批次、空结果证明及中立行类型；BT 投影模块持有 Feed/合约匹配、数量单位绑定与 Position 数值投影，Store 只注入自身状态与错误类型。跨仓 WIP，仅源码对照，未行为验收。 |
| `bt_api_py.execution_identity_assurance_composition` / `bt_api_py.execution_identity_fence` | SDK 捕获并校验身份向量，持有宿主代际的栅栏状态；Store 提供当前配置、generation 和 API 回调。配置期望或 DTO 不是 provider/account/session 事实或授权；跨仓源码未提交、未行为验收。 |
| `BtApiStore` 旧 forwarding 分支 | 初始化保留对旧 gateway/forwarding 配置的明确拒绝；连接流程中不可达的旧客户端入口和 route 策略中的旧 forwarding 分支已移除。此源码改动未做行为或导入验收，不影响可选 SDK gateway 的独立职责。 |
| `bt_api_py.route_identity_projection` / `execution/store_route_policy.py` | SDK 读取并比较路由集合、选择精确 route；BT 持有 Store 实例、配置、生命周期和代际检查，注入自己的错误类型与消息。名称比较不证明账户或交易权限；跨仓源码未提交、未行为或发行验收。 |
| `bt_api_py.account_request_labels` / `BtApiStore` | SDK 校验 route 的显式账户请求标签及可选传入标签的一致性；Store 提供配置并映射框架错误。标签不证明账户身份或授权；两仓源码未提交、未行为或发行验收。 |
| `bt_api_py.account_risk_projection`、`bt_api_py.account_risk_state` / `execution/account_risk_state.py` | SDK 持有身份绑定读取、中立快照校验、单实例缓存和刷新预约；BT 桥保留 Store 代际、身份和生命周期回调。Store 构造时惰性加载 SDK 状态，不复制缓存或锁；该状态不是可选业务风控策略，也不证明账户事实。跨仓源码未提交、未行为或发行验收。 |
| `bt_api_py.command_outcome`、`bt_api_py.command_coordinator` / `execution/sdk_execution.py` | SDK 分类结果并协调命令执行、丢弃、UNKNOWN 锁存及计数；BT 注入订单引用、回执投影和 Store 生命周期回调。每个 coordinator 持有唯一安全状态，不创建 provider 授权；直接路径无需可选 execution 或 risk。本轮跨仓源码未提交，异常、锁顺序及行为未验收。 |
| `bt_api_py.service_contracts` / service 示例 | 服务执行示例及 014_2 旧服务入口的账户、行情与服务合同类型改从 SDK 统一导入，保留 base 类型身份；014_2 源码中的旧开发环境探测与历史认证目录另行核对。跨仓 WIP，未行为或发行验收。 |
| `bt_api_py.query_preflight` / 052 示例 | SDK 持有中立只读查询批次、租约与会话一致性检查；示例提供请求命名、用途和有限错误类型映射。结果不建立授权或独立账户事实；跨仓源码未提交，未进行查询、行为或发行验收。 |
| `bt_api_py.multi_route_read.query_orders_sync` / 052 示例 | SDK 组合显式 route 的只读订单查询并提供同步事件循环桥；示例保留参数解析和结果摘要。各 route 的结果不合并成账户快照；跨仓源码未提交，未进行查询或行为验收。 |
| `setup.py` 可选依赖 | `live` 与 `execution` extras 声明统一 `bt_api_py`，execution 另声明 execution 子包；SDK 当前要求 Python 3.11 起。工作区 SDK 接口尚未全部提交，最低版本并不证明现有发行包含有重构接口，隔离安装和最终版本范围未验收。 |
| `bt_api_py.service_recovery.project_service_owner_book_payload` / `service/service_execution_adapter.py` | execution 持有恢复账本中立投影，SDK 惰性暴露统一入口，BT 只提供其错误类型和框架绑定；BT 不再直接导入该子包。跨仓 WIP，未行为或发行验收。 |
| `bt_api_py.service_execution` / `service/service_execution_adapter.py` | SDK 统一执行服务的引用、品种格式及恢复 owner 记录外层合同校验；BT 惰性调用并校验自身数据名、交易和通知投影。跨仓 WIP，未行为验收。 |
| `bt_api_py.managed_execution` / `bt_api_py.execution` / `bt_api_py.correlated_execution` / `bt_api_py.direct_correlated_execution` | SDK 中立 claim/授权委托从可选 journal facade 分出，旧 SDK `execution` 路径重导出相同类型；direct 由 SDK 按 base 直连订单 port 选择 provider，并与显式 managed 路径相互隔离。CTP 直连 provider、会话与订单回报链尚未闭合，不能推断 direct 可用；这些源码均为未提交 WIP，未做导入或行为验收。 |
| `feeds/replay_market_adapter.py` | `BtApiFeed` 只通过独立 `replay_market_tick_port` 接受 local replay，要求 `store=None`，并使用专属生命周期与原子 EVENT/EOF/final event-time watermark 合同；不会调用通用 Store start/register/subscribe/history。回放 tick/bar identity 不映射成 live generation/ingest cursor、receive clock/freshness 或下单资格。当前源码未行为验收。 |
| `strategies/ctp_future.py` / `BtApiBroker` / `bt_api_py.futures_contract_lookup` | 策略经 Broker 和 Store 委托 SDK 查询主力与次主力；SDK 组合参考快照、日历和选择算法，BT `futures/` 保留框架日历、分钟网格、bundle 和换月投影。默认实时查询因新鲜度不可证明而不可用，显式参考模式不证明实时性；旧六个 `feeds/futures_*` 文件已退役，跨仓源码未做导入、发行或行为验收。 |
| `bt_api_py.futures_snapshot_workflow` / `bt_api_py.futures_eod_projection` | SDK 持有中立快照采集工作流及 EOD 绑定、lease 检查和摘要；原生规则和日报解析归所选 provider。2026 日盘规则 review 为 HOLD，报告最新/定稿性及目录覆盖不完整；选择结果不证明当前行情或交易授权。 |
| `broker.py`、`brokers/`、`order.py`、`position.py`、`trade.py`、`comminfo.py`、`commissions/`、`fillers.py` | Broker 合同与实现、订单/持仓/交易、费用及成交规则；实际服务能力和授权不应由名称或模拟结果推断。 |
| `commissions/option_premium.py` | `OptionPremiumCommInfo` 是中立单腿 premium 会计，只接收经 SDK `ExecutionRulesSnapshotPort` 验证的规则快照，不维护账户账本。CTP snapshot issuer/费用币种证明未注册，CTP fees 与卖方 pre-fee margin 保持 unavailable。 |
| store.py、stores/ | Store 是非单例的实例级公共基类，每个实例独立持有生命周期、feed/broker 绑定和通知队列；LiveStoreBase(Store) 定义 live Store 必需接口，缺实现时显式抛 NotImplementedError。VChartFile 直接继承 Store；BtApiStore 经 LiveStoreBase 继承 Store，构造时先调用 Store.__init__，再初始化自身 API 状态、工厂和生命周期。backtrader.store.SingletonMixin 仅保留为通用 mixin 的旧导入别名，不参与任何 Store 的 MRO。普通 direct SDK client 的配置、懒工厂、执行配置移交和 client close 由 bt_api_py.direct_api_assembly.DirectApiAssembly 持有；Store→Cerebro 的 event waiter 和 SDK wake-callback 绑定状态由 backtrader.service.store_event_notifier.StoreEventNotifier 单独持有，Store 保留原引擎接口的薄委托。该结构改动尚未行为验收，见第 6 节。 |
| `stores/_live_bar_queue.py` | 唯一持有 Backtrader completed-bar FIFO、容量、溢出计数与 sticky stale 状态；Store 只委托入队/出队/健康投影，Feed 通过 `has_pending_live_bar()` 查询。未知 symbol 的 `snapshot()`/`pop()` 会创建空队列，作为后续验收项保留；未做行为验收。 |
| `bt_api_py.market_history_composition` / `stores/_bar_history_cache.py` | SDK 持有历史行情 facade、路由、分页及中立 bar 批次合同；BT Store 直接惰性调用 SDK 或只读服务，`stores/_bar_history_cache.py` 持有 BT 周期转换、bar 投影及本地缓存。旧 `feeds/sdk_history_adapter.py` 已移除；源码未行为验收。 |
| `bt_api_py.market_stream_session` / `bt_api_py.market_stream_contracts` | SDK 单实例 session 持有中立订阅 token、句柄映射、深度及丢弃计数，并负责订阅、轮询、恢复和退订；失败时保留待关闭句柄。Store 注入自身 route/currentness 和生命周期、健康投影回调，provider 持有 session 与 channel queues。旧 BT 私有模块已移除；此跨仓源码未提交，锁、生命周期、安装和行为未验收。 |
| `bt_api_py.market_stream_contracts.market_stream_consumer_contracts` | SDK 统一惰性组装中立身份、订阅及事件类型，SDK session 持有订阅句柄映射并调用注入的框架错误类型。跨仓 WIP，未行为验收。 |
| `bt_api_py.market_stream_contracts` 行情流操作 | SDK 合同层封装端口选择、订阅、令牌绑定、身份/队列检查、轮询、恢复与退订；SDK session 单实例保留 token 与该订阅的计数，BT 处理路由生命周期与交付异常投影。绑定一致不证明 provider 权威；跨仓 WIP，未行为验收。 |
| `bt_api_py.market_stream_contracts.polled_market_event_header` / `service/store_event_dispatch.py` | SDK 校验轮询事件的中立映射与 kind，BT service 桥将事件分发到 Broker/Feed/通知；Store 保留单一消费锁和实例状态。未验证订单事件的本地绑定及 UNKNOWN 投影归 BT `execution/unverified_order_projection.py`。跨仓 WIP，未行为验收。 |
| `service/store_lifecycle.py` / `stores/btapistore.py` | BT 生命周期桥协调 Store 的 Feed/Broker 挂接、启动/重启栅栏、API 就绪和关闭；Store 持有实例状态，SDK 的 direct 装配、队列、行情订阅、funding 与有界关闭仍各自持有对应资源。桥不创建第二份生命周期状态；迁移后的锁、异常和并发未行为验收。 |
| `stores/_market_delivery_state.py` / `bt_api_py.market_delivery_projection` | SDK 投影中立事件字段和连续性；BT 唯一持有 delivery/drop 去重、本地 sequence 与 stream-health 状态，并在该 owner 内投影 SDK 队列观察；旧 `_market_stream_projection.py` 已合并移除。Store 持有 event drain 锁、生命周期及 stream generation；跨仓源码未行为验收。 |
| `execution/store_order_projection.py` | 无状态投影 Backtrader order request 与 normalized Broker update 的 Store runtime-event payload；不持有 Store、通知队列或账户状态。Store 保留 runtime-event 发布、脱敏及通知队列生命周期；未做行为验收。 |
| `bt_api_py.broker_event_envelope` / `brokers/btapibroker.py` | SDK 持有旧通用消息信封展平、中立 DTO/映射字段读取、数值及方向/状态解析，以及对账订单、成交费用和持仓字段的中立形态检查；BT 保留本地订单引用、Feed/合约与单位绑定、持仓比较、状态映射和通知。既有 SDK `b76b84f6` 为源码提交，新增检查与 BT 接线为跨仓未提交 WIP；原生字段解释属于 provider，行为与来源未验收。 |
| `bt_api_py.startup_recovery.normalise_startup_account_state` / `brokers/btapibroker.py` | SDK 投影中立启动账户计数，保留缺失/未知/错误状态；Broker 持有本地启动与停机决策和日志回调。该摘要不是最终账户状态或账户权威；初始化时新增 SDK 模块依赖，跨仓源码未提交、未行为验收。 |
| `bt_api_py.startup_recovery` / `stores/btapistore.py` | SDK 的 `recover_local_startup_journal` 统一运行和校验可用的本地 journal 恢复 hook；缺少 hook 只表示 unsupported，不证明订单已清理。Store 负责选定 API 的启动顺序、触发条件和失败转译。此跨仓接线为源码 WIP，未做行为或账户验收。 |
| `bt_api_py.approval_lease` / `stores/btapistore.py` | SDK 校验显式传入的审批期限、操作次数及风险减少标记；该检查不签发授权或证明来源。Store 只映射 BT command 字段并转译拒绝，Broker 的本地计数与上游权威仍须单独核对。此跨仓接线为源码 WIP，未做行为或账户验收。 |
| `bt_api_py.order_readiness_composition` / `stores/btapistore.py` | SDK mode 的 readiness facade 调用、结果投影与 `definite_failure` 布尔检查由 SDK 持有；Store 保留 Feed/route、显式账户配置与 BT 映射。此跨仓源码未提交、未行为验收，不证明交易授权。 |
| `stores/btapistore.py` funding 查询 | SDK mode 调用统一 `get_funding_snapshot`；SDK 缺少此合同则拒绝，不在 BT 尝试 SDK 的旧方法。非 SDK 路径与 BT funding 缓存生命周期仍按各自合同核对；此源码变更未行为验收。 |
| `bt_api_py.execution_capacity` / `stores/btapistore.py` | SDK `read_order_capacity_facts` 选择并校验 route-bound facade 和 snapshot；Store 保留 SDK 模式、连接、写路由身份及 route 选择。此跨仓接线与 SDK 文件为未提交 WIP，未做行为或账户验收。 |
| `bt_api_py.order_preflight` / `execution/order_preflight.py` | SDK 协调中立规则请求、session generation 检查及 rules/economics 决策绑定；BT 仅提供 Store 弱引用上下文、订单投影、route 与 instrument 配置。SDK 持有传入的 host order 身份但不解析框架类型；源码未行为验收。 |
| `bt_api_py.execution_rule_preparation.evaluate_rules_with_position_evidence` / `bt_api_py.order_preflight` | SDK 构造中立规则及经济性请求、串接持仓证据与决策，并核对规则快照、持仓证据及有效期；BT 提供 Store session-generation fence 和框架对象投影。跨仓源码未提交，未做行为和发行验收。 |
| `execution/sdk_correlated_order_adapter.py`、`execution/order_request_projection.py` | BT 执行适配器负责框架订单关联准备、订单请求的框架配置和合约信息投影、exact correlation 到 BT registry binding 校验及 execution-contract 附着，并委托 SDK 加载中立类型、构造请求及完成一次性 dispatch/ACK handoff；`order_request_projection.py` 只生成 Store 本地 execution-contract。Store 保留 route/account/strategy 配置、instrument metadata、绑定注册表、command worker 与生命周期。Provider authority 与 native schema 归 SDK/provider；源码未行为验收。 |
| `strategy.py`、`indicator.py`、`observer.py`、`analyzer.py`、`sizer.py`、`signal.py` | 策略和相应组件的公共基类、接口和生命周期。 |
| `indicators/`、`observers/`、`analyzers/`、`sizers/`、`signals/` | 各自类型的可复用实现；信号、分析与观察不应暗中更改账户。 |
| `research/` | 因子研究、面板与研究协议；计算仍服从引擎生命周期，下游分析通过既定外部接口接入，不复制其他项目的权威算法。 |
| `strategies/factor_strategy.py` | 因子研究的 Backtrader 策略装配和同步网格采集；研究协议、因子、面板与 sink 仍归 `research/`，Cerebro 保持唯一调度。迭代 61 迁移和驱动修复已按用户确认的本地证据范围完成；旧 `research.FactorStrategy` 和 `research.factor_strategy` 路径按用户决定退役。 |
| `plot/`、`bokeh/`、包内 `reports/` | 绘图后端和报告展示；可选展示依赖不应无故成为核心导入前提。 |
| `channels/`、`channel.py`、`notifications/`、`events.py`、`timer.py` | 按现有公开合同处理通道、事件、通知与定时，不自行引入第二套引擎。 |
| `live_trading/`、`configs/`、`profiles.py` | 现有实盘配置及辅助能力、无凭据配置模板和配置投影；逐项确认支持状态，不存真实凭据。 |
| `btrun/` | 包内受支持命令/运行装配入口；命令只协调受支持能力，不把业务实现锁进 CLI。 |
| `mixins/`、`utils/`、`functions.py`、`mathsupport.py`、`flt.py`、`talib.py`、`tradingcal.py`、`writer.py` | 共享机制、数学/日期/外部库适配、交易日历和输出；优先放领域模块，仅在确有跨领域复用时放通用工具。 |
| `test_helpers.py` | 现有包内测试辅助兼容入口；新测试辅助优先放 `tests/`，移动此文件前先审查现有使用者和发行兼容。 |
| `execution/`、`factor_execution/`、`service/` | 迭代 53 工作区中的 BT 候选位置：通用执行调用端、BT 因子/策略事实、框架生命周期桥接；`service/` 只保留 Cerebro/Strategy/Broker 薄桥及其 event wake 协调器，不承载 SDK/provider 权威或 transport。当前仍在迁移，未完成结构或行为验收。 |
| `bt_api_py.service_read_lifecycle` / `service/service_read_proxy.py` | SDK 持有只读 facade owner-thread、连接和逐个关闭状态；`bt_api_py.service_market_bindings` 工作区持有中立 bar/盘口客户端、账户资源和历史范围绑定校验，账户客户端接口、覆盖范围、估值及持仓/挂单中立完整性与单位校验归 `service_account_observation`，历史分页边界、UTC 解析、bar 客户端启动与健康轮询，以及每个 bar 流的 epoch/序号、bootstrap/事件 wire、订阅键和时间区间校验归 SDK history。盘口启动回执、投影来源与健康检查归 SDK orderbook；BT 保留绑定对象、关闭目标及 Feed/Broker 投影。跨仓接线为 WIP，未做行为验收。 |
| BT service 引用及 Broker 待修缺陷 | 只读桥按旧源码恢复 `_optional_float`，session 使用 TYPE_CHECKING 声明 SDK 路由类型；Broker 的 order-reconciliation 完成方法存在未定义 `command` 及 submit/cancel/query 处理片段错位，需审阅后修复，不视为订单能力可用。源码未行为验收。 |
| `bt_api_py.managed_order_refresh` / `service/service_refresh_loop.py` | SDK 持有无独立线程的刷新节奏、退避、统计和异常类型；BT 负责 Broker 回调和部分完成事实投影，旧 BT 统计/异常重导出已退役。SDK 已做源码提交，BT 接线仍为未提交 WIP，行为未验收。 |
| `bt_api_py.service_route_selection` / `service/service_execution_session.py` | SDK 解析已注册账户簿 route、操作和 scope，检查唯一性；BT 根据解析结果绑定 Strategy 视图及生命周期。配置和绑定不证明账户或 provider 已就绪；跨仓未提交、未行为验收。 route 类型直接从 `bt_api_py.service_route_selection` 导入，旧 BT 重导出已移除。 |
| `bt_api_py.account_book_contracts` / `service/service_strategy_account_book.py` | SDK 持有中立账户簿快照、财务 DTO 和操作常量；BT 保留策略绑定与 Position/现金投影，不再重导出中立类型。旧 BT 导入路径属于破坏性变更，源码未提交或行为验收。 |
| `bt_api_py.queued_command_runtime` / `execution/sdk_command_runtime.py` | SDK 规范化命令队列容量、预留量和关闭超时，并持有唯一命令 worker、有界队列、代际和完成 inbox；BT 惰性构造并注入订单回执、丢弃和健康投影。资金费率最大缓存年龄与刷新间隔的配置规范化归 `bt_api_py.funding_refresh`。跨仓源码 WIP，锁顺序和并发行为尚未验收。 |
| `bt_api_py.correlated_command_dispatch` / `execution/sdk_correlated_order_adapter.py` | SDK 持有中立订单/撤单请求构造、route facade 选择、correlation 签发、请求与关联字段的一致性检查、claim、单次派发和 ACK 校验；BT adapter 持有 Store 订单绑定、派发前 currentness 和 Broker 回报投影。请求字段一致不构成授权；工作区跨仓源码尚未导入或行为验收。 |
| `bt_api_base.execution_identity_projection` / provider normalization policy | base 按策略声明识别订单原始记录中显式提供的中立身份字段，SDK 保留统一 route 装配；识别字段不证明来源或授权。所有 route 当前仍沿用旧字段集合，provider 原生字段的逐项归属及行为验收未完成；跨仓源码未提交。 |
| provider normalization policy / SDK 结果信封 | SDK 按所选 route 的策略读取品种和资产类型字段；13 个现有 provider 均声明品种字段，后十家其余字段仍继承 base 旧策略。字段过滤会改变部分输入的输出；策略与 DTO 不证明账户、品种来源或授权。跨仓源码未提交、未行为及发行验收。 |
| `bt_api_base.account_permission_projection` / provider normalization policy | base 提供中立权限投影与合并；Binance/OKX/CTP 各自声明字段，SDK 用选定 route 调用并绑定 readiness 的投影器。其他 provider 沿用旧字段；字段过滤可能改变权限判断，不证明授权或账户事实，跨仓源码未提交、未行为验收。 |
| `bt_api_py.factor_order_correlation` / `factor_execution/factor_execution_facts.py` | SDK 按中立客户端订单 ID 查重并关联 provider 订单和调用方提供的本地行，检测品种冲突；BT 构造自身关联结果并保留 Strategy、Broker、Order 和 Feed 读取。该关联不证明 provider 事实或授权；跨仓源码未提交、未行为验收。 |
| `bt_api_py.managed_execution_client` / `factor_execution/factor_execution.py` | SDK 持有中立查询、快照租约、claim、单次 submit/cancel 和 UNKNOWN resolution 的调用及合同检查；provider/底层 facade 仍持有权威。BT 保留 Strategy/Broker、决策作用域及本地订单/持仓投影，注入框架错误类型。跨仓源码未提交，缺少新 SDK 模块时的错误投影、依赖及运行行为待审阅后验收。 |
| `bt_api_py.account_execution_snapshot.require_account_execution_snapshot_scope` / BT factor facts | SDK 检查账户快照类型、回执/租约/session 身份和中立行容器；BT 保留策略和 Broker 本地事实关联。该检查不验证 lease 当前性或账户来源；跨仓源码未提交、未行为验收。 |
| `bt_api_execution.factor_position_attribution` / `bt_api_py.factor_position_attribution` / `execution/_journal_ports.py` | execution 持有本地归属账本 schema、journal 内版本/预检/建表/校验、事务、幂等、容量记账和容量行读取，SDK 公开统一入口，BT 不再重导出中立 fill/结果类型及 schema、grid、checkpoint 函数；缺失 provider 持仓、成交及证据的拒绝和中立平仓证据输入和 provider 成交对账不可用的拒绝归 execution，中立查询回执判断归 SDK；Execution 持有调用方持仓数量比较及结果类型，BT 保留框架接线及错误转换。沿用原表名、版本和本地成交标识，本地账本不证明 provider 事实；BT journal port 经 SDK facade 继承 execution 的 grid、flat checkpoint 和本地 close-owner 操作，调用方经 BT 端口提供待比较数量；其他 port 函数仍须逐项核对。跨仓改动未提交、未行为验收。 |
| `bt_api_execution.factor_position_journal_port` / SDK facade / BT journal port | execution 实现中立持仓归属 journal 端口的 schema、容量及持久操作；SDK facade 转译容量异常，BT 子类仅提供 Broker 关联的本地持仓投影和框架错误类型。三仓源码为未提交 WIP，继承、事务、导入及行为尚未验收。 |
| `bt_api_execution.factor_position_attribution.read_factor_position_snapshot_inputs` / BT factor position book | execution 准备本地 schema、检查中立快照输入并读取本地归属事实，SDK 公开入口；BT 比较 Broker 数量并构造框架快照。这些事实不证明 provider 持仓，跨仓源码未提交且未行为验收。 |

迭代 53 的目标集成边界：BT Store/Broker/Feed 经 `bt_api_py` 公开 facade 调用 SDK，以 `bt_api_base` 中立合同/DTO 交换数据；所选 provider package 独占其 native/session/field/request/query/callback 真值，BT 只将中立 DTO 映射为 Order/Position/Feed/Broker。BT `execution/` 保留 Backtrader 特定的 correlated order request/BT-binding adapter 与其他通用调用端；journal/port schema、provider dispatch authority 和 durable state 归 SDK execution owner；`factor_execution/` 仅保留 BT 因子/策略事实；`service/` 不持有服务组合、factory、transport 或恢复能力。BT 不按交易所建立专属 adapter；CTP 的 BT 侧仅保留与框架强耦合的 provider-neutral 映射。`bt_api_py.market_cohort` 独立拥有 neutral event cohort 校验，BT 直接使用该 SDK 模块；`feeds/market_factor_source.py` 和 `futures/` 消费 SDK 中立合同/DTO；`futures/expected_projection.py` 验证 SDK-issued expected-calendar snapshot 并投影为 BT 日历。CTP 原生行情、EOD 解析、expected-calendar rules 与 source manifest 归所选 provider，经 `bt_api_py` 公开。2026 日盘 rules 的 review 状态为 HOLD，未验收。
旧的 SimNow weekday/session 前置选择兼容实现及 SDK 旧导入路径已移除，CTP 前置选择使用 `bt_api_ctp.ctp_env_selector`。它不读取已退役的 SDK YAML 配置；`set2` 默认前置与旧实现不同，自动选择还要求真实日历证据才会选用 set1。示例已切换到 provider 入口，该源码变更未做行为或账户验收。
`BtApiStore` 消费 SDK 签发的 typed identity snapshot、provider assurance、SDK vector binding 和 typed account-risk snapshot；SDK 持有身份栅栏历史，BT 提供 Store generation/API 回调，不再读取 raw identity mapping 或本地序列化 digest。SDK 风险读取仍需证明账户事实来自绑定的同一 SDK route/session；该证据未闭合时必须保持 unavailable。Binance/OKX provider 模块与 `bt_api_py.execution_identity_assurance_composition` 当前均为 source WIP，不能据此声称 identity/provider 行为已验收。`bt_api_py.managed_runtime_composition.compose_read_only_runtime` 与 read-only route-owner registrations 同为 source WIP；052 非 CTP `run.py` 仅有源码接线，CTP `simnow_runner.py` 仍走旧的本地 wrapper，均未行为验收。只读组合不证明连接/账户/行情 ready，也不授予写权限。
普通 direct Store 将收到的 `exchange_kwargs`、`execution_config`、debug、显式 transport/event-bus 选项及可注入 factory 原样交给 SDK `DirectApiAssembly`；Store 仅保留 route-name projection 和所需的 Backtrader policy reads。Route-name/config projection 不证明账户、endpoint、session 或写权限。该装配路径当前未完成行为、打包或 SDK 消费验收。
SDK `DirectApiAssembly.from_options` 负责工厂选项与显式 execution 配置开关组合，SDK 提取 execution 配置快照及字段集合；direct 授权准备调用及中立结果检查也归 SDK。Store 提供只读约束与现有配置，负责本地命令冻结、错误转换及自身工厂输入清理。该跨仓调整未提交，未做生命周期或发行验收。
`StoreEventNotifier` 拥有 event generation、Cerebro waiter registry、SDK notifier token/setter binding 与清理；`BtApiStore` 仍提供 Cerebro 现有私有接口，并负责传入当前 SDK facade。此结构迁移不改变通知、wait 或 API lifecycle 的行为合同，也未完成行为验收。
Binance/OKX 订单字段、readiness 读取和持仓模式原生映射由对应 provider 实现；SDK 工作区通过 provider entry point 选择相应投影，并注入中立归一化工具。已有 route 明确声明自有或原通用投影，缺失拒绝；SDK 接线为 WIP，base 共享合同、跨包运行和发行依赖均未行为验收。
OKX 费用范围、分组和原生费率/返佣投影归 `bt_api_okx.fee_projection`；SDK 与 `BtApi` 根据 provider route 注册装配并调用，其他现有 route 明确选择原有通用费用投影。通用投影中遗留的场所字段仍待按职责迁移；声明不证明费用能力，源码迁移未进行行为或发行验收。
Binance、CTP 和 OKX 的原生合约规则分支位于各自 `instrument_rules_projection`；严格 InstrumentSpec 的合约标识、币种、资产及合约类型字段由各 provider 的 normalization policy 声明，SDK 按 route 读取并保留中立 DTO/数值校验。base `08e335e`、Binance `676dd76`、OKX `7951205`、CTP `e2dcd35` 和 SDK `addb34a3` 仅源码迁移；其他 route 使用原通用字段，字段收窄及发行依赖未行为验收，旧过滤字段仍须核对。
Binance 和 OKX 原有原生错误码分类及明确拒绝码表由各自 `error_classification` 持有，SDK 按场所声明加载；没有可用分类器时不能据此认定订单已拒绝。源码迁移未经订单状态行为或发行验收。
Binance 的原生 `S`/`ps` 订单方向候选由其 provider 选择；SDK 通过 `bt_api.order_side_projections` 按 route 选择候选并归一化。其他现有 route 显式使用 base 旧通用别名，别名中的原生字段仍须核查。缺少声明时结果为 UNKNOWN；尚未运行或发行验收。
SDK 的 `bt_api.normalization_policies` 按 route 选择 provider 的行情时间字段、资金费率字段、数量单位、乘数、零余额币种、订单成交来源、模式 ACK 和撤单投影；资金费率的费率、时间、间隔与原始审计字段由 Binance/OKX 显式声明；通用手续费投影的原生费率与币种字段由 Binance/MEXC 显式声明，base 仅保留中立字段；CTP 原生撤单字段属于 CTP provider。其他已声明 route 显式选用 base 旧通用策略，旧 native 别名仍须核对；缺少策略保持 UNKNOWN。此迁移未运行或发行验收。
SDK 归一化中的事件标识、审计字段、盘口序号/前序号及 tick 字段由 provider 策略选择；tick 的中立字段归 base；交易日/行动日字段由 CTP provider 声明中立及原生别名，其余十二家显式仅声明中立字段，Base 默认为 None，旧十家的大写候选已移除，是破坏性收窄；其他字段仍部分继承旧集合。此结构要求 base/provider 同步更新；SDK 继续持有中立事件与 sealed attestation，别名收窄和各场所原始字段覆盖未经行为或发行验收。

共享 Base 的合约、余额、持仓、订单和成交默认字段中已去除一批 CTP 风格别名；CTP 对应字段继续由其 provider 策略声明。其他交易所专有别名仍需逐项收敛，字段来源与全量原始输入覆盖未经验证；跨包源码未提交。

合约元数据的 filters、合约面值/倍数及类型字段由 Binance 或 OKX provider 明确选择，Base 默认不启用这些场所专用规则。其他 provider 的自身字段覆盖、版本组合及行为仍待审阅后验收。

Base 默认字段进一步去除一批 OKX 风格订单、成交、账户与元数据别名；OKX 保留自身声明和带符号费用币种规则。身份冲突检测暂保留旧字段集合，其他场所实际输入覆盖及跨包行为仍未验收。

买卖/持仓方向候选和 position-mode 的中立值转换由 `bt_api_base.execution_identity_projection` 承担，SDK 负责选择 provider 字段策略。该投影不证明身份或授权，跨包源码未行为验收。

Base 不再默认选择 `positionAmt`、`crossUnPnl`、`lastUpdateId` 和 `dualSidePosition`；Binance 策略显式持有这些选择。`clientOrderId`、`executedQty`、`cummulativeQuoteQty`、`commissionAsset` 从 Base 默认移到源码已使用它们的 Binance/MEXC/Kraken 策略；`marginBalance` 和 `initialMargin` 分别由已有对应字段的 Binance/dYdX 与 Binance/Hyperliquid 声明。其他 provider 的原始输入覆盖仍未证明，未做行为验收。
合约元数据通用投影位于 `bt_api_base.instrument_metadata_projection`，Binance/OKX/CTP 的字段集合由各 provider 策略提供；其他 route 暂保留旧通用别名。此源码未行为或发行验收，元数据不等于合约规则或来源证明。
账户权限的中立结果与多行合并算法位于 `bt_api_base.account_permission_projection`，SDK 保留原兼容入口及旧字段选择；`perm` / `canTrade` 和显式身份来源仍须逐 provider 归属，当前未收窄以免改变冲突判定。base `651a2b24`、SDK `1f5dec05` 仅源码迁移，未行为或发行验收。
余额行通用投影位于 `bt_api_base.balance_projection`，各 provider 声明字段和嵌套来源，SDK 保留账户币种选择与权限合并；其他 route 暂保留旧通用别名。源码字段收窄未经行为或发行验收，不证明账户事实。
持仓通用投影位于 `bt_api_base.position_projection`，各 provider 声明自身数量、方向及相关字段；其他 route 暂保留旧通用别名。源码字段收窄未经行为或发行验收，不证明持仓事实。
订单与成交的标识、数量、价格、费用币种及有符号费用选择由 provider 声明，SDK 保留统一结果、状态和关联处理。其他 route 暂保留旧通用字段；显式身份字段仍待核对，字段收窄未经行为或发行验收。
订单状态和持仓模式的场所字段、别名由 provider 策略声明；SDK 保留中立状态、终态及未知处理。其他 route 暂保留旧映射，显式身份和权限字段仍待核对；场所别名收窄未经行为或发行验收。
CTP 原生持仓和平仓规则的结构化规划器位于 `bt_api_ctp.ctp_close_plan`，`bt_api_py.ctp_close_plan` 仅惰性转发符号；其结果仍明确不可执行，不授予账户或订单权限。该迁移未做运行或发行验收。
SimNow 前置对与配置校验属于 `bt_api_ctp.simnow_store_profile`，`bt_api_py.ctp_profiles` 为惰性导出，028 示例仅做结果类型与异常投影；示例仍是工作区 WIP，源码校验不证明账户或授权。

`bt_api_execution.service_owner_book_projection` 承担恢复 journal 的归属簿 DTO 输入投影；BT service 仅注入框架异常类型并调用，BT 工作区接线与行为尚未验收。

`bt_api_py.bounded_api_close.BoundedApiCloser` 拥有 SDK API 的有界关闭线程与保留结果；BT Store 工作区保留借用 API 约束、错误及健康投影。此拆分未行为或并发验收。

`bt_api_py.service_observation_assembly` / `service_observation_clients` 管理 SDK 只读服务装配及客户端，CTP 专用元数据解析和 instrument 选择位于 CTP provider；BT `service/service_observation.py` 工作区绑定 Store/bar/orderbook，tick 暂不可用；观察配置、中立类型和异常直接由 SDK 导出，两个示例已切换类型导入。跨仓行为和发行尚未验收。

既有迁移草稿须逐函数确定为 SDK 通用能力、BT 中立映射或退役；单纯搬移文件不代表重构完成。当前 CTP source-clock 未就绪，EOD 最新/定稿性与产品目录覆盖不完整，2026 日盘 expected-calendar review 为 HOLD 且未验收，option fee issuer/币种证明未注册；相关能力保持 unavailable/fail-closed。
上述均为迁移目标；当前目录变化尚未通过结构、导入、发行或行为验收，也不证明账户能力。

每个子目录里的 `.py` 文件应围绕该目录的一项连贯职责；`__init__.py` 是包入口，具体实现按业务命名。包内数据仅保留运行必需且明确加入分发的无秘密资源；测试样本与大型结果放测试或证据位置。不要以“utils”“common”为理由聚合不相干的职责。

## 4. 测试、示例和工具

| 路径 | 职责 |
| --- | --- |
| `tests/unit/` | 对单个模块或合同进行隔离测试。 |
| `tests/integration/` | 组件边界和组装行为；真实外部依赖、账户和模拟替身必须明确区分。 |
| `tests/functional/` | 用户可观察的端到端/策略行为和回归；`strategies/` 是策略回归测试。 |
| `tests/performance/`、`tests/bench/` | 性能合同和基准；记录环境、统计口径，时间敏感测试按项目现有串行策略运行。 |
| `tests/fixtures/`、`tests/datas/`、`tests/assets/` | 稳定、无秘密的测试输入与资源；标注来源、许可、生成方法及是否冻结。 |
| `tests/factories/`、`tests/test_utils/`、`test_support/` | 测试对象工厂、测试工具和共享支持；不能作为产品实现的依赖。 |
| 其他 `tests/` 文件及子目录 | 依其实际测试目标、夹具或支持用途归类；历史布局不自动表明单元或集成证据等级。 |
| `examples/` | 用户可运行的配置、策略和示例说明；每项注明依赖、模式、外部服务与副作用。共享示例辅助只服务示例，不能成为包运行依赖。 |
| `examples/unified/013_1_midfreq_cross_arbitrage/provider_runtime.py`、`013_2_highfreq_calendar_arbitrage/provider_runtime.py`、`013_3_sa_midfreq_simnow/provider_runtime.py` | 各示例的 provider-neutral SDK 组合薄入口；当前仅有源码，未完成行为验收。013_3 的 `legacy_runner.py` 原生网络辅助仅供已禁用的历史网络路径；其现有 replay 路径保留。 |
| `examples/_support/ctp_legacy_example_support.py`、013_1/013_2 `ctp_example_support.py` | 保留旧 API 的明确退役拒绝；已清除八个拒绝后的不可达凭据、连接与框架装配代码，不恢复旧 runtime。007 的候选名称排序已迁至 CTP provider、通过 SDK 委托；其余三份示例的未引用旧配置常量尚未清理。源码未行为验收。 |
| `scripts/`、`scripts/ci/`、`scripts/debug/` | 可发现的开发、CI、调试和一次性任务入口；应说明前置条件、输出和副作用。历史认证脚本要保留其证据语境，不应默认作为当前运行入口。 |
| `tools/` | 仓库辅助工具和专项验证；与 `scripts/` 的既有职责有交叉时，沿用相关工具的现有位置，不新造同义入口。 |

测试文件按被验证行为命名，夹具不得伪造未建立的生产事实；隔离测试、源码模拟、真实账户、安装包与性能证据分别报告。工具输出默认不回写源码目录或覆盖历史证据。

## 5. 文档与文件类型

`docs/source/` 放面向读者的文档：`getting-started/` 和 `tutorials/` 用于学习，`user-guide/`、`advanced/` 和 `migration/` 用于完成任务，`api/`、`reference/` 用于准确参考，`developer-guide/` 用于开发规范，`strategies-series/` 为策略系列。`locales/` 和 `_static/` 分别服务翻译与静态资源。实际站点入口和构建规则以文档配置为准；增加用户文档时同时检查导航和双语维护需求。

`docs/_internal/` 存内部计划、设计、迭代记录和明确保留的证据，不应成为唯一的用户使用说明。其他 `docs/` 路径以现有站点、内部项目和维护用途分类；生成文件不要冒充源文档。中文 Markdown 默认 UTF-8 BOM，既有格式及冻结证据例外见 `AGENTS.md`。

无论位于何处：源码实现合同；配置声明可验证参数和安全默认值；无秘密模板提供示例；测试断言行为；夹具是输入；文档解释用途；生成文件有可追溯来源；证据记录真实范围和时间。文件后缀不能决定是否公开、可执行、安全或可删除。

## 6. 已观察到的偏差与待核查事项

本节是带证据的工作区快照，不是全仓逐文件合规结论。优先级是处理建议，不授权重构或删除；每项修复都须核实调用者、兼容性和测试后独立验收。

| 优先级 | 事实与影响 | 建议后续动作 |
| --- | --- | --- |
| 高 | 截至 2026-11-01，迭代 53 工作区已删除若干 `backtrader/stores/service_*.py` 及执行/CTP 文件；当前工作树存在 `backtrader/service/`、`backtrader/execution/` 和 `backtrader/factor_execution/` 候选目录。这些变化尚未通过结构、导入、发行包或行为验收；目录落点不证明职责已完成迁移，也不代表可用 API。 | 按职责逐函数核对 BT 薄桥、SDK/provider 通用能力与无用/重复代码，再完成调用点、测试、打包和文档验收；仅在相应验收后更新支持状态。 |
| 高 | 当前 `backtrader/stores/btapistore.py` 从 `..execution.managed_execution` 导入携带 BT 订单及回调的框架执行适配合同；恢复协议与校验器由 SDK `bt_api_py.service_recovery` 提供，BT 的旧重导出模块及两个根导出已退役。`service_execution_group.py` 保留 Strategy/Broker 及线程绑定，服务组中立 route、结果与异常的旧 BT 别名已退役，调用者应直接从 `bt_api_py.service_group_rpc_client` 导入；`service_recovery_attestation.py` 等仍需逐函数核对。相关结构、导入、发行包及行为验收未完成。 | 保持恢复协议及持久化实现由 SDK owner 负责；逐函数审查其余 service 模块、调用点与打包，再分层验收。 |
| 高 | 迭代 53 当前工作树将 neutral cohort validator 实现放在 SDK `bt_api_py.market_cohort`，BT 直接消费 SDK，旧本地门面已移除；factor-source、EOD ranking projection 和 option-premium 也已改为中立边界。路径存在不代表重构验收。CTP source-clock 尚未就绪，EOD 报告最新/定稿性和产品目录覆盖不完整，CTP execution-rules snapshot issuer 与 fee-currency proof 未注册，因此真实时钟、完整 EOD selector、CTP option fees 和卖方 margin 均不可用。 | 保持 fail-closed；待 provider source/issuer、clock/currentness、catalog 和 fee evidence 接入后再分别做结构、导入、发行包、行为及账户验收。 |
| 中 | `conftest.py` 的 journal port 导入已改为候选位置 `backtrader.execution._journal_ports`；该模块及 SDK facade 为未提交 WIP，尚未验证导入与 fixture 行为。`scripts/run_iteration50_live_factor_benchmark.py` 的 journal 构造已改走 BT 端口和 SDK 决策键；所选旧版 BT 根目录可能缺少新桥，原 source pins 未覆盖 SDK journal。`scripts/iteration50_installed_fixture.py` 仍引用旧 journal、factor 和 registered-sim 路径，且被迭代 51 工具复用。 | 保留历史证据；梳理基准跨版本选源及 SDK 来源固定，迁移安装夹具的活跃入口；未做导入或行为验收，不恢复已退役实现。 |
| 高 | `examples/unified/007_ctp/run_runtime.py`、`examples/unified/028_alpha003_simnow_minute/protected_simnow.py` 与 `scripts/ci/smoke_iteration41_registered_offline.py` 当前明确声明旧 runtime 入口不可用；归档的旧 CI 脚本已删除。 | 替代的注册式离线 smoke 能力尚未建立；其他旧入口继续逐项核实，不恢复隐式兼容包。 |
| 中 | `backtrader/feeds/btapifeed.py` 与 Store 当前通过 `backtrader.utils.bar_projection` 共用 BT bar 投影，不再从 Store 导入 CTP 时间函数；`backtrader/cerebro.py` 的 live cohort 路径仍直接依赖研究类型、精确 `BtApiFeed` 类型及其接口。该源码结构尚未行为验收。 | 结合现有时钟与数据合同审查 cohort 是否需要窄接口；保留现有语义，避免为消除引用而破坏多数据行为。 |
| 中 | `BtApiStore` 现在继承 `Store.put_notification()` 与 `Store.get_notifications()`，不再维护第二套通知队列或 drain 逻辑。基类用队列 sentinel 界定每次 drain；本次只完成源码结构归属，未行为验收。 | 按既有 Store 通知合同继续保留单一队列 owner；后续行为验收覆盖并发 producer 与批量 drain。 |
| 中 | `backtrader/test_helpers.py` 位于发行包，其文档示例面向测试；`setup.py` 使用 `find_packages` 分发 `backtrader`。这使测试支持与产品包边界交叠，但不证明没有外部使用者。 | 查找调用者及兼容承诺；新测试支持放 `tests/`，旧文件是否迁移须单独评估。 |
| 中 | 历史认证脚本仍位于 `scripts/`，例如 `scripts/run_simnow_c01_native_td_read_v20_root_activation_r2.py` 指向退役包内路径；脚本存在不等于入口可运行或获准执行。 | 建立入口状态和历史证据索引，区分活跃工具与冻结记录；用户已授权删除相关冻结历史证据，已消费调用不得重跑。 |
| 高 | SDK 建立 Feed 后通过 `get_verified_stream_configuration` 钩子接收 provider 验证的流参数；CTP 自动选中地址的验证和投影已归 `bt_api_ctp.stream_configuration`。 | 该跨仓源码和旧测试引用尚未提交、未运行；其他 provider 的合同及发行兼容性待审阅后验证。 |
| 高 | CTP quote V2 原生类型、回执及字段匹配在 `bt_api_ctp.quote_v2_provenance`，专用时间字段解析在 `bt_api_ctp.quote_v2_time`；SDK 保留严格 schema 识别、direct、队列绑定及 opaque 证明签发。 | 跨仓源码未提交、未行为验收；此结构不证明来源时钟或执行资格。 |
| 高 | SDK `bt_api_py/bt_api.py` 仍包含 CTP 专属授权、private/market ingress 的实例接线、查询证据及恢复代码；BT 已消除显式场所分支不代表 SDK/provider 边界完成。 | 按状态、锁、source/authority 的实际 owner 逐组迁至 CTP provider 或 SDK 中立合同，修复直接调用；不按名称机械搬运，待审阅后再验证行为。 |
| 高 | `bt_api_py.execution_identity_assurance_composition` 与 Binance/OKX `execution_identity_assurance_provider`、`bt_api_py.managed_runtime_composition.compose_read_only_runtime` 及其 route-owner registrations 当前为 source WIP；BT Store/052 的消费接线不构成 identity、route、连接或账户行为验收。 | 继续按 neutral port/facade 接线并分别验证 provider ownership、只读生命周期和 route capability；缺项保持 unavailable，不以 profile 或配置声称授权。 |
| 中 | `examples/unified/013_1`、`013_2`、`013_3` 新增 `provider_runtime.py` 薄入口；013_3 `legacy_runner.py` 的 native network helpers 仅属已禁用的历史网络路径，replay 保留。新入口尚未行为验收。 | 逐入口核对 SDK composition、replay 分支和禁用网络边界后单独验收；不因 replay 可用推断 live/provider 支持。 |
| 中 | `README.md`、`AGENTS.md` 和代码/构建配置存在可能过期或互相矛盾的信息，例如前者声明 PyPI 安装，而后者当前称仅能从源码安装；`setup.py` 的分发名称为 `back-trader-python`。 | 单独核实实际发布状态后统一说明；本规范不据此推断当前 PyPI 发行状态。 |
| 高 | `setup.py` 的许可证分类器写为 MIT，而仓库 `LICENSE` 是 GPLv3 文本，README 也标示 GPLv3；发行元数据与仓库声明不一致。 | 独立核实项目许可及发行元数据后修正；这里仅记录不一致，不作法律结论。 |
| 待核查 | `reports/`、`artifacts/` 等同时有已跟踪材料和可能的本地产物，`scripts/` 与 `tools/` 也有历史职责交叉。 | 先做逐项来源、依赖、冻结和保留策略盘点，再制定整理计划；不要批量删除或移动。 |

## 7. 提交前检查

1. 说明新增/修改文件属于哪个最具体的职责，公开接口、依赖方向和可选依赖是否改变；未分类项目先调查。
2. 检查真实调用者、导入、副作用、包数据和安装包；新入口有无重复、权限边界及可用性说明。
3. 测试与变更风险相称，按实际说明源码、模拟、安装包或真实账户的证据等级；文档链接、导航、编码及中英文同步按需核验。
4. 遵循现有 `dev` 小轮验收、精确暂存和提交，保留无关改动及冻结材料；结构改变时更新本文与 `AGENTS.md`。

## 8. 参考依据与适用范围

- [Python Packaging User Guide：src 与 flat 布局](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/)：两种布局各有取舍；当前 flat 布局需特别验证安装包与源码导入来源，并不因此要求迁移到 `src/`。
- [pytest：Good Integration Practices](https://docs.pytest.org/en/stable/explanation/goodpractices.html)：测试布局和导入方式影响验证对象，应有意识区分安装包与源码测试。
- [Python 导入系统：Packages](https://docs.python.org/3/reference/import.html#packages)：包提供模块命名层次；文件夹本身不自动保证职责或依赖方向。
- [Diátaxis 文档框架](https://diataxis.fr/)：教程、操作指南、参考和解释对应不同读者需求；不要求机械创建四套目录。

这些参考提供通用原则；本仓库的具体边界、兼容例外和迁移顺序是结合当前代码与工作流程制定的项目约定，并非某个外部标准规定的唯一目录树。
