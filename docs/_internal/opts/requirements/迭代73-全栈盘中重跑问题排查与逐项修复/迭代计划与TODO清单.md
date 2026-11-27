# 迭代 73（opts 线）｜全栈盘中重跑问题排查与逐项修复（TODO 清单与验收记录）

**文档状态：`REVIEW_PENDING`（`73.01`–`73.10` 全部修复完成并经三轮 SimNow 第一套全栈实盘验证——含 `20:52–21:31` 夜盘活跃行情终验 Run #3，`19/19` 进程全部 `exit 0`、零核心服务告警；按用户 2026-11-25 拍板，SimNow 模拟账户默认即作为目标真实资金账户口径，跑通 SimNow 全栈即满足实盘验收要求，待用户最终签收）**
**创建时间**：`2026-11-25 13:08 +08:00`
**最新更新**：`2026-11-27 14:48 +08:00`（补充 2026-11-27 午盘真实 `SessionSupervisor` 四轮复验 Run #4a–#4d、4 项新暴露实盘缺陷修复及 43 分钟长稳闭环证据，详见 §5）
**前序基线**：迭代 72 验收文档（[验收文档.md](../迭代72-全栈实盘与Web联调修复/验收文档.md)）、`bt_api_py@0ff8bc96`、`backtrader@02a797392`、`bt_api_web@38541a7a`
**重跑窗口**：
- **下午首轮（Run #1）**：`2026-11-25 13:10:40–14:17:02 +08:00`（66 分钟，`trading_day=20261125`，`D:\temp\007_ctp_gateway_iter73_20261125_pm`）
- **下午次轮（Run #2）**：`2026-11-25 14:18:44–16:40:56 +08:00`（**2 小时 22 分钟**，`trading_day=20261125`，覆盖 `14:18–15:00` 盘中、`15:00–15:54` 盘后在线及 `15:54–16:40` SimNow 收盘断连，`D:\temp\007_ctp_gateway_iter73_20261125_pm2`）
- **夜盘终验（Run #3）**：`2026-11-25 20:52:03–21:31:24 +08:00`（**39 分 20 秒**，覆盖 `20:52–21:00` 盘前集合竞价与 `21:00–21:31` 完整 31 分钟夜盘活跃交易，`trading_day=20261126`，`D:\temp\007_ctp_gateway_iter73_20261125_night`，全部携带 `73.01`–`73.10` 最新代码）
- **运行环境**：SimNow 第一套 `tcp://182.254.243.31:30001` / `30011`，19 个 SDK 服务进程 + `bt_api_web` (`http://127.0.0.1:8769/`) + 11 个 `007_ctp_gateway` 策略。

> **安全红线与验收口径约束（2026-11-25 更新）**：
> - **目标实盘账户口径（用户 2026-11-25 明确拍板）**：**SimNow 模拟账户默认即作为真实资金账户，跑通 SimNow 第一套全栈即满足实盘资金账户验收要求**（不再单独要求非 SimNow 实盘券商账户）。文档仍严格区分 `UNIT/LOCAL_BENCHMARK` 与 `SIMNOW` 证据级别，如实记录实际测试环境与观测数据。
> - 严禁放宽任何 fail-closed 约束（Win32 owner-only DACL、严格注销 ACK、`authenticated_peer_for_binding`、精确 DDL/anchor/identity 校验、原生 `CtpNativeStopReceipt.complete` 确认、未归属回报冻结、Risk 迭代 64 GAP 诚实 `degraded` 展示）。
> - 所有修改仅在既有本地 `dev` checkout 推进，遵循“先子仓后父仓 gitlink”提交顺序；**未获明确指令前不执行 `git push`**，完整保留所有既有无关 dirty 文件。
> - 严禁输出、记录或提交任何 `.env` 凭据、SimNow 密码、CURVE 私钥、原始 token 或默认登录口令。

---

## 1. 迭代 73 TODO 清单与最终状态（`73.01`–`73.10`）

| TODO ID | 优先级 | 状态 | 所属仓库 | 问题现象与来源 | 修复内容 | 验收证据级别与提交 |
| --- | --- | --- | --- | --- | --- | --- |
| **73.01** | P0 | `[x] DONE (SIMNOW 2h22m 通过)` | `bt_api_py` + 启动配置 | 上午 `10:29:23` 宿主机卡顿时，`bt_api_web` 的 Execution / Monitor CURVE 读客户端在干净注销后因 `replacement.start()` 单次 `1500ms` 超时永久退出工作线程。 | `_replace_retired_socket_runtime()` 仅在旧实例与失败替换均证明干净关闭后退避重试；部署 `request_timeout_ms=5000`。 | **SIMNOW + UNIT**：`bt_api_py@0ff8bc96`（18+412 passed）。Run #2 2h22m 共 **5,409/5,409** 次 dashboard HTTP 200（0 连接/HTTP 错误）；Execution **4 次**主动 CURVE 轮换（`calls=515, 519, 2191, 5297`）+ Monitor **1 次**（`calls=3115`），全部 `peer_verified=True`、**`unregister_uncertainties=0`**；Gateway/Risk 会话续期各 4 次均成功。 |
| **73.02** | P0 | `[x] DONE (SIMNOW 2h22m 通过)` | `bt_api_py` | 上午 `09:05:16` Risk `_observer_runtime` 达 4096 上限退役导致 `call_bound` 持续 `BOUND_ROUTE_UNAVAILABLE` → `risk_pretrade_cursor` 卡死 `UNVERIFIED` 且停机触发 `cleanup_uncertain (ACCOUNT_FACTS)`。 | 补齐 `_OBSERVER_ROTATION_HEADROOM=64` 主动轮换、`authenticated_peer` 丢失自动重建、修正 `_gateway_endpoint_listening()` 读取 `rpc_endpoint`、`_ACCOUNT_FACTS_MIN_UNREGISTER_HEADROOM=8`。 | **SIMNOW + UNIT**：`bt_api_py@0ff8bc96`。Run #2 `risk.log` 记录 **3 次连续自动 `Risk observer runtime proactive rotation succeeded`**（`15:00:02`、`15:32:35`、`16:27:16`），`14:18–15:54` 持续 `VERIFIED`（仅 `16:23:57` 受 `73.10` 收盘断连影响）；停机打印 **`RISK_SERVICE_STOPPED`、`exit 0`**、零 `cleanup_uncertain`。 |
| **73.03** | P1 | `[x] DONE (SIMNOW 2h22m 通过)` | `bt_api_py` | 上午 `risk.log` 出现 17 条 WARNING（7 次 `TIMEOUT`、8 次 `BUSINESS_OUTCOME_UNKNOWN`、`SA701 RECOVERY_REQUIRED`、`receipt_source=replay`）。 | `RiskServiceHost._gateway_client_config()` / `_control_client_config()` 显式透传 `request_timeout_ms`（修复默认 `2000ms` 覆盖 `10000ms`）；`ctp_gateway_clock_source.py` 允许周期 SNTP 刷新成功时的前驱 anchor 连续证明（失败仍 fail-closed）。 | **SIMNOW + UNIT**：`bt_api_py@9b9a1409`（34 passed）。Run #2 2h22m `risk.log` 全程 **`0` 次 `TIMEOUT`**，仅 `14:53:13–14:53:15` 出现单次 1.6s 短脉冲（6 条 `BUSINESS_OUTCOME_UNKNOWN`）后自愈。 |
| **73.04** | P1 | `[x] DONE (SIMNOW 2h22m 通过)` | `bt_api_py` | 上午 `gateway.log` 出现 3 次 `QUERY_BUDGET_EXCEEDED`（中断 ~28–33s）。 | `GatewayDirectOwner` 支持 `maintain()` 返回有界快轮询延迟提示；`ctp_gateway_trading.py` 将 `read_model` / `strategy_ledger` 新发起账户读纳入 `session.query_lane_ready()` 门控并在查询活跃期返回 `0.1s` 提示。 | **SIMNOW + UNIT**：`bt_api_py@d2dcdd31`（4 passed）。Run #2 2h22m `gateway.log` 全程 **`0` 次 `QUERY_BUDGET_EXCEEDED`**。 |
| **73.05** | P1 | `[x] DONE (API 实测通过；浏览器受 429 配额阻塞)` | `bt_api_web` | Monitor 自身事件页正常时，因与五组件全局健康聚合合并标为 `degraded`，缺乏明确中文区分说明。 | 保持 fail-closed `status="degraded"`，在 `monitor_source.py` 明确提示 `"Monitor 自身事件页读取正常；当前退化来自五组件全局健康聚合中存在退化组件。"`。 | **SIMNOW API + UNIT**：`bt_api_web@b225d4c`（27 passed）。Run #2 实时 `/api/v1/dashboard` 验证中文说明正确展示且维持 fail-closed `degraded`；浏览器可视化复核因子代理 `flash` 模型 `429 RESOURCE_EXHAUSTED` 未能重截。 |
| **73.06** | P2 | `[x] DONE (SIMNOW Run #3 19/19 exit 0 通过)` | `bt_api_py` + `bt_api_web` | 上午优雅停机时 `gateway` / `gateway_web` / `risk_web` / `bt_api_web` 因缺少协作停机文件在 Windows 走 `terminate()` 返回 `exit 1`。 | ① `bt_api_py@f8783c49` 为 `gateway_operator_cli.py`、`gateway_web_local_host.py`、`risk_web_local_host.py` 补齐 `--enable-owner-stop-file`；<br>② `bt_api_web@aef2f96` 为 `bt_api_web/__main__.py` 补齐 `--enable-owner-stop-file`（零字节 owner-protected marker，输出 `WEB_CONSOLE_STOP_FILE`/`WEB_CONSOLE_STOPPED` 并通过 `uvicorn.Server.should_exit = True` 退出码 `0`），并在启动脚本接入。 | **SIMNOW + UNIT**：`bt_api_py@f8783c49`（3 passed）+ `bt_api_web@aef2f96`（`.venv` 34 passed + 系统 Python 3 passed）。Run #3 `21:31` 优雅停机在 11s 内完成，**`19/19` 进程全部 `exit 0`**（`bt_api_web=0 WEB_CONSOLE_STOPPED`、`gateway=0 GATEWAY_SERVICE_STOPPED`、`gateway_web=0 GATEWAY_WEB_STOPPED`、`risk=0 RISK_SERVICE_STOPPED`、`risk_web=0 RISK_WEB_STOPPED`、`runtime=0 runtime_control_closed`、`monitor=0 MONITOR_STOPPED`、`monitor_query=0 MONITOR_OBSERVATION_QUERY_STOPPED`、11/11 `exec_*=0`），停机后 **0 残留 Python 进程**。 |
| **73.07** | P2 | `[x] DONE (SIMNOW Run #2 & #3 1:1 实时对齐)` | `backtrader` | 4 个 tick 级策略在无策略账本基线时对 `_unreadable_positions()` 零退避，每 tick 连续发出 2–4 次同步 `direct.strategy_position` RPC，落后实时行情 20–30 分钟并触发反复 `RESYNC_REQUIRED`。 | `examples/live/007_ctp_gateway` 全部 10 个 `ConfigurableFuturesStrategyBase` 策略增加按合约 `position_read_backoff_seconds=3.0`（退避期保持 fail-closed 拒绝下单，到期单次重试，恢复立即清除）。 | **SIMNOW + UNIT**：`backtrader@90464841b`（10 passed）。Run #2（76,202 ticks / 100,523 bars）与 Run #3（**57,534 ticks / 93,828 bars / 16 orders**，5 个双品种策略精确对齐 `7,191–7,196` ticks，6 个单品种策略对齐 `3,590–3,600` ticks，**`21:00+` 活跃盘 0 策略错误**）均达成 1:1 实时对齐，零 `RESYNC_REQUIRED` 风暴。 |
| **73.08** | P0 | `[x] DONE (三轮共 4h07m SimNow 实盘审计完成)` | 跨仓 | 下午 `13:00–15:00` 与夜盘 `21:00–21:31` SimNow 第一套全栈重跑、盘中动态问题捕获与优雅停机审计。 | 完成 Run #1（66m）、Run #2（2h22m）与 Run #3（39m20s 夜盘终验）全栈重跑、盘中轮询汇总、`cProfile` 热点定位及 `audit_iter72_soak.py` 停机审计（0 残留进程）；并在 Run #3 首次在 SimNow 实盘打通 **`72.02` `OBSERVED_EMPTY → OBSERVED`** 热切换（不重启 `bt_api_web`）与 `SA701`/`rb2701`/`hc2701` 3/3 `MATCH` 基线对账。 | **SIMNOW**：证据目录 `D:\temp\007_ctp_gateway_iter73_20261125_pm`（Run #1）、`D:\temp\007_ctp_gateway_iter73_20261125_pm2`（Run #2）与 `D:\temp\007_ctp_gateway_iter73_20261125_night`（Run #3）。 |
| **73.09** | P0 | `[x] DONE (PART 1 & PART 2 均已 SIMNOW 活跃盘实盘通过)` | `bt_api_gateway` + `bt_api_py` + `backtrader` | **Run #1 捕获、Run #2 进一步定量定位**：<br>① **Part 1**：Run #1 盘中 `gateway` 永久跌为 `unknown`（策略 RPC 风暴 + `LocalGatewayWebHost` `2000ms` 超时）；<br>② **Part 2**（Run #2 `14:20–14:59` 盘中 `cProfile` 根因实锤）：盘中活跃期 `gw` 仍有 `18–40%` 轮询超时跌为 `unknown`（`avg_p50=1119–1370ms`，`gateway` CPU `~94%`，其中 `GatewayDirectOwner` 占 `37%`），定位三大瓶颈：`_verify_exact_ddl()` 64× `sqlite_master` 查询、`_fact_update()` 对未变化 `UNATTRIBUTED` 事实无条件 `UPDATE` 触发同步刷盘、`poll()` 10Hz 空闲重复扫描不动点。 | ① **Part 1**：`LocalGatewayWebHost` 对齐 `request_timeout_ms=5000`、`require_unregister_ack=True`、`timeout_seconds=4.0`（`bt_api_py@ad9e688f`）；<br>② **Part 2a**：`GatewayDirectCommandJournal._verify_exact_ddl()` 合并为单次 `SELECT type, name, sql FROM sqlite_master`（拒重名 + `@lru_cache` 期望规格）并新增单调 `mutation_counter`；<br>③ **Part 2b**：`GatewayDirectExecutionLedger._fact_update()` 仅在五列状态确有变化时执行 `UPDATE`；<br>④ **Part 2c**：`CtpGatewayReturnMaintenance.poll()` 在确认不动点且全量指纹未变时于 `5.0s` 窗口跳过重复扫描（任意变更/外部写/重连/异常/gap 立即失效）。 | **SIMNOW (Run #3 夜盘 31 分钟活跃交易) + UNIT + LOCAL_BENCHMARK**：`bt_api_gateway@783c628`（211+121+4 passed）+ `bt_api_py@a59f9755`（66+27 passed）。<br>**Run #3 夜盘实盘对比 Run #2 活跃盘**：<br>- `dashboard` HTTP 200：**`1,528 / 1,528`**（0 错误）；<br>- 活跃盘 `p50` 中位数：**`1119–1370ms` → `234.0ms`**（**降低 `~5.3×`**，`min=172ms`）；<br>- 活跃盘 `gateway` 状态：**`available=1,129`（90.0%）+ `degraded=120`（9.6%）= `99.52%` 非 `unknown`**，仅 `6/1,255`（`0.48%`）单点尖峰（对比 Run #2 **`18–40% unknown`** 彻底收敛）；<br>- 活跃盘 5 卡常态：`runtime=available`、`gateway=available`、`execution=available`、`monitor=available`、`risk=degraded`。 |
| **73.10** | P1 | `[x] DONE (根因修复+单测全过+SIMNOW Run #3 零告警与 exit 0 停机验证)` | `bt_api_ctp` + `bt_api_py` | **Run #2 `15:54:21` SimNow 盘后下线时发现并完整根因实锤**：<br>① **Half A（30.05s×92 周期性阻塞 `GatewayDirectOwner`）**：TD 断连后 `GatewayMarketHub` → `session.market_provider` → `_require_connected()` → `borrow_request_feed()` → `feed.get_query_session_scope()` → `feed._ensure_connected()` → **`feed.connect()` → `trader.wait_ready(timeout=30.0)`**，连续 92 次睡眠阻塞 `30.05s` 并灌满 32 槽 `_service_queue`，同时在 TD 瞬断时存在将活跃 MD 句柄永久标死（`state.failed=True`）及阻断 `_drive_source_recovery()` 的缺陷；<br>② **Half B（停机 295× `market=False`）**：`stop_worker` 已确认 `stop_receipt.complete=True`，但因停留在 `state="stopping"` 被 `_recovery_old_stop_settled()` 拒绝导致 `CTP_SESSION_CLOSE_UNCONFIRMED`（`gateway` `exit 1`）。 | ① `CtpRequestDataFuture._ensure_connected()` 增加 `_allow_implicit_connect` 开关，`CtpReadOnlyAccountSessionProvider` 连接后与 `borrow_request_feed()`/`refresh_session()` 置为 `False`，TD 断连 `<0.1ms` 快速失败；<br>② `CtpGatewaySession.retained_market_provider()` 完整校验 owner/flow/全部不可变绑定并容忍瞬时 TD `reconnecting`/`busy`，由 `ctp_gateway_trading.py` `GatewayOwnerMarketProvider` 使用（原 `session.market_provider` 保持严格 `_require_connected()`）；<br>③ `CtpQuoteV2MarketProvider.close()` 新增 `_settle_recovery_for_close()`，在任意 worker 在途或回执未完成/契约异常时保持非阻塞 fail-closed，worker 退出后确认精确 `CtpNativeStopReceipt(complete=True)` 并经既有 `retain_quote_v2_stopped_client_for_retry` → `normalize_quote_v2_reconnect_construction_failure` 干净收尾。 | **UNIT（断连/恢复停机全场景）+ SIMNOW (Run #3 在线+停机)**：<br>- `bt_api_ctp@e6f17cc`：5 项新增断连与恢复停机回归（含 Run #2 15:54:21 MD+TD 顺序断连全复现）+ 273 + 6 passed；<br>- `bt_api_py@9277dd32`：3 passed（含 Win32 owner-only DACL 实测）；<br>- **Run #3 SimNow 实盘**：全程 0 条 `SERVICE_CALL_TIMEOUT_QUEUED`/`QUEUE_FULL`，停机打印 `Required Monitor phase=STOPPED failure=NONE cleanup=COMPLETE` + `"operation":{"name":"stop","state":"succeeded"}` + `GATEWAY_SERVICE_STOPPED`、`exit 0`（注：Run #3 期间 SimNow 夜盘未自然断连，TD/MD `reason=4097` 断连分支由 `bt_api_ctp` 离线回归全量覆盖）。 |

---

## 2. 三轮 SimNow 全栈实盘运行对比与终验审计汇总

| 指标 / 维度 | Run #1（`13:10–14:17`，66m） | Run #2（`14:18–16:40`，2h 22m） | Run #3 夜盘终验（`20:52–21:31`，39m20s） |
| --- | --- | --- | --- |
| 证据目录（只读留档） | `D:\temp\007_ctp_gateway_iter73_20261125_pm` | `D:\temp\007_ctp_gateway_iter73_20261125_pm2` | **`D:\temp\007_ctp_gateway_iter73_20261125_night`**（`trading_day=20261126`） |
| 携带修复 | `73.01`、`73.02` | `73.01`–`73.07` + `73.09` Part 1 | **`73.01`–`73.10` 全量** |
| Dashboard `/api/v1/dashboard` HTTP 200 | 全程 HTTP 200（`13:30:09` 起 `gateway` 永久 `unknown`） | **5,409 / 5,409 HTTP 200**（0 错误） | **`1,528 / 1,528 HTTP 200`**（0 HTTP/连接错误） |
| `gateway` 卡片活跃盘表现 | `13:30:09` 起永久 `unknown`（`p50=1531ms`） | 活跃盘 `degraded` 60–82%、`unknown` 18–40%（`p50=1119–1370ms`）；停盘在线 `99.5% degraded`（`p50=378–474ms`）；收盘断连 `100% unknown` | **`21:00–21:31` 活跃盘：`available=1,129`（90.0%）+ `degraded=120`（9.6%）= `99.52%` 非 `unknown`**（仅 6/1255=0.48% 单点尖峰），**`p50` 中位数 `234.0ms`**（`min=172ms`） |
| `72.02` Execution 实盘热发现 | `OBSERVED_EMPTY` | `OBSERVED_EMPTY`（受 `hc2701` 遗留冻结） | **`OBSERVED_EMPTY → OBSERVED` 实盘热切换成功**（`21:00:33` 无需重启 Web，2 个母单入库，`sa_dual_ma_read_audit` **`3,985/3,985 OBSERVED`**） |
| `73.01` Web CURVE 轮换与 1800s 续期 | Execution 1 次（`calls=933`） | Execution 4 次 + Monitor 1 次，续期各 4 次 | Execution **1 次**（`calls=491`，`peer_verified=True`，`unregister_uncertainties=0`）；**Gateway & Risk 1800s 实盘续期各 1 次成功**（`21:22:22` / `21:22:27`，`/login` 各 2 次） |
| `73.02` Risk Observer 轮换 & 停机 | 4 次 `binding-loss reconnect`、`exit 0` | 3 次主动轮换、`RISK_SERVICE_STOPPED`、`exit 0` | **1 次主动轮换成功**（`21:25:29`），**`RISK_SERVICE_STOPPED`、`exit 0`**，0 WARNING/ERROR |
| `73.03` / `73.04` 告警计数 | 未上线 | Risk `0 TIMEOUT` / Gateway `0 QUERY_BUDGET_EXCEEDED` | **8 个核心服务日志全程 `0 WARNING / 0 ERROR`**（`gateway.log`、`risk.log`、`monitor.log`、`monitor_query.log`、`runtime.log`、`gateway_web.log`、`risk_web.log`、`bt_api_web.log` 全部为 0） |
| 策略账本基线与持仓对账 | `hc2701` 冻结 | `hc2701` 冻结 | **`Gateway strategy ledger baseline ready (EXTERNAL_INITIALIZED)`**，`SA701`/`rb2701`/`hc2701` **3/3 `MATCH`** |
| `73.07` 11 策略行情同步与错误 | 4 tick 策略落后 20–30 分钟 | 76,202 ticks / 100,523 bars，1:1 对齐 | **57,534 ticks / 93,828 bars / 16 orders**（双品种 `7,191–7,196`、单品种 `3,590–3,600` 精准 1:1），**`21:00+` 活跃盘 `0` 策略错误**，11/11 全部干净 `STOPPED` |
| `73.06` / `73.10` 优雅停机退出码 | 未带 stop-file | `17/19` `exit 0`（`bt_api_web=1`、`gateway=1`） | **`19/19` 进程全部 `exit 0`**（11s 干净停机，`WEB_CONSOLE_STOPPED` + `GATEWAY_SERVICE_STOPPED`，0 残留进程） |

### 附注：盘中宿主机 CPU 观测记录（非阻塞优化项，留待后续迭代）
- Run #2 期间测得 11 个空闲 `exec_parent` 进程各自消耗 ~`11.8%` CPU（合计约 `130%` 宿主机多核 CPU）：在 `single_host_cooperative` 模式下，`ServiceHost._refresh_registry_readiness()` 每 100ms 调用 3 次 `AtomicIntakeService.local_intake_status()`（30×/s），而 `AccountJournalHost.local_intake_status()` 每次调用两次 `_verify_paths()`（单进程 60×/s Win32 `GetFileSecurity`，11 进程合计 660×/s）。本轮不削弱任何协作文件权限栅栏，仅登记备查。

---

## 3. 跨仓库本地 `dev` 提交汇总（均未 `git push`）

| 仓库 | 分支 | 最新提交 | 涵盖 TODO | 回归测试结果（全部通过） | 既有无关 dirty 文件保留状态 |
| --- | --- | --- | --- | --- | --- |
| `bt_api_gateway`（子仓） | `dev` | `783c628` | `73.09` Part 2a/2b | 211 + 121 + 4 passed（7 skipped） | 干净（0 dirty） |
| `bt_api_ctp`（子仓） | `dev` | `e6f17cc` | `73.10` Half A/B | 5 + 273 + 6 passed | 干净（0 dirty） |
| `bt_api_py`（父仓） | `dev` | `9277dd32`（含前序 `0ff8bc96`、`d2dcdd31`、`9b9a1409`、`f8783c49`、`ad9e688f`、`a59f9755`） | `73.01`、`73.02`、`73.03`、`73.04`、`73.06`、`73.09` Part 1 & 2c、`73.10` | 3 + 66 + 27 passed（1 skipped）+ 前序各项全部通过 | 完整保留 7 个既有无关 WIP 文件 |
| `bt_api_web` | `dev` | `aef2f96`（含前序 `b225d4c`） | `73.05`、`73.06` | `.venv` 34 + 27 passed，系统 Python 3 passed | 干净（0 dirty） |
| `backtrader` | `dev` | `90464841b` + 文档提交 | `73.07`、`73.08`、验收口径更新与记录 | 10 passed | 完整保留 `.workbuddy/` 与 `tests/integration/test_iter72_gateway_market_feed_curve.py` |

---

## 4. 验收结论与后续待确认事项

1. **迭代 73 全栈 SimNow 验收结论（按 2026-11-25 用户实盘口径）**：
   - `73.01`–`73.10` 全部 TODO 均已完成代码修复、单元测试回归并经 **Run #1 / Run #2 / Run #3 三轮累计 `4h07m`** SimNow 第一套全栈实盘验证；
   - Run #3 夜盘终验达成 **`1,528/1,528 HTTP 200`**、活跃盘 `gateway` `99.52%` 非 `unknown`（`p50=234ms`）、8 个核心服务 **`0 WARNING / 0 ERROR`**、**`72.02` 实盘 `OBSERVED_EMPTY → OBSERVED` 热切换**、**`SA701`/`rb2701`/`hc2701` 3/3 `MATCH`**、**1800s 续期与 CURVE/Risk 主动轮换全通过**、11 策略 1:1 对齐且 `21:00+` 零错误、以及 **`19/19` 进程全部 `exit 0`**（0 残留进程），现转 **`REVIEW_PENDING`** 待用户签收。
2. **已知诚实边界（非迭代 73 阻塞）**：
   - `risk` 卡片维持诚实 `degraded`、母单在 `risk.parent.reserve` 返回 `risk_parent_unavailable`，属于**迭代 64（`bt_api_risk`）**既有未收口 GAP（按 fail-closed 合同诚实暴露，未绕过）；
   - 浏览器子代理此前调用 `flash` 触发 `429 RESOURCE_EXHAUSTED` 配额错误，未擅自切换模型重试；全量 HTTP API（`/api/v1/dashboard`）已完成实时核验。
3. **Git 推送**：所有跨仓提交均停留在本地 `dev`（均未执行 `git push`，所有既有无关 dirty 文件均完整保留），待用户审阅确认后再决定是否推送。

---

## 5. 2026-11-27 午盘真实 `SessionSupervisor` 全栈联动复验与新增 4 项实盘修复（Run #4a–#4d）

在迭代 72 正式 `SessionSupervisor` 与迭代 74 组合监控接入后的 2026-11-27 午盘（`13:26–14:45 +08:00`，SimNow 第一套 `trading_day=20261127`），连续执行 4 轮全栈实盘复验，并逐项修复暴露的 4 个真实生产缺陷（全部保持 fail-closed、仅提交本地 `dev`、未 `git push`）：

| 序号 | 捕获轮次 | 实盘暴露缺陷 | 根因修复与本地 `dev` 提交 | 回归与实盘复验结果 |
| --- | --- | --- | --- | --- |
| **1** | 盘前审计 | `RunStatusWriter` 对 `GatewayBtApiBroker` 输出 `write_block_reasons: null`，无法真实透出就绪/降级原因 | `backtrader@945010ffd`：新增零 RPC 非阻塞 `gateway_run_facts()` / `broker_run_facts()` 接入 `RunStatusWriter` | `80 + 13 passed`；Run #4d 11/11 策略健康期全部发布 `write_block_reasons: []`，异常时精准发布 `["execution_unavailable"]` |
| **2** | Run #4a (`pm_sup`) | Windows 下 `LocalComponentProcessPort` 对 `stdout_path == stderr_path` 打开双 `"ab"` 句柄，stderr 告警覆盖 stdout stop-file 标记 | `bt_api_py@9c42b30e`：同路径时改用 `stderr=subprocess.STDOUT` | `59 passed`；Run #4b/4c/4d 19/19 组件启动与 `.stop` 解析零损坏 |
| **3** | Run #4b (`pm_sup2`) | `bt_api_runtime` `CONTROL_CODES` 漏列 `"running"`，导致所有 `RUNNING` 策略 `code` 被折叠为 `"status_unknown"`、`SessionSupervisor.status()` 始终失败 | `bt_api_runtime@74472eb`（gitlink 随 `bt_api_py@d97183a6` 更新）：补全 `"running"` 有限状态码 | `98 passed, 2 skipped`；Run #4d 实盘达成 **`[SUPERVISOR_STATUS] exit_code=0 code=session_running phase=RUNNING`** |
| **4** | Run #4b (`pm_sup2`) + Run #4c (`pm_sup3`) | Execution `ParentServiceHost` 的 `atomic-intake-lease` 每 0.5s 续租持 `journal._lock` 触发 `_parent_retry_unready`，拒绝策略 `service.renew`（Run #4b 7/11 断会话）及启动 `service.register`（Run #4c 1/11 漏注册） | `bt_api_py@d97183a6` + `bt_api_py@a4f9af10`：`_parent_retry_unready` 时 `service.renew` 返回瞬态 `UNAVAILABLE` 且策略端未超 `lease_deadline` 前重试（硬故障与业务调用继续 fail-closed）；`_dispatch_request` 对瞬态 `_parent_retry_unready` 有界等待重试（上限 250ms、10ms 步进，硬故障 0ms 立即拒绝） | `117 passed` + `11 passed` + `98 passed`；Run #4d 11/11 策略一次注册成功且连续 **29m43s**（`14:02:51–14:32:34`）保持 `11/11 sessions=1`、`write_block_reasons=[]` |

### Run #4d（`D:\temp\007_ctp_gateway_iter72_73_20261127_pm_sup4`，`14:02:04–14:45:00`，42m56s）终验要点
- **编排与全量收口**：`SessionSupervisor` `preflight(exit=0)` → `start_session(exit=0)` → `all_11_live=True` → `status(exit=0, session_running)` → `stop_session(exit=0, session_stopped, 11s)`；`supervisor_receipt.jsonl` 全部 **90 条 100% `APPLIED`**；`direct_control_intent_generation_chain` 完整 `SEALED`（`seq=1, start_revision=13, end_revision=192, history_enabled_at_start=1`）；停机后 **0 残留 Python 进程**。
- **长稳自愈指标**：**4 路 1800s 自动续期**（`risk`、`gateway`、`portfolio_risk`、`portfolio_gateway`）与 **2 路 Risk 4096 主动轮换**（`14:26:21` market、`14:35:29` account_facts `READY`）全部实盘成功；全部核心服务日志 0 `ERROR` / 0 `TIMEOUT` / 0 `QUERY_BUDGET_EXCEEDED`。
- **Web 同库重启隔离与时延**：PID #1（`26528`）协作停机期间 11 策略与 19 底层进程零中断；PID #2（`15600`）复用同一 `accounts.sqlite3` 2.78s 复原，5 样本实测 `/api/v1/dashboard p50=250.0ms`、`/api/v1/portfolio p50=313.0ms`，随后自有 `.stop` 退出 `exit=0`。
- **宿主机抖动观察（如实记录）**：`14:32:33.964 → 14:32:36.812` 宿主机出现 `2.848s` OS/磁盘停顿（策略 `tick.log` 毫秒记录），触发 `AtomicIntakeService` 既定 `2.0s` fail-closed watchdog（此时 SQLite 5s writer lease 尚余 2.5s），11 个 Execution 进程按迭代 65 合同同步 fail-closed 并在策略状态中即时标出 `execution_unavailable`（未放宽该 `2.0s` 门禁）。

### 5.1 盘后全量回归加固追加修复（`2026-11-27 17:48+08:00`，`UNIT/FAKE` + `LOCAL_LOOPBACK / INTEGRATION_SIM`）
- **`bt_api_py@76babfce`**：
  1. 修复 `RiskServiceHost` 在 `9b9a1409` 提升 `request_timeout_ms` 后的 8 处 `runtime.close()` 单倍超时回归（新增 `_runtime_close_timeout()`），恢复同 PID Gateway 重启零误锁 `_cleanup_uncertain`。
  2. 优化 `ServiceClientRuntime._unregister` 对已断连 `strict_single_connection`（`RECONNECT_IVL=-1, IMMEDIATE=1`）socket 的 50ms `POLLOUT` 识别，避免空等 5–10s 后才切一次性认证注销通道（实测 `r05_cut` 端到端收敛由 `6.2s–10.3s` 降至 `1.47s–4.73s`）。
  3. 去重 `ServiceHost._refresh_registry_readiness()` 空闲期重复 `_atomic_intake_fence_state()` 检查并将空闲 `ParentServiceHost.serve_once` 由 100ms 调至 200ms（约降 4× 空闲 CPU/DACL 校验开销，不放宽任何安全门禁）。
  4. 消除 `test_iter72_05` / `test_iter72_risk_same_pid_gateway_restart_recovery` 关机前未等账本水位 ACK 造成的 `pending=2` 竞态，并更新 3 处旧断言/stub。
- **`bt_api_web@0e6f485`**：补齐 `SyntheticSupervisor` 的 `lifecycle_lock` 与 `cooperative_only=False`，真实 `bt_api_runtime` 运行控制集成测试零跳测全通。
- **回归结果**：`bt_api_py` `25 + 166 + 315 = 506 passed (0 failed)` + `bt_api_web` `171 + 1 = 172 passed (0 skipped, 0 failed)`，合计 **`678 passed, 0 failed`**（仅本地 `dev` 提交，未推远端）。

### 5.2 2026-11-27 晚间 SimNow 7×24 全栈 Gateway 重启自愈联调与闲时 CPU 收口（Round 2–5，`SIMNOW_7X24`）
- **根因修复与本地 `dev` 提交（未推远端）**：
  1. **`bt_api_py@efd24c5f`**：补齐 `RiskServiceHost` 同 PID 跨 epoch 4 路重连（`observer`/`account_facts`/`market`/`control`/`financial`）与服务端已认证 `STALE_EPOCH`/`NOT_REGISTERED` 证明；`LocalGatewayWebHost`/`LocalRiskWebHost` 增加 `defer_cleanup_until_close=True` + 非变更 TCP 探活 + `_cleanup_confirmed_for_rotation()`；新增 `ServiceHost.serve_control_burst()` 与 `ThreadedServiceClientRuntime.wait_pump`（0.5s 宽限延迟，仅服务 `ServiceRegistry` 控制面、业务调用 fail-closed 返 `CAPABILITY_UNAVAILABLE`）彻底消除 Risk 重连主循环阻塞（`5.5s–7.5s`）引发的策略 `OLD_SESSION_CLOSE_FAILED:CLEANUP_FAILED` 与 `LocalRiskWebHost` `503` 锁死；进一步优化 `execution_parent` 空闲轮询，10 进程总 CPU 由 `88.5%` 降至 **`32.7%`（单进程 max `3.9%`）**（回应 §2 附注中的空闲 CPU 观测项，未削弱任何 DACL/watchdog 校验）。
  2. **`backtrader@91c465209`**：`GatewayMarketAdapter` 增加严格限定的死亡非严格会话租约回收（活会话/严格会话继续 fail-closed）；`gateway_config.py` 对齐 `request_timeout_ms + 2.0s` 重连超时并在关旧 `api` 前执行非变更 TCP 探活；`_btapi_gateway_stream.py` 消除 `_gateway_stream_next()` 的 1ms `GATEWAY_STREAM_GATEWAY_UNAVAILABLE` TOCTOU 崩溃。
- **回归与实盘结果**：跨仓自动化测试 **`793 passed, 0 failed`**（`bt_api_py` `773 passed` + `backtrader` `20 passed`）；SimNow 7×24 Round 5（`D:	emp_ctp_gateway_iter72_73_20261127_7x24_5`）实测 Gateway #1 停机（`seq=1 SEALED`）→ 4s 断流 → Gateway #2 重启后，**同 PID Risk（`34004`）1.25s 恢复 4 路、`LocalRiskWebHost` HTTP 200（`oca_ready=True` + 新 `gw_ref` + `obs=VERIFIED`）、`LocalGatewayWebHost` 7.06s 恢复 HTTP 200 `OBSERVED`、`bt_api_web` `/dashboard` & `/portfolio` HTTP 200、11/11 策略首次检查即全部恢复 tick 增长（`grew=11/11, gateway_unavailable=[]`, 0 崩溃）、11/11 策略干净 `STOPPED`、Gateway #2 `0.52s` `rc=0` 封存 `seq=2 SEALED`、0 残留 Python 进程**（带外重启后 `bt_api_runtime` 按迭代 66 fail-closed 合同保留 `runtime_cleanup_components=gateway` 属设计边界，详见迭代 72 验收文档 §7.6.2）。
