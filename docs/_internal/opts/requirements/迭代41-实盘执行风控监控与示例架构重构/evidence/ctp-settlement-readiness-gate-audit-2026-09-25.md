# SimNow 7×24 与结算就绪门槛差异审查（2026-09-25）

状态：`READ_ONLY_SOURCE_AUDIT / NO_CONFIG_READ / NO_PROVIDER_SESSION / NO_WRITE`。

本记录只核对公开 SimNow 产品说明、CTP SDK 接口/仓库代码与 fake-only 测试；没有读取私有 `config.yaml`、`.env`、凭据或 one-shot marker，没有连接 SimNow，也没有发送登录、查询、报单、撤单或结算确认请求。

## 裁决

SimNow 的第二套 7×24 前置适合 CTP API 与连接诊断。SimNow 官方产品页明确说该环境只提供 CTP API 测试，不提供结算等服务；其账户资金和仓位与第一套环境上一个交易日保持一致。该产品说明没有承诺 7×24 提供本项目 managed-write readiness 所需的、绑定当前交易日的结算确认读回，因此不能把它作为这项证据来源，也不能用它替代成交后的结算/资金验收。该环境的 `doctor`、配置前置 TCP 检查和受监督只读 API 诊断可以继续保持零写入；不应把缺失的结算证据合成为 `trading_ready`，也不能以改代码绕过此门后在 7×24 下单。

需要验证报撤单和交易后资金/持仓变化时，应由操作者在唯一受保护配置 `examples/013_3_sa_midfreq_simnow/runtime-ctp-private/config.yaml` 中显式填写/切换到 SimNow 正常结算环境的一组成对 MD/TD 前置及对应账户、合约范围。运行仍为 `simulation/sandbox`，配置路径、canonical `ctp:` 字段结构和 runtime identity 保持不变；选择来自用户文件，不由代码按时间、地址形状或 set 标签推断。官方页面将正常环境与 7×24 列作不同环境，并说明正常环境提供每日结算规则。审查没有读取或修改那份本地文件。

切到正常结算环境只解除“没有结算服务”这一能力不匹配，不会自动解除 F14。现有公开 CTP 查询接口没有共同快照版本、完整账户覆盖证明或跨主机/跨用户账户写者锁；严格 F14 仍需柜台/账户控制服务的外部证据，或正式修改验收合同并接受清楚标注的残余风险。不能把正常结算环境当成账户级 writer fence。

## 可追溯证据

| 证据 | 发现 | 对验收的影响 |
| --- | --- | --- |
| [SimNow 官方产品与服务说明](https://www.simnow.com.cn/product.action) | 页面分别列出正常交易环境和第二套 7×24 环境；对 7×24 明示“仅为用户提供 CTP API 测试需求，不提供结算等其它服务”，并说明账户、钱、仓与上一个交易日保持一致。正常环境列出每日结算规则。 | 7×24 是 API/连接诊断目标；当前日结算、资金和持仓变化不能由它证明。完整真实写入验收应选有结算服务的正常环境，并基于动作前后的实际读回做对账。 |
| [SimNow 官方 CTP Mini API 下载页](https://www.simnow.com.cn/static/apiDownload.action) 与 [CTP Mini API V1.7.0 手册](https://www.simnow.com.cn/DocumentDown/api_3/5_2_4/SFIT%2BCTP%2BMini%2BAPI-V1.7.0.pdf) | CTP API 暴露按请求发送、按响应回调的接口；查询完成标志是各自响应流的 `bIsLast`。这些 API 文档没有给每次结算/订单/成交/持仓查询一个共同账户快照令牌，也没有定义账户级 writer lease。 | 原生终包可证明一次请求流结束，不能补出结算服务、共同快照或写者排斥。 |
| `backtrader_runtime/ctp_simnow_td_trading_readiness.py:297-332,363-453` | `verify_ctp_simnow_td_trading_readiness()` 只调用一次 `verify_settlement_confirmation()` 查询；要求匹配当前 BrokerID、InvestorID、TradingDay、连接代次且恰好一条终态记录。它不调用 `settlement_confirm` 写接口，也不授予 write authority。 | 对正常结算环境的读回要求明确且可测试；对 7×24 若没有对应结算记录，应返回拒绝/未就绪，不能用默认值或 fake receipt 标记通过。 |
| `backtrader_runtime/ctp_simnow_managed_runtime.py:398-498,500-540` | 若注入 TD trading-readiness 结果，会重新核验 settlement query、账户、pair、TradingDay 与 generation；省略该前置回调只保留只读启动，文档明确 SDK 之后仍会拒绝缺少当前 settlement readback 的 order write。 | 不能通过“不调用 TD readiness callback”绕开 managed 写入门。 |
| `tests/unit/runtime/test_ctp_simnow_td_trading_readiness.py:307-352,355-377` | 正向测试使用 fake 返回一条精确匹配的结算确认记录，断言一次 query、零结算确认/报撤单写入；负向测试拒绝账户或日期不符的记录。 | 这些测试验证本地合同，不证明 7×24 或任何真实 SimNow 账户会返回该记录。应补一项能力矩阵/配置合同测试，确保 7×24 只读诊断与正常结算写入预检分别标记，不得把 fake 正例用于 provider 结论。 |
| `backtrader_runtime/ctp_simulation_execution.py:12-30,812-827,1029-1045,1612-1627` 与 `tests/unit/runtime/test_ctp_simulation_execution.py:1256-1292,1492-1513` | 执行协议另行要求注入 writer fence 与 native query evidence verifier；本地 lease 只覆盖合作的同主机、同 OS 用户、同 state root 写者。测试明确缺 fence 或只有 `complete=True` 而缺独立查询证据时不准 native dispatch。 | 结算环境选择不会生成 writer fence/查询完整性证明；这是独立外部依赖。 |

## 当前代码门槛差异

1. **只读与可交易就绪应维持为不同状态。** `CtpSimNowNativeReadiness` 证明登录、所选 pair、连接代次、MD 订阅 ACK/首 tick 等只读事实；它返回 `td_trading_ready=False`，不代表交易就绪。之后的结算确认是独立 TD 查询，不应由 MD 行情、TCP 连通、登录成功或历史结算日推导。
2. **代码的结算查询门与 7×24 产品能力不匹配。** 7×24 页面公开承诺的是 API 测试；managed write policy 需要匹配当前交易日的一条结算确认读回。代码应在 7×24 结果缺失时清楚返回“该环境不提供结算 readiness”，并保持写计数为 0。不要把“无结算服务”映射为“确认已完成”。
3. **G7 的结算/资金断言不能在 7×24 下记 PASS。** 该环境沿用上一个交易日的钱和仓；可以用于连接与 API callback 诊断，但不能用其旧余额或位置推断本次成交完成结算。G7 的成交用例应在正常结算环境对同一动作前后观察的订单、成交、持仓和可用资金做差异核对。若官方/账户实际接口不提供其中某个字段，应将该项列为该环境不支持，并由 QA 明确决定该环境不能承担这条完整验收；不得假填字段。
4. **同一配置路径目标成立，但只能由操作者切换。** 正常结算环境的 MD/TD pair、账户和合约由操作者编辑同一 Git-ignored `config.yaml`。每次切换必须生成新 seal/scope；原先 7×24 的配置摘要、连接回执或批准不能复用。不得增加生产专用第二配置，也不得在代码里按地址识别或自动切到正常环境。
5. **正常环境仍没有 CTP API 可验证的强账户 fence/共同快照。** 本地 CTP 6.7.7 查询回调提供请求 ID 与 `bIsLast`，查询参数能带 Broker/Investor 和可选筛选；接口没有分页总数/快照版本或账户写锁。七个独立终包不证明无柜台漏行，也不证明它们取自同一时点。严格 F14 如继续要求跨主机、跨用户 writer fence 与共同账户状态，必须取得柜台/券商或账户级外部服务的独立证据。用户受控 gateway 可在独占凭据、网络 egress 封锁和单一持久命令 authority 被证实后证明写者排斥，但 gateway 自身仍不能制造 CTP 查询共同快照。

## 推荐的最小真实验收路径

以下是后续候选顺序；它不授权本次运行，也不改变 G0–G8 的独立前置。I11/I12 已消耗的 marker 不得复位或复用。

1. **配置与制品。** 操作者通过唯一受保护文件显式设置正常结算环境中一组成对 MD/TD 前置、账户、合约、交易所与 HedgeFlag。重新 seal 并记录脱敏的文件/registration/effective scope 摘要。先满足正式 base、CTP 和 `bt_api_py` parent wheel pin、installed RECORD/import origin、隔离解释器和父级信任根；目前 managed 第三件制品没有 code-owned pin，managed dispatch 路由也未登记。
2. **同一账户只读就绪。** 由新的受监督尝试按固定顺序建立 TD 与 MD 会话。TD 的身份、当前交易日、连接代次及 settlement-confirmation query 必须在正常环境得到匹配终态读回；MD 的登录、精确订阅 ACK、首个匹配 tick 与相同 TradingDay 必须正面观察。每个子进程用配置中同一 pair，不在登录失败后自动改选。只有 native `Join`/`Release` 关闭条件和 worker containment 均通过才进入执行阶段；当前真实 SDK 仍观察到 `Join` pending，供应商合同尚缺。
3. **先记录基线，再做两个不同的有界正例。** 在用户/QA 单独批准的测试窗口内，按已审风险上限做一笔可撤余量限价单并核对精确目标撤单终态；另做一笔允许成交的最小合规单并按本交易日 query 读回核对订单、成交、持仓和资金变化。若有部分成交，只能对剩余量请求撤单，并验证成交量、撤销量和剩余量守恒。任何未知 outcome 都冻结且不得重派。该次验收只能声称被测账户、环境、合约和窗口内的结果。
4. **恢复与报告。** 断线/强杀后须从唯一权威账本与同源 provider 状态完成精确恢复，不用新 client/第二 writer 或 cancel-all 掩盖未知结果。当前 G5/G6 账本接线、可信 native callback verifier、外部 writer fence 与共同快照仍未完成；这些门关闭前不应执行 G7。
5. **未来 production。** 在未来路线实现并独立接受之后，操作者仍只编辑同一 `config.yaml` 的 mode/preset 和 `ctp:` 账户/前置/合约字段；配置变化本身不会开放 live route。生产需另行完成制品、账户与会话、逐动作审批、risk/monitor、writer fence、恢复及真实账户证据。生产不能继承 SimNow 结论。

## 可直接实现的离线差异测试

- 用合成配置分别绑定“7×24/API-test”与“正常结算”选择，确保 route/environment 选择只能来自显式配置、两者均不靠地址/时段推断；不得读本地私密配置。
- fake `verify_settlement_confirmation` 返回无记录、空记录、多记录、非终态、旧 TradingDay、错账号、错 generation、超时、unsupported 时均拒绝写权限，且 `settlement_confirm`、order insert、order action 计数保持零。
- fake 正常结算记录只支持 offline contract 验证；标记为 `LOCAL_CONTRACT_PASS`，测试不得宣称 7×24 settlement-ready 或真实 provider PASS。
- 对没有外部 snapshot/fence 的正常环境继续断言 `CtpSimulationExecutionSession.submit_order()` / `cancel_order()` 的 native dispatch 计数为零；正常环境不放宽该门。
- 用临时合成配置测试从 `simulation/sandbox` 切换到未来 `live/managed_live_direct`：路径与 runner identity 不变、scope/receipt/approval 全部变化，当前默认 live profile 仍在 credential/SDK/network/runner 前拒绝。

公开来源内容取自 SimNow 官网公开产品/API 页面；本次没有访问账户服务。官网页面会更新，实际受理前应保存当日公开页面快照/版本化官方回函，且仍以真实账户对结算查询的正面回执决定该账户是否适合所选验收。
