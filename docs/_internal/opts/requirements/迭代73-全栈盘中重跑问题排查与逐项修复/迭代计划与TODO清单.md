# 迭代 73（opts 线）｜全栈盘中重跑问题排查与逐项修复（TODO 清单）

**文档状态：`IN_PROGRESS`（真实资金账户继续保持 `NOT_RUN / NO-GO`）**
**创建时间**：`2026-11-25 13:08 +08:00`
**前序基线**：迭代 72 验收文档（[验收文档.md](../迭代72-全栈实盘与Web联调修复/验收文档.md)）、`bt_api_py@0ff8bc96`、`backtrader@02a797392`、`bt_api_web@38541a7a`
**重跑窗口**：`2026-11-25 13:00–15:00 +08:00`（SimNow 第一套 `tcp://182.254.243.31:30001` / `30011`，`trading_day=20261125`）

> **安全红线与工作约束**：
> - 严禁放宽任何 fail-closed 约束（Win32 owner-only DACL、严格注销 ACK、`authenticated_peer_for_binding`、未归属成交冻结、Risk 迭代 64 GAP 诚实 `degraded` 展示）。
> - 所有修改仅在既有本地 `dev` checkout 推进，逐项修复并补回归测试后小步提交；未获明确指令前不执行 `git push`，完整保留所有既有无关 dirty 文件。
> - 严禁输出、记录或提交任何 `.env` 凭据、SimNow 密码、CURVE 私钥、原始 token 或默认登录口令。

---

## 1. 迭代 73 TODO 清单（按优先级逐项推进，盘中动态补充）

| TODO ID | 优先级 | 状态 | 所属仓库 | 问题现象与来源 | 修复 / 验证目标 | 验收证据与提交 |
| --- | --- | --- | --- | --- | --- | --- |
| **73.01** | P0 | `[~] 待盘中复验` | `bt_api_py` + Web 部署配置 | 上午 `10:29:23` 宿主机 ~5s 卡顿时，`bt_api_web` 的 Execution / Monitor CURVE 读客户端在干净注销后因 `replacement.start()` 单次 `1500ms` 超时永久退出工作线程（`/execution` 落入 `UNKNOWN`，`/monitor` 报事件页不可用）。 | ① `bt_api_py@0ff8bc96` 已修 `_replace_retired_socket_runtime()`（仅在旧实例与失败替换均证明干净关闭后退避重试）；② 启动配置 `request_timeout_ms` 调整为 `5000ms`；③ 下午重跑全程验证 `/execution` 与 `/monitor` 事件页跨多次 CURVE 轮换与抖动持续恢复、零永久死亡。 | 代码+单测已提交 `bt_api_py@0ff8bc96`（18 passed）；待下午 SimNow 实盘复验 |
| **73.02** | P0 | `[~] 待盘中复验` | `bt_api_py` | 上午 `09:05:16`（启动约 19 分钟）Risk `_observer_runtime` 达 4096 消息上限退役，非 strict socket 换新导致 `call_bound` 持续 `BOUND_ROUTE_UNAVAILABLE` → `risk_pretrade_cursor` 卡死 `UNVERIFIED` 长达 2 小时，连带阻塞 `_account_facts_runtime` 主动轮换并在 `11:17:35` 停机触发 `cleanup_uncertain (ACCOUNT_FACTS)`。 | ① `bt_api_py@0ff8bc96` 已补齐 `_OBSERVER_ROTATION_HEADROOM=64` 主动轮换、`authenticated_peer` 丢失自动重建、`_gateway_endpoint_listening()` 修正读取 `rpc_endpoint` 与 `_ACCOUNT_FACTS_MIN_UNREGISTER_HEADROOM=8`；② 下午重跑跨越 ≥3 个 19 分钟周期，实测 `/risk` 持续显示 `来源连续性: 已核验`，且停机 `risk` 以 `exit 0` 退出、零 `cleanup_uncertain`。 | 代码+真实 CURVE 集成测试已提交 `bt_api_py@0ff8bc96`；待下午 SimNow 实盘复验 |
| **73.03** | P1 | `[ ] 待排查修复` | `bt_api_py` | 上午 `risk.log` 出现 **17 条 WARNING**：`risk market attestation failed: CONTROL_CALL_FAILED (cause=TIMEOUT)`（7 次）、`BUSINESS_OUTCOME_UNKNOWN`（8 次，连续突刺）、`risk market poll failed: instrument=SA701 code=RECOVERY_REQUIRED`（1 次）与 `receipt_source=replay`（1 次）。 | 排查 Risk 行情证明向 Gateway `control_runtime` 发送证明 RPC 超时 / `BUSINESS_OUTCOME_UNKNOWN` 的根因（包括超时预算、并发/退避、Gateway 侧处理耗时或回放跳过逻辑），完成修复与回归测试并提交。 | 待实施 |
| **73.04** | P1 | `[ ] 待排查修复` | `bt_api_py` / `bt_api_gateway` | 上午 `gateway.log` 出现 3 次 `QUERY_BUDGET_EXCEEDED`（`09:41:40`、`10:30:09` 账户读失败各中断 ~28.1s；`11:03:58` 策略基线查询失败中断 ~33s）。 | 排查 Gateway CTP 内部查询预算（账户快照、策略基线、持仓/委托轮询、Risk `account.snapshot.typed` / `strategy_financial` 叠加频率）为何周期性触顶；在严格遵守 CTP 1 req/s 限流前提下消除内部竞争与预算误撞，补回归测试并提交。 | 待实施 |
| **73.05** | P1 | `[ ] 待排查修复` | `bt_api_web` / `bt_api_py` | ① 上午 `08:52–10:29` 期间 Monitor 事件页本身 `available`（`33/100`），但因 `monitor_source.py:1063` 将“五组件健康快照 + 事件页”合并判定，导致 Gateway/Risk 退化时 `/monitor` 卡片也被标为 `退化`，容易让运维误以为 Monitor 服务本身故障；② 同交易日 `20261125` 存在隔夜 `SHFE:hc2701` 未归属冻结时，确认 Web 页面清晰展示“为何退化”而非模糊报错（严禁伪报 `available`）。 | 审查 `/monitor` 与 `/overview` 状态呈现及提示文案：在不违背安全合同与既有测试前提下，明确区分“Monitor 自身事件查询可用”与“全局五组件存在退化”，补齐前后端测试并提交。 | 待实施 |
| **73.06** | P2 | `[ ] 待排查修复` | `bt_api_py` | 上午 `11:18:05` 优雅停机时 `runtime` / `11×execution` / `monitor_query` / `monitor` 均经零字节 stop-file 返回 `exit 0`，但 `gateway` / `gateway_web` / `risk_web` 仍因缺少协作停机文件在 Windows 上走 `terminate()` 返回 `exit 1`。 | 检查 `gateway_operator_cli`、`gateway_web_local_host`、`risk_web_local_host` 停机机制，在不放松权限/锁校验前提下补齐协作停机路径（使全栈 19 进程停机全部干净退出 `exit 0`），补单测并提交。 | 待实施 |
| **73.07** | P2 | `[ ] 待排查修复` | `backtrader` / `bt_api_py` | 上午 11 个策略共 33 次 `WARNING:DELAYED (RESYNC_REQUIRED / OWNER_TIMEOUT)`，其中 22 次高度集中在 2 个非 5s 套利策略：`mixbroker_pair_arbitrage_gateway`（13 次）与 `tickbroker_pair_arbitrage_gateway`（9 次），其余 9 个策略仅 1–2 次。 | 对比分析 `mixbroker_pair_arbitrage_gateway` / `tickbroker_pair_arbitrage_gateway` 与其余 9 个策略的喂价/队列/消费耗时，定位高频 `RESYNC_REQUIRED` 根因并修复，补回归测试并提交。 | 待实施 |
| **73.08** | P0 | `[~] 准备启动` | 跨仓 | 下午 `13:00–15:00` SimNow 第一套全栈重跑与盘中问题动态捕获。 | 拉起全栈 19 服务 + 11 策略（运行根目录 `D:\temp\007_ctp_gateway_iter73_20261125_pm`），全程监控并浏览器复核 `http://127.0.0.1:8769/`；盘中新发现问题即时追加为 `73.09+` 并逐项修复。 | 待执行 |

---

## 2. 下午重跑（`2026-11-25 13:00–15:00`）动态问题记录区

> 盘中实时观察到的任何新异常、超时、日志报错、账本不一致或 Web 页面异常，均在此追加编号 `73.09+` 并同步回填上方 TODO 清单。

- （待启动重跑后持续追加）

---

## 3. 逐项修复推进记录

- **`2026-11-25 12:42`** — 预修 `73.01` & `73.02` 根因并提交 `bt_api_py@0ff8bc96`（18 新增/聚焦回归 + 412 `bt_api_py` 扩展回归 + 27 `bt_api_web` 联调测试全绿），待本轮 `13:00–15:00` SimNow 盘中实盘复验。
- **`2026-11-25 13:08`** — 建立迭代 73 TODO 清单；准备拉起下午盘全栈重跑并在运行期间并行排查修复 `73.03`～`73.07` 及盘中新发现项。
