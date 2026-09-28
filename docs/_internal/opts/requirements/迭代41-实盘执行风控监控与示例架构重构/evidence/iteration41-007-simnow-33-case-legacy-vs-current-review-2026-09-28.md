# 007 SimNow penetration：33 案例新旧行为与真实通过条件复审

审查日期：2026-09-28（UTC+8）  
范围：`examples/007_ctp/live_certification/simnow_penetration/cases/<ID>/<ID>_strategy.py`、对应旧版 `cases/<ID>_*.py`、案例 `run.py`、`managed_case_entry.py` 与共同只读策略/结果契约。仅静态读取源码；没有读取 `config.yaml`、`secrets.yaml` 或任何凭据，没有导入/运行案例，没有调用 SDK、原生代码、Provider 或网络。

## 结论先行

- 当前 33 个案例目录里的 `run.py` 都只是把案例 ID 和自身路径交给 `managed_case_entry.main`；它会对配置正确的案例也返回 `managed_ctp_certification_not_registered` / `BLOCKED`，并输出 network/order_write 计数为 0。当前路径没有案例执行器，也没有报单权限。参见 `cases/T01/run.py:1-13`、`managed_case_entry.py:257-289`；其余 `run.py` 是同类薄包装。
- 33 个新策略文件是场景计划和被动证据观察器的构造入口。计划里写“submit/cancel/observe”，不代表这些模块会执行这些动作。构造器需要外部注入的 plan/scope/authenticator 或 typed adapter；共同只读策略快照把 `certification_pass=False`、`dispatch_permitted=False` 固定下来（`common/read_only_case_strategy.py:233-360`）。共同结果层也说明可信的事后对账 adapter 尚未配置（`common/result.py:18-19,152-155,234`）。
- 旧平铺脚本里确有真实风格的 `buy/sell/cancel/batch_cancel` 调用，但它们没有被新目录的 `run.py` 调用。多份旧脚本在下单前还会调用 `ensure_ctp_trading_admission`，因此旧源码中的策略体不是当前可用的真实写通道。不能把旧脚本的本地 `PASS` 分支、合成证据或离线测试当作 SimNow 认证通过。
- 旧结果分支多处把“本地请求事件”“监控计数”“本地停止/拒绝”当作成功；常见缺口是缺少同一 request/order ref 的原生回报、独立账户快照、终态订单查询和可信来源认证。下表逐案指出。

## 逐案例清单

“新计划”描述目标所需动作；“旧脚本实际”描述静态代码中实际尝试/接受的行为。所有“外部证据”均要求由真实受控运行产生，不能用测试夹具或 caller 自报事件替代。

| 案例 | 行为类别与新策略目标 | 旧平铺脚本实际行为及差距 | 真实通过不可缺的证据 / 外部条件 |
|---|---|---|---|
| **B01** | 行情 + 多笔开仓 + 部分成交 + 批量撤单。新计划要求每笔真实部分成交、剩余量、逐单批撤回报和最终对账。 | 旧脚本提交多笔订单后批量撤活单；`pass` 只看至少 3 条 cancel request/submitted 事件，没证明发生过部分成交，也没逐单核对剩余量和最终状态（`B01_batch_cancel_partial.py:91-137`）。 | 可成交行情、允许的最小订单预算；原生部分成交数量/交易所委托号；按剩余量发出的撤单、逐单撤单终态；成交与订单最终查询一致。部分成交时机不能由自动化凭空保证。 |
| **B02** | 行情 + 多笔已受理且仍挂单 + 批量撤单。 | 旧脚本尝试批撤，但以 3 条 `order_cancel_request` 计数即可 `pass`；不要求之前每笔被 Provider 接受、仍在挂单，也不核对撤单响应/终态（`B02_batch_cancel_pending.py:95-137`）。 | 至少多笔真实 working orders；先有原生受理和当前挂单查询，再批撤；逐单撤单确认、成交竞态处理及撤后空挂单/持仓查询。 |
| **C01** | 只读认证/登录：新计划要求原生认证与登录回调、请求 ID/ErrorID、捕获次序、FrontID/SessionID/TradingDay 和干净退出。 | 旧脚本检查 Store connected 并找到 `store_auth_success` 就通过；没有要求成功 login 回调或把登录 session 字段绑定到本次认证请求（`C01_connect_and_login.py:45-90`）。 | 真实 TD 登录成功；认证/登录原生回调及 request ID、ErrorID、FrontID、SessionID、TradingDay、账户范围，清洁断开；独立来源确认且全程零报撤单。 |
| **E01** | 报单 + 柜台资金不足。新计划要求先记录资金与风险条件，获得账户所有者批准，再采集真正的 counter rejection 并对账。 | 旧脚本有报单/撤单清理，但将任何带数字 ErrorID 或错误文本含 `CTP` 的远端拒单归为有效 counter error，最后只要存在远端拒单且未完成就 `pass`；未证明原因是资金不足（`E01_insufficient_funds.py:41-80,193-220`）。 | 同账户资金/可用保证金前快照、批准过的受限测试条件、与请求绑定的柜台资金不足 ErrorID/消息、请求回执以及最终订单/成交/资金对账。真实资金边界须由账户管理员/风控批准；不能安全地由测试自动造出。 |
| **E02** | 读持仓 + 平仓报单 + 柜台持仓不足。新计划要求按方向/开平和可平量核验前后快照。 | 旧脚本遇到已有多仓就跳过；在本地持仓为零时尝试卖出，任何通用远端拒绝且本地 position_size 为零即可 `pass`，不要求拒单真因为可平仓不足（`E02_insufficient_position.py:98-112,182-209`）。 | 原生账户持仓、方向、今昨仓/可平数量及请求开平标志；与请求关联的真实持仓不足拒单；最终持仓/委托/成交一致。需批准的无仓或不足仓条件；不能用净仓推算 CTP 今昨仓 bucket。 |
| **E03** | 读真实市场状态 + 报单 + 柜台市场状态拒绝。新计划只在真实市场状态自然满足条件时尝试，缺失就保持 pending。 | 旧脚本只启动 Store 后返回 `BLOCKED`，不发单；这是诚实的未覆盖，不是通过（`E03_market_state_error.py:27-44`）。 | 交易所/柜台的时间戳市场阶段或限制状态，与同一请求的 counter ErrorID/Msg 和最终委托状态关联。真实非交易阶段/合约限制由市场自然提供；禁止合成。 |
| **EM01** | 外部账户权限变更 + 受控报单 + 权限恢复。 | 旧脚本调用 `broker.disable_trading`（若有）然后在订单被本地标为 Rejected 时通过；没有管理员撤销账户权限的审计证据，也没证明拒绝来自柜台权限（`EM01_restrict_trading.py:63-89,96-107`）。 | 独立管理控制面撤销/恢复权限记录、账户/操作者/时间；同账户、同 session 的受控请求及原生权限拒绝；恢复后权限查询与账户状态。此控制只能由获授权管理员触发。 |
| **EM02** | 外部运维暂停策略 + 观察窗口内不再运行/报单。 | 旧脚本在第 2 bar 自己设置 `paused=True`、可选调用 `broker.pause_strategy`，再调用本地 `cerebro.runstop()`；只要本地标记成立就通过，没有外部暂停命令或暂停后出站写零的独立监控（`EM02_pause_strategy.py:62-99`）。 | 真实运行实例 ID、运维暂停命令/操作者审计、控制前后进程与回调状态；暂停后约定窗口的策略回调数、报单请求数为零并由独立监控核实。`runstop` 自调用不能替代外部暂停。 |
| **EM03** | 外部终止交易会话 + 断连识别 + 阻止后续委托。 | 旧脚本自己调用 `store.stop()`，随后 `is_connected=False` 就通过；这是本地有序停止，不能证明被运维从外部强制注销，更不能证明断线期间没有写请求（`EM03_force_logout.py:28-69`）。 | 运维/柜台强制注销的独立审计、原生断连回调和同 session 身份、未完成订单查询、断线期间出站拦截记录、恢复/最终对账。需有真实外部管理员动作。 |
| **L01** | 报单 + 成交 + 交易日志关联。新计划要求真实委托、成交及订单/成交查询按交易日、订单引用、成交 ID 对齐。 | 旧脚本确实尝试开仓和反向平仓；成功条件包含 `trade_execution`、trade.log 非空和本地 close_completed，强于“日志有一行”，但仍未要求可信 callback 身份/独立 Provider 查询对账（`L01_trade_info_log.py:89-160,168-220`）。 | 实际开/平成交回调和交易所 trade ID、order ref、TradingDay；TradeLogger 原始记录与账户/委托/成交查询一一对应，手续费/持仓变化一致；真实行情和账户资金/仓位许可。 |
| **L02** | 只读系统生命周期日志：新计划要求 PID、启动/退出、连接/ready 回调及原日志完整性关联。 | 旧脚本跑一 bar 后检查系统事件集合，能验证本地 logger 写了事件，但不能独立证明日志对应哪个实际 Provider session/进程（`L02_system_run_log.py:46-77`）。 | 真实受管进程 ID/时间边界、连接与 ready 的原生事件/会话身份、退出记录、未修改日志与完整性摘要；只读登录和至少一 bar/readiness。 |
| **L03** | 行情 + 报单/撤单 + 监控日志。新计划要求 monitor 请求记录与批准 request、Provider 回执、监控计数一致。 | 旧脚本做一次开单再撤单；只要 monitor.log 中出现 submit、cancel 或 monitoring_summary 任一种就通过，不证明本次 action 的关联或 Provider 受理（`L03_monitor_info_log.py:77-112`）。 | 当前会话的真实 monitor 原始记录、请求 ID/订单号、Provider 接受/撤单回调、summary 计数与最终订单/持仓查询一致。 |
| **L04** | 本地校验错误日志：不合 tick 的请求应在出站前拒绝。 | 旧脚本试图触发非法价格；error.log 只要含 `order_reject_local` 或通用 `order_rejected` 即通过，未关联精确输入/tick，也未证明无出站请求（`L04_error_info_log.py:75-110`）。 | 当前合约真实 tick metadata、精确请求价格、本地校验原因与 request ID、出站收据/Provider 侧零对应委托及最终空委托查询；必须证明发生在 dispatch 前。 |
| **M01** | 只读行情/连接就绪：新计划要求 `store_connected`/`store_ready` 绑定同一已认证 session，干净关闭。 | 旧脚本观察一 bar 并要求 system.log 有 connected/ready；没有把 auth/login/subscribe 的原生 identity 和 ready 绑定（`M01_connection_success_display.py:45-73`）。 | 认证登录、行情订阅及 ready 原生回调、同 session/front/trading day、真实 tick/时序、清洁关闭记录；不需要报单。 |
| **M02** | 外部真实 TD/MD transport 中断，再监督恢复/账户对账。 | 旧脚本将 `stop_on_exit=True` 视为断开，检查 `session_stopped` 就通过；有序本地 stop 不是 transport fault（`M02_disconnect_display.py:41-75`）。 | 监督故障注入或经批准的真实 transport 中断、原生 TD/MD 断连、display 事件对应；恢复后的 fresh 登录/订阅/ready 与账户/未完成订单查询。网络故障/恢复不可由合成日志替代。 |
| **M03** | 外部 transport 故障后自动重连。新计划要求旧/新 generation、fresh login/subscription/ready。 | 旧脚本手动 `store.stop()`、sleep 两秒、`store.start()`；只要重连调用成功就无条件 `pass`，不验证外部断网、自动重连或新 session/generation（`M03_reconnect_success.py:35-72`）。 | 独立确认的真实 transport loss；系统自动（非脚本手动重启）恢复，新的 connection generation/session/login/订阅/ready callbacks，断前/断后账户与委托 reconcile。 |
| **M04** | 行情 + 最多三笔受控开仓 + 撤单 + 报单计数核对。 | 旧脚本提交并撤单，但只要 monitor 中 submit 请求计数 ≥3 就通过；无需 monitoring_summary、Provider ack 或各订单终态（`M04_order_count_stats.py:79-124`）。 | 有效行情报价、三笔预算/权限、逐笔 request/订单引用和原生接受回执、真实 monitor 计数、撤单确认与最终空单/持仓查询。 |
| **M05** | 行情 + 最多三笔订单及撤单计数/原生撤单确认。 | 旧脚本只计 `order_cancel_request` ≥3 即通过；不核实撤单 ack、是否同一/有效挂单或最终状态（`M05_cancel_count_stats.py:79-117`）。 | 订单先原生 accepted/working；cancel 请求关联具体 order ref，原生撤单结果，计数与 monitor summary 对账、最终订单与持仓快照。 |
| **O01** | 重复开仓意图 + 风控重复检测。新计划要求同 repeat key、窗口、计数/来源请求及最终订单对账。 | 旧脚本反复下开仓单并计数；submit_count ≥3 即通过，没有检查 `risk_repeat_order_detected`，也未证明订单是同一意图或风控告警（`O01_repeat_open_order.py:79-110`）。 | 精确同一合约/账户/session/side/offset/价格或 intent key 的重复序列；有效风控配置与窗口、告警引用到各 request；被接受/阻断的原生结果、仓位/订单对账。必须批准重复尝试预算。 |
| **O02** | 真实持仓上的重复平仓意图。新计划明确先取 Provider 方向/offset bucket 可平量，逐笔不超仓，要求 repeat 风控证据。 | 旧脚本循环 `sell(offset="close")`，没有可信的开仓仓位前置确认；3 个 submit request 就通过，不要求 repeat 告警、正确今昨偏移或真实订单状态（`O02_repeat_close_order.py:79-110`）。 | 方向与 close-today/close-yesterday 分桶的原生持仓/可平量（标量净仓不足以证明 CTP closeability）；每笔请求和成交/拒单 offset 精确一致；同 scope repeat guard 只允许预期的一次 dispatch，并对账最终持仓。外部提供真实仓位。 |
| **O03** | 一笔真实挂单 + 对同一 order ref 重复撤单，第二次在 dispatch 前被风控拦截。 | 旧脚本看见 `risk_repeat_cancel_detected` 就通过，并报告计数/key；没有强制同一 order ref、至多一次真实 cancel dispatch，也没有最终空单条件（`O03_repeat_cancel_order.py:79-122`）。 | 一个被 Provider 接受且仍挂单的真实订单；两次相同 cancel intent/ref/window，monitor 告警绑定 request ID；native cancel dispatch 恰一次，第二次 blocked，最后订单查询空且 fills 对清。 |
| **T01** | 行情 + 一笔最小开仓 + Provider ack 后撤单及结清。 | 旧脚本只 assert 出现 `order_submit_request` 并通过；即使没有交易所 order ref/接受回调也可能算成功（`T01_open_order.py:93-128`）。 | 有效 tick/限价、审查过的写 admission/预算、出站回执、真实订单号和 accepted/working、撤单 ack、最后空挂单/无意外持仓查询。 |
| **T02** | 查询确认可平仓位 + 有界平仓 + 终态/前后持仓对账。 | 旧脚本出现 submit request 就通过；甚至本地或远端拒绝（例如无仓）也作为“平仓通路”通过（`T02_close_order.py:92-135`）。 | Provider 位置/方向/可平量及开平 offset，真实 submit/accept 或明确 scenario 预期，最终订单与持仓变化对账；本案计划要求真实 close path，泛拒绝不能算成功。 |
| **T03** | 一笔开仓委托后按真实订单号撤单，等待原生终态和查询。 | 旧脚本 assert 有 `order_cancel_request` 后通过，没有要求 provider cancel response 或 final order query（`T03_cancel_order.py:96-126`）。 | Provider accepted/working 的 order ref；同 ref cancel request/ack/status；成交竞态对账及最后 open-orders/position 查询。 |
| **TH01** | 仅配置/读取 submit threshold=5，正常行情 bar，采集 resolved runtime 值/summary；不下单。 | 旧脚本有一条危险降级：summary 存在时看 summary，但没有 summary 也因 logger 接受构造参数而无条件 `pass`（`TH01_order_threshold_setting.py:71-88`）。 | 实际加载配置的 runtime identity、有效阈值值和 monitor summary 原文，正常 session/bar；零报撤单。构造函数接受参数不是运行时设置证据。 |
| **TH02** | 配置阈值 2 + 两笔批准订单，需真正观测阈值告警并清理。 | 旧脚本有 warning **或仅 submit_count≥2** 即通过；后者绕过告警验证（`TH02_order_threshold_alert.py:101-122`）。 | 同运行的 resolved threshold=2、两条有效请求/原生状态、阈值事件的阈值/计数与请求引用对应；撤完后终态与空单查询。 |
| **TH03** | 只读 combined submit/cancel threshold=10 和 summary，不下单。 | 旧脚本接受 observer 参数并在 run 后直接 `pass`，没核对 summary/effective config（`TH03_total_threshold_setting.py:46-71`）。 | runtime-resolved combined threshold、真实 summary 中 submit/cancel 阈值字段、运行配置身份和零请求日志。 |
| **TH04** | 阈值 3 + 报单/撤单组合触发真正 combined 告警。 | 旧脚本在 total_ops≥3 **或** warning 时通过，操作计数满足就可能没有任何告警（`TH04_total_threshold_alert.py:100-114`）。 | 有效 threshold=3、独立数清实际 submit/cancel 请求、特定告警事件及计数一致、订单终态和无遗留挂单。 |
| **TH05** | 只读重复订单 threshold=3 与 repeat window 的 runtime 值/summary。 | 旧脚本接受 observer 参数后直接 `pass`，不证实值已生效，也不验证窗口（`TH05_repeat_threshold_setting.py:46-71`）。 | resolved threshold 与实际 repeat window、summary 原文、配置/会话身份、零订单活动。 |
| **TH06** | 重复同一开仓意图两次，阈值 2 告警并清理。 | 旧脚本要求出现 `risk_threshold_triggered` 与 `duplicate_order_threshold_reached` 两种日志事件，比其它旧告警用例更强；仍未绑定相同 intent/request refs、准确窗口及 Provider 状态（`TH06_repeat_threshold_alert.py:102-130`）。 | 同 scope/intent 的两次真实请求、threshold/window、事件与 request refs 相符；风控实际触发、至多预算范围内的 dispatch、取消/最终查询。 |
| **V01** | 合约 metadata 下选真实无效 instrument，本地拒绝必须先于 dispatch。 | 旧脚本做 CTP preflight 后尝试无效代码；日志中任意 `invalid_contract` 错误码就通过，未绑定本次请求/无出站事实（`V01_invalid_instrument.py:47-58,91-123`）。 | Runtime 当前合同 metadata/source、不可用 instrument 选择依据、精确 request ID 与本地 validator 命中、出站/Provider 无对应 order 的核对。需要真实 feed bar 只用于触发策略，不应把 invalid code 发到柜台。 |
| **V02** | 按实时 contract tick 构造步长不合法价格，本地拦截。 | 旧脚本基于限价构造非法 tick；只按 error.log 中 `invalid_price_tick` 文本计 PASS，没有绑定 metadata、请求输入及无 dispatch 证明（`V02_invalid_price_tick.py:47-58,89-123`）。 | 当前 contract tick 原始来源、精确价格算术、拒绝原因与 request ID、native/outbound 零匹配和最终空单查询。 |
| **V03** | 按 contract max order size 构造超限数量，本地拦截。 | 旧脚本按最大量构造请求；只按 `max_order_size_exceeded` error.log 事件计 PASS，没有证明来自当前 validator 或无出站（`V03_exceed_max_volume.py:47-58,89-125`）。 | 受审最大单量 metadata、请求 size 与校验结果精确关联、出站收据/Provider 零匹配及最终空单查询。仅在本地 validator 保证 dispatch 前拦截时可测。 |

## 33/33 真正通过的最短依赖链

这是逻辑上的最短链，不表示当前已经具备或允许执行：

1. **建立可信案例执行路径**：注册受审 runner；先验证 suite/case scope 与代码、配置摘要；获取被允许的 sealed runtime/account/session 范围。当前路径停在 `managed_ctp_certification_not_registered`，因此这一步未满足。
2. **提供真实观察面**：只读登录/账户/合约/持仓/挂单查询 + MD 订阅和带捕获时间的真实 tick；provider callbacks、查询结果、monitor/system/order/trade/error logs 必须按 account/session/day/generation 与 request/order/trade refs 关联，并有独立源认证/完整性证明。
3. **仅对需要写动作的案例启用逐案 admission**：批准的账户、合约、数量、方向/offset、价格带、次数和 stop 条件；实时风控检查、出站 receipt、原生回调、fill/cancel/reject 和最终查询必须闭环。读日志/阈值设置/本地校验类可不做真实写入，但仍需当前 runtime/行情/metadata 证据。
4. **逐案满足外部场景**：两种批撤的订单状态、真实部分成交；E01 资金不足、E02 方向/今昨可平量不足、E03 市场拒绝状态；EM01 权限审计、EM02 运维暂停、EM03 管理员注销；M02/M03 transport fault；TH 告警对应的配置/真实操作；O 系列重复保护条件。每项由实际 Provider、账户所有者、运维或风控侧产生，测试进程不能伪造。
5. **结束并封存对账**：所有 action 均有 native terminal result；最终 order/trade/position/account 查询与账本一致；没有遗留风险订单；保存原始证据、来源身份、完整性摘要和独立复核结论，之后才可能由已注册的 trusted post-reconciliation adapter 判定 PASS。

**不能由自动化自造的条件**：柜台认证/登录、真实交易日和行情 tick、原生委托/撤单/成交/拒绝回报及其 IDs、账户资金/方向和今昨仓、柜台交易权限与管理员审计、外部暂停/注销、真实 TD/MD 断网恢复、交易所时段/市场限制、柜台风控的拒绝决定、第三方/原始日志来源真实性。自动化可以安排时间、发起已批准的请求、收集并做一致性检查；不能通过造 JSON、改时间戳、手工设本地 flag 或合成事件满足这些事实。

## 适用边界

本报告是源码行为审查，不是账户/Provider 测试或风险放行意见。离线单测、假的 adapter、合成 observations 和旧版脚本的 `pass_result` 都不代表真实认证。当前应继续把 33 个案例标为未执行/`BLOCKED`，不能记录为 33/33 PASS。
