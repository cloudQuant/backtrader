# 迭代 73（opts 线）｜全栈盘中重跑问题排查与逐项修复（TODO 清单与验收记录）

**文档状态：`IN_PROGRESS / REVIEW_PENDING`（`73.01`–`73.08` 已获 SimNow 盘中全栈实盘证据；`73.09` Part 2 代码与本机真实库基准/单测已完成待下个交易时段 SimNow 复验；`73.10` 已定位待补单测与断连验证；真实资金账户继续保持 `NOT_RUN / NO-GO`）**
**创建时间**：`2026-11-25 13:08 +08:00`
**最新更新**：`2026-11-25 17:35 +08:00`
**前序基线**：迭代 72 验收文档（[验收文档.md](../迭代72-全栈实盘与Web联调修复/验收文档.md)）、`bt_api_py@0ff8bc96`、`backtrader@02a797392`、`bt_api_web@38541a7a`
**重跑窗口**：
- **下午首轮（Run #1）**：`2026-11-25 13:10:40–14:17:02 +08:00`（66 分钟，`D:\temp\007_ctp_gateway_iter73_20261125_pm`）
- **下午次轮（Run #2）**：`2026-11-25 14:18:44–16:40:56 +08:00`（**2 小时 22 分钟**，覆盖 `14:18–15:00` 盘中、`15:00–15:54` 盘后在线及 `15:54–16:40` SimNow 收盘断连，`D:\temp\007_ctp_gateway_iter73_20261125_pm2`）
- **运行环境**：SimNow 第一套 `tcp://182.254.243.31:30001` / `30011`，`trading_day=20261125`，19 个 SDK 服务进程 + `bt_api_web` (`http://127.0.0.1:8769/`) + 11 个 `007_ctp_gateway` 策略。

> **安全红线与证据分级约束**：
> - 严禁放宽任何 fail-closed 约束（Win32 owner-only DACL、严格注销 ACK、`authenticated_peer_for_binding`、精确 DDL/anchor/identity 校验、`unresolved-return:SHFE:hc2701` 冻结、Risk 迭代 64 GAP 诚实 `degraded` 展示）。
> - 所有修改仅在既有本地 `dev` checkout 推进，遵循“先子仓后父仓 gitlink”提交顺序；**未获明确指令前不执行 `git push`**，完整保留所有既有无关 dirty 文件。
> - 严格区分 `UNIT/LOCAL_BENCHMARK` 与 `SIMNOW` 证据级别；SimNow 模拟盘证据不证明真实资金账户可用，Gateway 真实账户继续保持 `NOT_RUN / NO-GO`。
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
| **73.06** | P2 | `[x] DONE (17/19 exit 0，余 2 项原因明确)` | `bt_api_py` | 上午优雅停机时 `gateway` / `gateway_web` / `risk_web` 因缺少协作停机文件在 Windows 走 `terminate()` 返回 `exit 1`。 | 为 `gateway_operator_cli.py`、`gateway_web_local_host.py`、`risk_web_local_host.py` 补齐 `--enable-owner-stop-file`（零字节 owner stop-file + `uvicorn.Server.should_exit = True`）。 | **SIMNOW + UNIT**：`bt_api_py@f8783c49`（3 passed）。Run #2 `16:40` 停机 **`17/19` 进程返回 `exit 0`**（`gateway_web=0 GATEWAY_WEB_STOPPED`、`risk_web=0 RISK_WEB_STOPPED`、`risk=0 RISK_SERVICE_STOPPED`、`runtime=0`、`monitor=0`、`monitor_query=0`、11/11 `exec_*=0`）；剩余 2 项：`bt_api_web=1`（uvicorn 进程无 stop-file，走 `terminate()`）与 `gateway=1`（已收到 stop-file 且完成 `Required Monitor COMPLETE` + `direct=True account=True`，仅因 `73.10` 收盘后断连导致 `market=False`）。 |
| **73.07** | P2 | `[x] DONE (SIMNOW 2h22m 1:1 实时对齐)` | `backtrader` | 4 个 tick 级策略在无策略账本基线时对 `_unreadable_positions()` 零退避，每 tick 连续发出 2–4 次同步 `direct.strategy_position` RPC，落后实时行情 20–30 分钟并触发反复 `RESYNC_REQUIRED`。 | `examples/live/007_ctp_gateway` 全部 10 个 `ConfigurableFuturesStrategyBase` 策略增加按合约 `position_read_backoff_seconds=3.0`（退避期保持 fail-closed 拒绝下单，到期单次重试，恢复立即清除）。 | **SIMNOW + UNIT**：`backtrader@90464841b`（10 passed）。Run #2 11/11 策略至 `15:15` 收盘共收 **76,202 ticks / 100,523 bars**（0 订单、0 成交），tick 策略与 5s bar 策略达成 **1:1 实时 tick 对齐**（`mixbroker_pair` **9,510** vs `mixbroker_5s_pair` **9,510**；`mixbroker_single` **4,799** vs `mixbroker_5s_single` **4,799**；`tickbroker_pair` **9,481** vs `tickbroker_5s_pair` **9,473**；`tickbroker_single` **4,783** vs `tickbroker_5s_single` **4,789**），零 `RESYNC_REQUIRED` 风暴。 |
| **73.08** | P0 | `[x] DONE (两轮共 3h28m SimNow 实盘审计完成)` | 跨仓 | 下午 `13:00–15:00` SimNow 第一套全栈重跑、盘中动态问题捕获与优雅停机审计。 | 完成 Run #1（66 分钟）与 Run #2（2 小时 22 分钟）全栈重跑、盘中轮询汇总、`cProfile` 热点定位及 `audit_iter72_soak.py` 停机审计（0 残留进程）。 | **SIMNOW**：证据目录 `D:\temp\007_ctp_gateway_iter73_20261125_pm`（Run #1）与 `D:\temp\007_ctp_gateway_iter73_20261125_pm2`（Run #2），成功捕获并推进 `73.07`、`73.09`、`73.10`。 |
| **73.09** | P0 | `[~] PART 1 已实盘验证；PART 2 代码+基准+单测完成（待下个交易时段 SimNow 复验）` | `bt_api_gateway` + `bt_api_py` + `backtrader` | **Run #1 捕获、Run #2 进一步定量定位**：<br>① **Part 1**（已实盘验证）：Run #1 盘中 `gateway` 永久跌为 `unknown`（策略 RPC 风暴 + `LocalGatewayWebHost` `2000ms` 超时）；<br>② **Part 2**（Run #2 `14:20–14:59` 盘中 `cProfile` 根因实锤）：盘中活跃期 `gw` 仍有 `18–40%` 轮询超时跌为 `unknown`（`avg_p50=1119–1370ms`，`gateway` CPU `~94%`，其中 `GatewayDirectOwner` 占 `37%`），而 `15:00` 停盘零 tick 后瞬间回升至 `99.5% degraded`（`avg_p50=378–474ms`）。在 Run #2 `orders.sqlite` 副本上 `cProfile` 定位三大直接瓶颈：<br>  (a) `_verify_exact_ddl()` 每次 `_transaction()` 执行 `64` 次 `sqlite_master` 查询 + `20` 次惰性 import（`5.99ms/txn`、`70+` SQL）；<br>  (b) `GatewayDirectExecutionLedger._fact_update()` 对未变化的 6 条 `UNATTRIBUTED` `hc2701` 事实无条件执行 `UPDATE` → 每次 `reconcile_pending()` 触发 WAL 脏页、`PRAGMA synchronous=FULL` 同步刷盘与 `dispatch_change_port` 通知（`37.38ms/tick`）；<br>  (c) `CtpGatewayReturnMaintenance.poll()` 在 10Hz 空闲 tick 上重复扫描同一批已达不动点的 `UNATTRIBUTED` 事实（单线程吃掉 `37.4%` CPU）。 | ① **Part 1**：`LocalGatewayWebHost` 对齐 `request_timeout_ms=5000`、`require_unregister_ack=True`、`timeout_seconds=4.0`（`bt_api_py@ad9e688f`）；<br>② **Part 2a（零放宽 DDL 优化 + 写计数）**：`GatewayDirectCommandJournal._verify_exact_ddl()` 合并为单次 `SELECT type, name, sql FROM sqlite_master`（拒重名 + `@lru_cache` 期望 DDL 规格，仍逐次校验活库全部对象与精确 SQL），并新增进程内单调 `mutation_counter`（`SELECT`-only 事务不递增，写/失败事务递增）；<br>③ **Part 2b（消除无变化 `UPDATE` 刷盘）**：`GatewayDirectExecutionLedger._fact_update()` 仅在五列状态确有变化时执行 `UPDATE`，`append_account_fact` 仍照常执行；<br>④ **Part 2c（有界空闲不动点快路径）**：`CtpGatewayReturnMaintenance.poll()` 在完成全量不动点扫描（`len(results) < 256` 且全部保持 `UNATTRIBUTED`）、无新回调且 `generation` / `mutation_counter` / `_storage_fingerprint()` / `_pending_cursor` 均未变化时，于 `5.0s` 安全窗口内跳过重复 `reconcile_pending` + `account_fact_health`（任何写入、外部修改、回调到达、重连、异常、gap 或安装 continuity witness 立即失效并保持 fail-closed）。 | **Part 1 (SIMNOW + UNIT)**：`bt_api_py@ad9e688f`（11 passed）+ `backtrader@90464841b`。<br>**Part 2 (UNIT + LOCAL_BENCHMARK on Run #2 DB copy，待 SimNow 活跃盘复验)**：`bt_api_gateway@783c628`（211+121+4 passed）+ `bt_api_py@a59f9755`（66+27 passed）。<br>**本机实测（Run #2 `orders.sqlite` 副本）**：<br>- `_transaction(read_only=True)`：`70+` SQL → **`9` SQL**（`_verify_exact_ddl` 降为 `0.19ms/call`）；<br>- 单次 `reconcile_pending + account_fact_health`：`37.38ms` → **`19.99ms`**，且无变化 `UPDATE=0`、`mc_delta=0`；<br>- 50 次连续 10Hz 空闲 `poll()`（5 秒窗口）：`1,869.00ms` → **`26.18ms`**（冷 1 次 `22.76ms` + 热 49 次 `0.0698ms/tick`，**owner CPU 降低 `71.4×`**，由 `37.4%` 降至 `0.52%`）。 |
| **73.10** | P1 | `[ ] OPEN / DIAGNOSED (盘后断连新发现，待补单测复现与下一轮断连验证)` | `bt_api_ctp` + `bt_api_py` | **Run #2 `15:54:21` SimNow 盘后下线时新发现**：<br>① `15:54:21.780` SimNow 关闭 MD 前置（`reason=4097`），`CtpQuoteV2MarketProvider` 触发 `_begin_source_recovery()`；`15:54:22.272` TD 前置断连（`reason=4097`），`15:54:22.284` `order_cut` 报 `SOURCE_OR_QUERY_FAILED`；<br>② `15:54:28.043` 起至 `16:40:25`（46 分钟），`GatewayDirectOwner` 队列阻塞（线程 `tid=40300` 处于 `Wait/UserRequest` 0% CPU），`gateway_required_monitor` 连续记录 `301× SERVICE_CALL_TIMEOUT_QUEUED` + `91× SERVICE_CALL_QUEUE_FULL`，导致 `bt_api_web` 中 `gateway` 100% `unknown`、11 策略在 `15:54–15:56` 记录 `DELAYED (OWNER_TIMEOUT_RUNNING/QUEUED)`、`risk_pretrade_cursor` 于 `16:23:57` 翻为 `UNVERIFIED`；<br>③ `16:40:26` 收到停机 stop-file 后 `Required Monitor` 干净停止、`direct=True` & `account=True` 正常关闭，但 **`market=False`** 在 15 秒内每 51ms 立即返回（295 次 `CTP Gateway session stop unconfirmed: market=False direct=True account=True` → `CTP_SESSION_CLOSE_UNCONFIRMED`，`gateway` 退出码 `1`），对应 `CtpQuoteV2MarketProvider.close()` 因 `_recovery_old_stop_settled(recovery)` 为 `False`（原 MD `Release()`/stop worker 在 SimNow 断连后未在 30s 内返回、恢复进入 `"abandoning"` 状态且未打诊断日志）而 fail-closed 拒绝释放。 | 待下一轮：① 离线单测复现 MD+TD 同时 `reason=4097` 断连后 `GatewayDirectOwner` 线程阻塞点与 `SERVICE_CALL_QUEUE_FULL` 链路；② 在不破坏“未确认原生停止前不得丢弃句柄” fail-closed 合同的前提下，补齐 `market_provider` 进入 `"abandoning"` 的有界诊断日志、评估断连期间 owner 队列不饿死机制及 MD 停机确认行为；③ 于夜盘/下午收盘断连窗口实测验证。 | **SIMNOW 实盘诊断证据**：Run #2 `gateway.log` L28–L496、`risk.log`、`audit_iter72_soak.py` 输出（未仓促合入未经验证的原生 CTP `Release()` 绕过）。 |

---

## 2. 下午两轮 SimNow 全栈实盘运行对比与审计汇总

| 指标 / 维度 | Run #1（`13:10:40–14:17:02`，66m） | Run #2（`14:18:44–16:40:56`，2h 22m） |
| --- | --- | --- |
| 证据目录（只读留档） | `D:\temp\007_ctp_gateway_iter73_20261125_pm` | `D:\temp\007_ctp_gateway_iter73_20261125_pm2` |
| 携带修复 | `73.01`、`73.02` | `73.01`–`73.07` + `73.09` Part 1 |
| Dashboard `/api/v1/dashboard` HTTP 200 | 全程 HTTP 200（`13:30:09` 起 `gateway` 永久 `unknown`） | **5,409 / 5,409 HTTP 200**（0 HTTP/连接错误） |
| `gateway` 卡片分时段表现 | `13:30:09` 起永久 `unknown`（`p50=1531ms`） | `14:20–14:59`（盘中活跃）：`degraded` 60–82%、`unknown` 18–40%（`p50=1119–1370ms` → 驱动 `73.09` Part 2）<br>`15:00–15:49`（停盘在线）：**`99.5% degraded`**（1961/1969，`p50=378–474ms`）<br>`15:54:21–16:35`（SimNow 下线）：100% `unknown`（驱动 `73.10`） |
| `73.01` Web CURVE 自动轮换 | Execution 1 次（`calls=933`），`unregister_uncertainties=0` | Execution **4 次**（`515/519/2191/5297`）+ Monitor **1 次**（`3115`），全部 `peer_verified=True`、**`unregister_uncertainties=0`** |
| `73.02` Risk Observer 主动轮换 & 停机 | 4 次 `binding-loss reconnect succeeded`，停机 `exit 0` | **3 次连续主动轮换成功**（`15:00:02`、`15:32:35`、`16:27:16`），停机 `RISK_SERVICE_STOPPED`、`exit 0`、0 `cleanup_uncertain` |
| `73.03` Risk `TIMEOUT` 告警 | 未上线 | **0 次 `TIMEOUT`**（仅 `14:53:13` 1.6s 单次 6 条 `BUSINESS_OUTCOME_UNKNOWN`） |
| `73.04` Gateway `QUERY_BUDGET_EXCEEDED` | 未上线 | **0 次** |
| `73.07` 11 策略行情同步与错误 | 4 个 tick 策略落后 20–30 分钟并触发 `RESYNC_REQUIRED` | **76,202 ticks / 100,523 bars**，0 订单/0 成交；tick vs 5s bar **1:1 实时对齐**；仅 1 条盘中错误（`tickbroker_pair` `14:33:30`），余 16 条均发生在 `15:54–15:56` SimNow 下线后（`73.10`）；零 `RESYNC_REQUIRED` 风暴 |
| `73.06` 优雅停机退出码 | `gateway`/`gateway_web`/`risk_web` 未带 stop-file | **`17/19` 进程 `exit 0`**（含 `gateway_web=0`、`risk_web=0`、`risk=0`、`runtime=0`、`monitor=0`、`monitor_query=0`、11/11 `exec_*=0`）；仅 `bt_api_web=1`（uvicorn 走 `terminate()`）与 `gateway=1`（`73.10` `market=False`）；停机后 0 残留进程 |

### 附注：盘中宿主机 CPU 观测记录（非阻塞优化项，留待后续迭代）
- Run #2 期间测得 11 个空闲 `exec_parent` 进程各自消耗 ~`11.8%` CPU（合计约 `130%` 宿主机多核 CPU）：在 `single_host_cooperative` 模式下，`ServiceHost._refresh_registry_readiness()` 每 100ms 调用 3 次 `AtomicIntakeService.local_intake_status()`（30×/s），而 `AccountJournalHost.local_intake_status()` 每次调用两次 `_verify_paths()`（单进程 60×/s Win32 `GetFileSecurity`，11 进程合计 660×/s）。本轮不削弱任何协作文件权限栅栏，仅登记备查。

---

## 3. 跨仓库本地 `dev` 提交汇总（均未 `git push`）

| 仓库 | 分支 | 最新提交 | 涵盖 TODO | 回归测试结果（全部通过） | 既有无关 dirty 文件保留状态 |
| --- | --- | --- | --- | --- | --- |
| `bt_api_gateway`（子仓） | `dev` | `783c628` | `73.09` Part 2a/2b | 211 + 121 + 4 passed（7 skipped） | 干净（0 dirty） |
| `bt_api_py`（父仓） | `dev` | `a59f9755`（含前序 `0ff8bc96`、`d2dcdd31`、`9b9a1409`、`f8783c49`、`ad9e688f`） | `73.01`、`73.02`、`73.03`、`73.04`、`73.06`、`73.09` Part 1 & 2c | 66 + 27 passed（1 skipped）+ 前序各项全部通过 | 完整保留 7 个既有无关 WIP 文件 |
| `bt_api_web` | `dev` | `b225d4c` | `73.05` | 27 passed | 干净（0 dirty） |
| `backtrader` | `dev` | `90464841b` + 本文档提交 | `73.07`、`73.08`、文档验收记录 | 10 passed | 完整保留 `.workbuddy/` 与 `tests/integration/test_iter72_gateway_market_feed_curve.py` |

---

## 4. 遗留项与下一步建议

1. **视觉浏览器复核**：Run #2 期间浏览器子代理调用 `flash` 模型触发 `429 RESOURCE_EXHAUSTED` 配额错误，未自动切换模型或重试；HTTP API（`/api/v1/dashboard`）已完成全量验证。如需页面截图复核，可在配额恢复或指定模型后再跑。
2. **`73.09` Part 2 活跃盘 SimNow 复验**：建议在下一交易时段（如 `21:00+` 夜盘）重跑确认盘中活跃期 `gateway` 卡片保持 `degraded` 且 `p50` 显著回落、无 `unknown` 抖动。
3. **`73.10` 盘后/断连复现与修复**：补齐 MD+TD 同时 `reason=4097` 离线单测复现，解决断连后 `GatewayDirectOwner` 队列阻塞与 `market=False` 停机诊断/处理，再进行断连实测。
4. **Git 推送与真实账户红线**：所有提交均停留在本地 `dev`（未 `git push`），待用户审阅确认后再决定是否推送；Gateway 真实资金账户在用户签收并另行授权前继续保持 **`NOT_RUN / NO-GO`**。
