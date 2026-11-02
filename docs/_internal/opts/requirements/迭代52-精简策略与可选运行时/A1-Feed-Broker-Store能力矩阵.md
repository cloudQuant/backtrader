# I52-A 候选小轮：Feed / Broker / Store 能力矩阵

状态：**源码观察 / 候选矩阵，不是 A1 验收**。观察基线为 Backtrader `dev` `b0ef00401b185372095860589eff3dc4f1d44067`（2026-10-30）。本轮仅整理公开源码与已存在的公开验证记录；不运行测试、账户、交易、replay、shadow 或本地撮合，不改变生产代码，也不授予任何写权限。

## 判读约定

- **源码/API 存在**只表示 checkout 暴露相应类和入口，不证明 provider、账户、产品、部署或完整组合可用。
- **SOURCE_FAKE** 表示框架真实对象组合到测试 fake 边界；不证明 fake 以外的 provider、账户、权限和写路径。
- **NOT_PROVEN** 表示具体能力/绑定没有足够端到端证据；配置 mode 名称、`provider` 名称和 `market_data_only` 开关都不是授权凭据。
- **REJECTED** 表示当前入口明确拒绝该组合/操作；**FUTURE** 表示长期候选，本轮不实现、不运行、不验收。

表中 `direct` 指由 Backtrader Store 直接连接或注入 provider/SDK API 的路径；`service` 指经 SDK service facade / execution runtime 的既有路径。它们是装配边界，不是 `paper` 或 `live` 模式的别名。

## 组合矩阵

| 组件组合 | direct / service | 行情 | 账户与订单 | 线程与资源所有者 | 明确 fail closed / 证据边界 | 尚待验证 |
|---|---|---|---|---|---|---|
| `PandasData` / `GenericCSVData` + `Cerebro` + `BackBroker`；没有 `BtApiStore` | local/framework-only、本地回测 API | 本地 DataFrame / CSV 输入 | `BackBroker` 是进程内 broker；订单由本地 broker 处理，不是 provider paper account，也不产生真实账户回报。[S7] | `Cerebro` 驱动 Feed、Strategy 和 Broker 生命周期；没有 SDK runtime / provider facade。 | 这是现存本地回测组合，不应标成 I52 `paper`。源码存在不是任何外部服务接受证据。 | 仅按既有回测合同使用；不在此轮运行。与 replay、shadow 的归属另行研究。 |
| `BtApiStore` + `BtApiFeed` + `BtApiBroker`，由 Store 创建或注入 direct provider / SDK API | direct | `BtApiFeed` 可从 Store 启动、订阅、请求 backfill 并消费 live bar/tick/orderbook 路径；实际通道、历史能力、symbol/product 和时钟依赖所接 API。[S1][S2] | Broker 启动会刷新余额、持仓和开放订单；订单提交、撤单与回报映射存在代码路径。SDK 写入路径要求 async submit/cancel/query 能力及启动对账；直接 CTP 写入口关闭，需受管 adapter 路由。[S1][S3] | `Cerebro` 执行 Feed/Broker hook。Store 区分内部创建与注入 API；停止时对 SDK API 调用 `close`，普通 API 调用 `disconnect` 或 `stop`，owned 标记还影响重建/重置。符合条件时 Store 会创建异步命令 worker，另有有界关闭线程。SDK/Store/Feed 的具体线程与关闭责任随 backend、api 来源和 adapter 变化，不能泛化成单线程或统一所有权。[S1][S2][S3] | 占位 provider 和遗留 gateway 入口会拒绝；SDK 交易未具备 async command contract、启动账户/订单/风险证据时拒绝。类和写方法存在不等于任何具体 provider/account 已获准。[S1][S3] | 选择并固定 provider、product、数据源、account/endpoint/credential/route scope；验证 Feed 时钟/序列、历史到实时切换、订单状态/部分成交/费用及 cleanup。分别证明外部 paper 与 production live，不能从配置名或 `BtApiStore` 推断。 |
| `BtApiStore` + `BtApiFeed` + `BtApiBroker(market_data_only=True)`，direct API | direct、只读观察 | 仍由 direct Store/API 提供；是否为真实行情、是否完整及是否有正确时间/序列，取决于真实 API 和 provider 验收。 | Broker 可读取账户状态，但订单提交与撤单被 Broker 本地拒绝；这是观察路径，不是 paper execution。[S3] | Store 与 Feed/Broker 生命周期仍由当前 Store/backend 路径管理；`market_data_only` 不替代 provider facade 的身份、线程和关闭验证。[S1][S3] | Broker `submit` / `cancel` 明确以 `market_data_only` 返回拒绝。若只断言“没有调用写 API”，并未实际覆盖拒绝分支。[S3] | 真实只读账户/行情、拒绝路径的单独验收、freshness/continuity 与 Store 停止结果。 |
| `ServiceReadProxy` 注入 `BtApiStore(api=proxy)` + `BtApiFeed` + `BtApiBroker(market_data_only=True)` | service、只读观察 | bar binding：独立市场 facade、显式固定 timeframe、订阅后分页历史；实时 bar 检查序列、乱序和 history/live 冲突。`ServiceCtpTickBinding` 只给原始 CTP tick，不提供 Kline 历史或在 Proxy 内合成 bar；在 `backfill_start=False` 且满足 `BtApiFeed` 的时钟等条件时，Feed 可另外将 tick 聚合为 timeframe bar；默认 `backfill_start=True` 则因 tick binding 无历史查询而在启动时报错。orderbook 是单独 typed binding。[S4][S6a][S6b] | 独立 account facade 提供带完整性检查的余额/估值、持仓和开放订单快照。原生账户订单不是策略订单归属。Store 入队、submit、cancel 入口和 Broker submit/cancel 都拒绝写入。[S1][S3][S4][S6a][S6b] | Proxy 在构造线程记录 owner thread；连接、读取、订阅、轮询和关闭均要求同线程。Proxy 关闭其使用的账户/行情 facade；共享 `ServiceClientRuntime` 由调用方最后关闭。关闭成功为终态，重跑须新建 facade/proxy，不自动转 direct。[S4][S6a][S6b] | 缺失/不完整账户快照、未知 coverage、单位/币种/position mode 不匹配、未绑定 Feed、订阅/stream 问题、序列缺口、乱序、冲突和无法恢复的 gap 均显式报错，不沿用旧快照静默继续。[S4][S6a][S6b] | 指定实际服务部署、account/resource coverage、每个市场 facade、授权与 runtime lease；实际 venue/account 的读取与恢复仍须单独验收。只读组合不能证明订单写入。 |
| `BtApiStore` + `BtApiFeed` + `BtApiBroker(market_data_only=False)` + `ServiceExecutionSession`（或 `run_configured_cerebro`） | service 托管执行；Store 必须是尚未启动的 `BtApiStore`，Broker 必须为 `BtApiBroker` | Feed 仍通过配好的 Store/API 读取；`ServiceExecutionSession` 本身不是行情 facade，也没有把 service market-read 与 writer 合并为统一交易 Store。Feed 的真实 provider、clock、历史/实时能力仍须逐项确认。[S1][S2][S5][S6a][S6b] | 窄入口要求同一 strategy-client 的 `broker.orders` writer 与 `broker.order_query` query routes；可另配显式 Strategy/account book 路由。订单写入经 managed adapter，策略身份/route 不符时拒绝；该入口不是交易所账户/行情权威，也不等同已批准 paper/live。[S5][S6a][S6b] | Primary runtime 由 session 接管；显式 `owned` account-book runtime 由 session 启停/关闭，`borrowed` runtime 仍由外部 owner 维护。session 与 facade 在创建线程运行；lease/order refresh 由 Broker 轮询驱动，session 不创建专用 lease/order-refresh 线程；Store 在支持的 SDK 路径仍可能创建 command worker。退出时先停 Broker/Store 再关 runtime，并核验清理报告。[S5][S6a][S6b] | 重复运行、wrong thread、runtime 非新建、缺失/歧义 route、错误 Broker/Store、已启动资源、read-only Store、`market_data_only`、channel 和优化模式会在运行前拒绝；配置/启动/route 失败不会回退到普通 `cerebro.run()`。清理不完整会抛错并保留状态报告。[S5][S6a][S6b] | 仍需可信 runtime factory / route scope / account 与策略身份绑定、actual provider 回报、Feed 与执行账户一致性、通知/重连/未决订单政策及完整生命周期证据。`ServiceReadProxy` 不能充当 execution writer。 |
| `ServiceReadProxy` + `ServiceExecutionSession`，试图用同一个 service Store 同时读账户/行情并写执行 | 混合 service 读写 | 读代理是 observation-only。当前代码没有一个同时完成服务账户/行情读取与 service execution 写入的统一 Store。[S4][S5][S6a][S6b] | 不支持将读代理升级成写路由。 | `ServiceExecutionSession` 的 preflight 要求非 read-only Store 和非 `market_data_only` Broker；它负责的 execution runtime 不接管代理所借用的共享 runtime。[S5] | **REJECTED**：`READ_ONLY_SERVICE_UNSUPPORTED` / `MARKET_DATA_ONLY_UNSUPPORTED`。不能捕获后回退 direct。[S5][S6a][S6b] | 需要独立设计新的明确组合和资源协议后再评审；本轮不绕过拒绝。 |
| `9d6182c2e` 的 I52-A1 行情纵切：`BtApiStore(api=fake)` + 真 `BtApiFeed` + 真 `BtApiBroker` + 真 `Cerebro` + 同一 `QuoteObserver` | 测试配置写 `paper`、`live`；provider 叶节点是 fake | 每种配置消费两根确定性 fake live bars，并检查字段、时间、自然 exhaustion 与 watermark；测试未请求真实历史行情。[S8] | fake 客户端内有合成余额/空持仓。Broker 为 `market_data_only=True`，测试没有尝试 submit/cancel；空写调用只证明该用例未发写命令，**不证明拒写**。没有真实账户读取、provider order update 或成交回报。[S8] | 子进程内使用真实 Backtrader 组件；测试显式在 `finally` 停 Store。fake 计数连接/断开；没有证明外部 service runtime、真实 provider 线程或真实账户 cleanup。[S8] | 合同 parser 拒绝 paper mode / live environment 不匹配，并在调用 provider factory 前停止；这属于配置输入校验，不是 permit/注册表/账户身份/写授权验证。[S8] | 只能标 `SOURCE_FAKE_PAPER_LIVE_FEED_PATH_ONLY`。已存在记录报告指定 Python 3.11.5 环境定向检查 `1 passed, 1 warning`；本矩阵未重跑。需要完整 trusted plan→factory→endpoint/account/credential/route 绑定、真实外部 paper account、订单拒绝与通知、live 权限及独立验收。[S8][S9] |

## `9d6182c2e` 范围精确说明

Git diff 中该提交仅新增两个公开路径：`tests/integration/test_i52_a1_paper_live_feed.py` 和 `A1-行情纵切源码记录.md`；没有修改 `BtApiStore`、`BtApiFeed`、`BtApiBroker` 或生产装配代码。子进程实际导入安装的合同 parser；paper/live 两组行情、余额与持仓由测试内 `FakeBtApiClient` 子类提供。每组都走真实 Backtrader `Cerebro` / Store / Feed / Broker 类，使用同一个普通 `QuoteObserver`，但 Feed 输入限于两根 fake live bars、`backfill_start=False`。合同层只测试 mode/environment 错配在 provider factory 前被拒绝。

因此准确证据是：有限 `SOURCE_FAKE_PAPER_LIVE_FEED_PATH_ONLY` 行情链，加一个已安装 parser 的配置错配检查。它不覆盖真实 provider/账户/历史行情、真实 paper endpoint、账号/凭据/许可身份、Broker submit/cancel 拒绝、订单回报、统一 service 读写、完整 plan→runtime 或清理故障。历史公开记录报告指定 Python 3.11.5 环境下定向测试 1 passed / 1 warning；当前矩阵未重跑该验收。[S8][S9]

## Mode 结论：名称不授予能力

| Mode / 路径 | 本轮状态 | 能够据源码/证据说什么 | 不能推断什么 |
|---|---|---|---|
| `backtest` / 本地 `BackBroker` | **I52 长期范围待定；本轮不运行/本地验收** | 现有源码包含 historical/local Feed 与本地 Broker 组合。[S7] | 本地撮合、假 fill 或 `BackBroker` 不等于 provider 外部模拟账户。旧 v4 的 `paper` 语义为 `local_simulation`，不得自动迁移成 I52 外部 paper。[S10] |
| `paper` | **NOT_PROVEN** | I52 目标要求外部 provider paper/simulated account；`9d6182c2e` 只用了 paper 配置名和 fake provider。[S8][S10] | 未绑定或验收实际 paper endpoint、账户、凭据和写路由；不推断已有 paper 写权限。 |
| `live` | **NOT_PROVEN；本轮无生产写授权** | parser 和组合代码可能表示 live environment；这不是运行许可。[S8][S10] | 不推断生产账户、交易所连接或 live write 已支持/已授权。 |
| `replay` / `shadow` | **FUTURE；本轮禁止执行/验收** | 只作为长期架构目标中的待研究 mode。[S10] | 不以旧 local simulation、历史脚本或目录名称宣称兼容；本轮不运行、不验收。 |

## 资源与拒绝边界摘要

1. `BtApiFeed.start()` 会注册至 Store；service-read-only 分支先订阅再取历史，历史读取错误向上抛出。普通 direct backfill 分支对历史异常会记录 warning 并继续，因此 direct/service 的缺口策略并不相同；不得把一个路径的 fail closed 推广到另一个路径。[S2]
2. `market_data_only=True` 同时锁住 Broker 的 submit/cancel，并被 ServiceReadProxy 所需；它只表达 Broker 观察模式，不证明 API facade 是只读权限，也不构成策略 mode 或 permit。[S3][S4][S6a][S6b]
3. `BtApiStore` 可注入 API，也可在需要时创建 SDK API；仅凭构造函数不能确定 transport/runtime 的最终 owner。直接 SDK 路径存在异步命令 worker与有界关闭路径；开始、停止与线程退出状态必须按具体 backend 检查。[S1]
4. ServiceReadProxy 关闭 facade 后共享 runtime 仍由调用方关闭；ServiceExecutionSession 对 primary runtime 承担完整生命周期。两种“service”对象所有权不同，不能只凭同一进程或同一 `BtApiStore` 名称推定所有权已统一。[S4][S5]
5. Broker 通用订单接口、配置 mode、provider 字符串和 `Store.is_connected` 都不足以证明交易能力。缺失 adapter/provider contract、账户身份、数据/订单时钟、许可或资源清理证据时，状态保持 NOT_PROVEN；不得静默 fallback 到 local/mock/direct 路径。[S1][S3][S5][S10]

## 本轮尚需补证的矩阵单元

- 选定一个具体 provider/product/environment，验证 Feed 实际历史/实时订阅合同、时钟域、序列连续性、延迟/新鲜度、gap/resync 和生命周期。
- 分别验证外部 paper 与 production live 的可信 endpoint/account/credential/route identity；mode/environment 错配、缺失授权、错误 account/facade 必须在 I/O 前拒绝。
- 单独覆盖 Broker submit/cancel 的拒绝分支、受管写入 route、订单受理/拒绝/部分成交/费用/撤单竞态和 notify 顺序；`9d6182c2e` 没有尝试写调用。
- 记录 Feed、Broker、Store、facade、runtime、worker/transport 的 owned/borrowed、创建线程、停止顺序、关闭结果和不确定状态；按真实组合证实启动失败的逆序清理与无 fallback。
- 证明纸面 mode 下是真实外部 paper account，不是本地 hypothetical fill；live write 必须另有显式、可核验许可。A1 完成前不得把此表中的源码/API存在提升为产品支持结论。

## 可复核源码与记录

- [S1 `backtrader/stores/btapistore.py`，L4148-L4174、L4212-L4274、L5693-L5748、L6728-L6765、L6945-L6969、L9302-L9324、L9670-L9690、L18624-L18701](../../../../../backtrader/stores/btapistore.py#L4148-L4174)
- [S2 `backtrader/feeds/btapifeed.py`，L408-L472、L1354-L1454、L1456-L1480、L1573-L1620、L1713-L1734](../../../../../backtrader/feeds/btapifeed.py#L408-L472)
- [S3 `backtrader/brokers/btapibroker.py`，L239-L285、L455-L585、L1583-L1607、L3547-L3605、L4125-L4215、L4874-L4891](../../../../../backtrader/brokers/btapibroker.py#L239-L285)
- [S4 `backtrader/stores/service_read_proxy.py`，L85-L160、L207-L324、L330-L385、L387-L465、L500-L574、L727-L813、L1318-L1325](../../../../../backtrader/stores/service_read_proxy.py#L207-L324)
- [S5 `backtrader/stores/service_execution_session.py`，L38-L45、L86-L114、L417-L642、L644-L664、L712-L752、L910-L1000](../../../../../backtrader/stores/service_execution_session.py#L86-L114)
- [S6a `optional-service-read-proxy.md`，L3-L17、L55-L80](../../../../../docs/source/developer-guide/optional-service-read-proxy.md#L3-L17)；[S6b `optional-service-execution-session.md`，L3-L12、L55-L62、L89-L117、L119-L124](../../../../../docs/source/developer-guide/optional-service-execution-session.md#L3-L12)
- [S7 `backtrader/feeds/pandafeed.py` L131、`backtrader/feeds/csvgeneric.py` L336、`backtrader/brokers/bbroker.py` L59、L935、L1324、L1534、L2434](../../../../../backtrader/brokers/bbroker.py#L59-L90)
- [S8 `tests/integration/test_i52_a1_paper_live_feed.py`，L1-L14、L86-L170、L180-L210、L212-L298、L323-L392](../../../../../tests/integration/test_i52_a1_paper_live_feed.py#L1-L14)
- [S9 `A1-行情纵切源码记录.md`，L1-L14](./A1-行情纵切源码记录.md#L1-L14)
- [S10 `A1-统一配置与适配器合同.md`，L32、L106-L110、L148-L156、L181-L191](./A1-统一配置与适配器合同.md#L148-L156)

本文件是静态源码矩阵；保留既有工作区其他改动，不提交。