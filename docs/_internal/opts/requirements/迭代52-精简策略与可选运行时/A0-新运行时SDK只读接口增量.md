# A0：新运行时 SDK 只读接口增量（I52-A）

日期：2026-10-31

## 范围与快照

本清点仅核对以下公开输入：SDK runtime 的 runtime/src/bt_api_runtime/__init__.py、assembly.py、sdk_readonly.py、runtime/README.md；Backtrader 已提交的 A1-统一配置与适配器合同.md；SDK parent 的 docs/ITERATION52_A1_SDK_READONLY_OWNER_ROUND_20261031.md。没有读取配置、环境变量、私密文件或历史 evidence；没有执行运行时或测试。

- bt_api_runtime：dev，7b05ffc6e07a86318a70d4f8e8144ffb48737b0d。
- SDK owner 功能提交：f6f70ca4538f86b2eee68cca627a136a11299435。
- bt_api_py parent：dev，2b603535（任务快照中的短提交号）。
- Backtrader：dev，da5c6d40907fb0267663f1bc278fe63b572ec728；这是本文新增前的仓库 HEAD 快照。该快照不包含本文。
- Backtrader A1 合同文件已跟踪且无工作区修改；其最近修改提交与上述写入前 HEAD 一致。本文新增路径在写入前不存在。

## 导出 API 清点

bt_api_runtime.__init__ 汇总两个模块的 16 个公开符号。责任和限制如下；“直接调用者”指代码中的组合路径，不表示真实账户已调用。

| 符号 | 公开责任 | 直接调用者 / 组合路径 | 源码支持 / 拒绝 / 未证明 | 后续决定 |
|---|---|---|---|---|
| **FeedSpec** | 声明代码持有的 feed 名和市场周期。 | 放入 RouteBinding 或 RouteBindingV2；assemble_run 检查并创建 BtApiFeed。 | 仅支持固定 1m；要求有效且不重复的 feed 名。Feed API 有历史和实时能力检查。不证明数据源或时钟真实绑定。 | 在后续适配合同中决定首个受支持产品、feed 字段和时钟/序号语义。 |
| **RouteBinding** | 把 v1 的可信 route 绑定到 Strategy 类、feed 声明和零参数 provider factory。 | 应用代码创建，放入 RuntimeBindings，由 assemble_run 按已解析 route 选中。 | 检查 Strategy 子类、feed 和 callable；不加载任意模块。factory 必须返回全新 ServiceReadProxy。代码绑定不证明远端 provider/account 身份或许可。 | 明确 trusted registry 与 factory 的部署加载/更新权威。 |
| **RouteBindingV2** | v2 对应绑定，附带 route 中的 capability 和策略参数合同。 | 应用代码创建，放入 RuntimeBindingsV2；合同 resolver 验证计划后匹配此 route。 | 静态绑定 route、Strategy、feed、provider factory。源码只要求 market.read 与 account.read 存在；合同/README 记录写请求在 factory 前拒绝、启用插件拒绝。仍不授予许可。 | 固定 capability 与 permit 的独立权威和拒绝语义。 |
| **RuntimeBindings** | v1 合同 registry 与完整 route binding 的不可变配对。 | 作为 assemble_run(source, registry) 的第二参数。 | 要求每条合同 route 恰有一条匹配 binding，同一策略引用的 Strategy 类一致。不是 provider 身份注册服务。 | 决定 registry 的可信来源、刷新和版本升级规则。 |
| **RuntimeBindingsV2** | v2 合同 registry 与完整 route binding 的不可变配对。 | assemble_run 的第二参数；v2 resolver 使用九个 route reference、能力声明和参数合同选择 binding。 | 校验 exact DTO 类型、路由集合和类一致性。静态相等不证明部署映射、授权或真实账户。 | 与合同 owner 一起冻结 v2 registry 映射的治理规则。 |
| **RuntimeAssemblyError** | 暴露有限、非敏感的 ASCII 错误码。 | assemble_run、RunSession 的边界错误。 | 错误信息不承载配置或 credential 内容；失败关闭，不回退到直接运行、本地撮合或 mock。 | 后续统一稳定错误码及面向调用方的状态映射。 |
| **RunSession** | 一次性运行句柄；绑定装配线程，支持停止请求及 owner-thread 清理。 | assemble_run 返回；调用者执行 run()，可在其他线程调用 request_stop()，并可显式 close()。 | run() 调用普通 Cerebro.run()；不是第二调度器。停止资源清理由 owner thread 执行。失败时尽力停止 Broker、Feed/Data、Store 和 proxy。它不关闭 SDK runtime，也不包装 Strategy 构造/start()。 | 定义 Strategy _start() 失败及 observer 通知的完整收尾合同；现有 best-effort 不视为完整生命周期接受。 |
| **assemble_run** | 解析合同输入，验证/解析 route，装配普通 Backtrader 只读 session。 | 应用把 source 与 code-owned registry 传入；返回 RunSession。 | v1/v2 都在 provider factory 前验证合同和代码绑定；v2 要求 account/market read、拒绝启用插件。若 factory 有 callable preflight(route)，要求其返回严格 True；无 hook 的零参 factory 保持兼容但没有 route-preflight 保证。随后检查 Backtrader ServiceReadProxy.supports_bar_history，要求全新只读 proxy、所需历史/实时 feed；建 BtApiStore、market_data_only=True Broker、BtApiFeed 和 Cerebro。不证明权限、身份、完整启动/清理或 provider truth。 | 决定 A1 是否要求所有生产 factory 实现 preflight；补齐 startup failure、readiness 和完整收尾验收。 |
| **SdkReadOnlyError** | SDK 组合边界的有限非敏感错误码。 | SDK spec 检查、factory、resource owner。 | 使用 ASCII code；不会把底层 SDK 异常文本作为公开 detail。 | 与合同错误类型对齐但保持 SDK 边界独立。 |
| **SdkRouteReference** | 显式映射一个 I52 符号引用到一个代码绑定 SDK 引用。 | 填入 SdkRouteReferencesV2，由 spec 预检逐项对比 route 字段。 | repr 脱敏；相等只验证映射表一致，不是身份或授权证据。 | 指定映射表由哪个部署 registry 签发、维护和审计。 |
| **SdkRouteReferencesV2** | 持有 strategy、provider、endpoint、account、credential、scope、product、data_source、clock 九组映射。 | SdkReadOnlySpecV2.references；factory preflight 和构造校验。 | 逐项核对 route ref 与所给 pair；各 SDK target 还会与 typed config/domain objects 做结构和请求键一致性检查。不能据此宣称 target 对应远端真实对象。 | 为九类 ref 建立可信 registry 的数据来源和变更控制。 |
| **SdkEnvironmentMapping** | 显式映射 I52 paper/live route environment 到 SDK account environment。 | 放在 spec 内；factory 对所选 route 与 SDK ClientConfig 一并预检。 | 检查静态映射、配置 profile、endpoint 和 account environment 一致。环境名不证明真实环境、account identity 或权限。 | 明确部署侧环境证明与 paper/live 许可隔离。 |
| **SdkClockBinding** | 把 SDK clock ref 与代码持有的 callable 配对，供 proxy 读取本地时间。 | SdkReadOnlySpecV2；factory 把 read 传给 ServiceReadProxy。 | ref 必须对应 route 的 clock selector。此对象只记录意图；未校准，也不证明 provider timestamps 或 clock domain 权威。 | 定义 clock domain/source 可信绑定、校准、时区、偏差与失步拒绝合同。 |
| **SdkReadOnlySpecV2** | 汇集一个 v2 route 的 typed ClientConfig、九映射、identity/peer、account/instrument/scope、endpoint、clock、feed 和 I/O leaf factory。 | 由应用代码构造，传给 SdkReadOnlyFacadeFactory；preflight/build 验证。 | 代码校验 exact typed SDK 对象、route/配置/请求键、scope、bar/1m 和仅 account.read、market.read mounts；拒绝 delegation、不支持额外 mounts。repr 脱敏。typed source descriptor 只检查 SDK 协议结构与请求键，source/provider/clock/session 等声明值未逐项绑定到可信 authority。 | A1 需指定这些输入的可信装配 owner；对 data source 和 clock 建立可验证的权威绑定。 |
| **SdkReadOnlyResourceOwner** | 同线程保留 SDK runtime、account/market client 和 proxy，并有序关闭。 | factory 构造期间填充；应用在 session 结束 proxy close 后，显式调用 factory.owner.close()。 | 先关闭 proxy/facades，再检查 unsubscribe/runtime cleanup 诊断，确认无未决 remote registration 后才关 runtime，最后核对 closed 状态与计数。close 失败或远端注销不确定时保留资源和状态供同线程重试。retry 不是远端成功保证；本地 closed/断连不单独证明远端清理。 | 定义远端注销 receipt、uncertain custody 的最终处置，以及 owner 与 RunSession 的统一生命周期入口。 |
| **SdkReadOnlyFacadeFactory** | 为单条 v2 route 组合真实 SDK runtime、account/market facades 和 Backtrader ServiceReadProxy。 | 应用持有 factory 并将其作为 route 的 provider factory；assemble_run 先调用可选 preflight(route)，再以零参数调用 factory。 | preflight 校验所选 route 与 spec 一致并在 I/O 前检查静态 maps/config；工厂限定 account snapshot 与 market read operations，并令 SDK subscribe 要求 typed MarketSourceDescriptor。外层 transport/subscriber 是注入叶；SDK runtime、facades、proxy 保持真实。未知/不支持 factory 返回对象不会由 runtime 擅自 close；在交回资源前失败的 transport factory 必须自清。 | 冻结 hook 是否成为通用接口要求；补真实 provider、identity/permission、source/clock 真值及正常/失败关停证据。 |

## 装配与权限边界

源码路径为：合同 parse_config、resolve/validate plan → 按 route 选择 code-owned binding → 若 factory 有 preflight hook，则先验证选中 route → 检查 Backtrader read proxy API → 调用 factory → 校验新鲜只读 proxy 与各 feed 能力 → 建 Store/Broker/Feed/Cerebro → 返回 RunSession。SDK factory 的 hook 只做选中 route 与所给配置/映射的一致性预检，不是身份服务、认证结论或授权。兼容保留的无 hook factory 不享有此项预检。

SDK source/fake 路径只开放 account snapshot 与 market subscribe/unsubscribe/snapshot/head/read_after/history。Broker 固定 market-data-only 并本地拒单；replay、shadow、plugin execution、旧本地 paper simulation 和订单路由未支持。paper/live 名称、静态 capability、typed input 或成功建立 transport 都不自动授予写权限。

## 所有权、清理顺序与不确定性

- SDK owner 固定创建线程。RunSession.run/close 也要求装配线程；request_stop() 可跨线程调用，但只通知 Cerebro，清理仍在 owner thread。
- 正常路径由 Cerebro 执行组件生命周期；RunSession 检查/补充 Store 停止，并确认 proxy 已断连。SDK facade factory 的应用调用方随后关闭 factory.owner；session 不关闭 shared SDK runtime。
- RunSession 对运行异常做 best-effort 补偿：Broker → 仍活动的 Feed/Data → Store → 必要时 proxy。若 metadata probe 仍在读 proxy，不会并发 disconnect。此代码不接管 Strategy 生命周期；Strategy constructor 或 _start() 自己产生的外部资源若在抛错前未释放，不能由此路径保证清理。
- SDK owner 关闭时先 disconnect proxy（proxy 拥有 account/market facades）；之后核对 market unsubscribe uncertainty 和 runtime 的公开 cleanup/registration counters；只有当前置状态可观察且无未决 remote registration 时才 close runtime；再核对 runtime closed 且 counters 清零。失败会保留整个资源组，可由 owner thread 重试。
- SDK 没有独立的 remote close receipt DTO。unregister response lost、uncertain counters、诊断无法读取或 runtime 关闭后 counters 非零时，结果必须保持未确认；本地断连和 retry 均不证明远端已注销。transport factory 若在将资源返回给 SDK 前部分分配后失败，必须自行清理。
- A1 合同文档亦记录 Backtrader 启动失败后的 best-effort 清理仍不能证明 Strategy 与 observer 已完整清理。当前 read-only owner round 未扩展该保证。

## 版本、依赖和验证证据

- bt_api_runtime 是单独 build root，README 标为 0.1.4，要求 Backtrader 暴露 ServiceReadProxy.supports_bar_history；该 API 在 README 指明的 Backtrader source commit 0f88508d3 提供。上游 Backtrader 发行版本仍是 1.4.0，单靠版本号不能识别该 capability。
- runtime README 声明 Python 3.9+；普通 assembly 依赖 bt_api_run_contract 与具备上述 API 的 Backtrader build。README 的安装顺序还列出 bt_api_base。SDK 自身保持可选并延迟加载；SDK bt_api_py 需要 Python 3.11+。Backtrader A1 文档记录 contract 0.1.4、bt_api_base 0.15.8、bt_api_py 0.15.5。Python 3.10 单独导入尝试曾因环境缺少 pytz 而在 Backtrader 导入阶段停止，不能据此宣称支持验证通过。
- 最新 owner round 记录 wheel-target 加本地 SDK/Backtrader 源码组合 55 passed、1 条现有 Quandl 弃用警告；Root 同轮实际执行观察的解释器版本为 Python 3.11.5，轮记录本身未记版本。此结果明确为 SOURCE_FAKE_SDK_READ_ONLY_COMPOSITION_ONLY：合成 transport/subscriber/service-response leaves，不连接真实 provider/account，不是隔离依赖解析、release 或 paper/live 验收。本文没有重跑测试。
- SDK MarketSourceDescriptor 必须是 typed 协议对象并匹配所请求 key/stream metadata；其 source、provider、clock domain/source、session 等声明的真实性和 clock calibration 未对照可信部署 authority 验证。账户 identity/permission、真实 provider、远端清理、生产部署均 NOT_PROVEN。

## 当前可执行决定

1. 继续把 bt_api_runtime 作为 Backtrader 外部的可选组装 owner；Backtrader 保留 Feed/Broker/Store/Cerebro 适配，不把 Python 3.11+ SDK 变成 Backtrader 普通安装的强依赖。
2. 在确认合同 owner 与 SDK owner 的部署 registry 责任之前，不把静态 selector 或 preflight 解释成真实 provider/account identity 或授权。
3. A1 后续要单独决定通用 provider factory 的 preflight 是否强制，并补 source/clock authority、Strategy startup failure、远端 unregister uncertainty 与 owner-thread shutdown 的实际证据。
4. 当前 55 项 source/fake 结果不计真实账户或正式 paper/live 用例；不据此提升正式通过数或宣称完整 A1 已接受。
