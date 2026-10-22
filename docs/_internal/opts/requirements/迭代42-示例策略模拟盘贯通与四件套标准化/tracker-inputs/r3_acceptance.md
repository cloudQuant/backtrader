# R3 验收记录：012_2 四件套化 + 双所 Demo 门（2026-10-09/10）

状态：**实现与迁移完成；Demo 成交往返 = 证据化 BLOCKED（候选研究状态结构门，按设计）**。

## 本轮范围

- 012_2 标准四件套：`run.py`（dry / `--replay` / `--live --allow-write --mechanical-smoke`）、
  `config.yaml`（新增 `entry` 段）、`event_driven_strategy.py`（原 strategy.py）、`README.md`（重写）；
  旧引擎 → `legacy_runner.py`（导入/校验适配）。
- manifest 刷新链：canonical（`strategy_module`、runner/strategy/config 哈希、candidate_sha256）
  + folder-local（`--check` 通过）；`.gitattributes` 路径更新。
- 测试更新：8 个 012 相关测试文件（含 `tests/performance/test_cross_exchange_event_path.py`
  与 `tests/unit/strategies/test_012_2_event_cross_exchange.py`）的模块路径与策略文件名锚点。

## 门结果

| 项 | 结果 | 证据 |
| --- | --- | --- |
| dry | DRY（config+entry+凭据 env 名；零网络） | 输出 JSON |
| replay | FORMULA_CHECK_PASS（0 网络/0 写单） | `evidence/replay-*/report.json` |
| 测试切片（8 文件 466 项） | 465 passed / 1 failed（012_1 基线时间门，见 r2 记录） | 会话日志 |
| refresh `--check` | 两目录 up to date | — |
| Ruff | run.py clean | — |
| Demo 链路 | store 构建/准入通过 → **执行门拒绝** | `evidence/live-20261009T191708Z-7c59c5fd/run.json` |

## Demo BLOCKED：`execution requires immutable direction/first-venue/fee/depth/latency path models`

- 事实：`event_path_models_from_candidate()` 在 `research_status != "PASS"` 时返回空；
  `_run_network_impl` 对 `paper-live/demo` 强制要求非空路径模型 → 本候选
  （`RESEARCH_REJECTED` + `HFT_FAILED`）**按设计不可执行**；manifest
  `event_path_models=None`。这正是 AGENTS/迭代21 记录的
  `HFT FAIL/NOT_ADMITTED`（需端到端延迟、队列与真实成交证据方可准入）。
- **翻转路径**：完成迭代21/30 的 HFT 路径模型准入流程（产出 OOS 方向/首场所/费率/深度/
  延迟模型并置 `research_status=PASS`，刷新 manifest）→ 原命令直接复跑；
  属研究/取证治理工作，不在迭代42 范围。
- 本轮为此门补充了**结构证据**（此前该门在示例层不可达；四件套入口与 manifest 链已就绪）。

## 附带修正

- 012_1 README 按既有测试契约补齐免责声明与 `python -m examples...run` 调用形式（R2 收尾项）。

## 追加：HFT 准入门机械冒烟贯通 — MECHANICAL_DEMO_SMOKE_PASS（2026-10-10 本轮）

在 operator 确认的 rejected-candidate demo 通道内为 012_2 建立**有界机械冒烟**路径，
并完成完整真实往返验收。候选研究状态与 `HFT_FAILED / NOT_ADMITTED` 标注不变；
常规 demo/paper-live 的研究准入门保持 fail-closed。

### 机械冒烟路径（新增，显式边界）

- `run.py --live --allow-write --mechanical-smoke` 现传入 `mechanical_demo_smoke=True`；
  `_run_network_impl` 仅在 `mode == demo`、`allow_rejected_demo_simulation=True`
  （operator override）且显式该旗标时放行空 `event_path_models`，并在 admission、
  报告与引擎快照标注 `MECHANICAL_DEMO_SMOKE_OVERRIDE_NO_RESEARCH_MODELS` /
  `MECHANICAL_DEMO_SMOKE_NOT_RESEARCH`（`bypassed_gates` 明列四项研究门）。
- 引擎机械分支：以当前真实买卖盘与费率定价发出意图，**入场提交前每次 book 可重发**
  （新鲜定价、容忍瞬时风险读取窗口）；`entry_committed` 后不再发出 → 每次冒烟至多
  一个回合。矩阵测试锁定：无旗标时该门仍按设计拒绝（store 之前）。

### 本轮定位并修复的缺陷链

1. **Decimal/float 提交边界**（策略 `_submit`）：`size/price` 显式 float 化
   （Backtrader 订单管道为 float）；首个真实成交即暴露 `order.execute` 的
   Decimal-float TypeError（`live-20261010T080859Z-94ccc2b0`，4 单 2 成交后崩溃）。
2. **账户风险瞬时读取粘滞上锁**（策略 `_account_loss_allows_entry`）：
   `stale_or_unbound`（含 store 周期刷新的 pending 窗口）曾置粘性 kill switch →
   一次瞬时读即永久封死入场（`live-20261010T083250Z-782be2ec`：176 次 stale +
   130 次 latch 拒绝、306 次机械重发零成交）。修复：瞬时陈旧只阻断当次；真实
   违约/契约错误仍上锁。
3. **持仓期 kill-switch 读频**：改为 ≥2s 节流，避免风险刷新车道长期在途（刷新窗口
   内 SDK 将提交判为 definite reject）——`live-20261010T081931Z-4a8b18db` 的
   flatten 两连拒 `account_risk_refresh_in_progress` 即此窗口。
4. **SDK 风险新鲜度门顺序**（`_risk_freshness_error`）：记录仍在 max age 内时，
   后台刷新在途不再构成 placement 阻塞（不再拒绝含减仓在内的合法下单、摘要不再
   瞬时 trading_blocked）；陈旧/未验证时仍阻塞。契约测试改为"陈旧前提"并在 SDK
   新增"新鲜记录不受例行刷新阻塞"回归（SDK 184 passed / 2 skipped）。
5. **停机对账时序**（broker `stop()`）：首次对账未证明 flat 且无 uncertain 单时，
   在停机预算内做至多 3 次有界重试（间隔 0.25s），覆盖"刚平仓订单终态轮询未及"
   的快照竞争。

### 真实验收

- 运行 `live-20261010T083916Z-f28557f7`：`MECHANICAL_DEMO_SMOKE_PASS`（exit 0）。
  - 4 单 4 成交全成：binance 买 0.01（开）→ okx 卖（对冲开）→ binance 卖平 →
    okx 买平；`mechanical.entry_committed=true`（提交前重发 5 次）；
    `execution_summary.evidence_complete=true`、无阻塞；
  - `broker_shutdown = PASS / reason=remote_flat_proven / remote_flat_proven=true`，
    active/local/remote/unknown 全 0；store `shutdown_state=PASS`。
- 中间失败记录保留不改写：`3c1e1db3`（瞬时不完整读被误判）、`94ccc2b0`（float
  边界崩溃）、`4a8b18db`（刷新窗口拒减仓）、`782be2ec`（瞬时 stale 粘锁）。
- 回归：SDK `test_execution_session.py` 184 passed / 2 skipped；主仓 012_2 策略
  86 passed、matrix 128 passed；相邻切片（pair/boundary/perf）绿；012_1 主路径在
  本轮 SDK/broker 变更后回归复跑：首跑 `live-20261010T084455Z-c18671f0` 出现
  okx 卖单到期限未成交被撤（一键式机械配对不重试）→ `MECHANICAL_DEMO_SMOKE_INCOMPLETE`
  （fill=0；全链无 unknown、停机对账 PASS、账户无残留——属市场时点而非代码回归）；
  复跑 `live-20261010T085734Z-82a55b70` 恢复 `MECHANICAL_DEMO_SMOKE_PASS`
  （fills 5、`FLAT_RECONCILED`、`remote_flat_proven=true`）。
- broker 停机对账重试新增两个单测（首次快照不 flat 时第二次证明 flat → PASS；
  永不 flat 时恰 3 次有界重试 → INCOMPLETE）。
- 运维工具（D:/temp，非入库）：Binance 残仓有界平仓脚本
  `iter42_0122_close_residual.py`（sell-limit+IOC、positionSide=LONG、
  价格 0.1 tick 量化），在一次崩溃残仓处置中实跑 FLAT。

### 边界与备注

- 真实成交往返验收 = Demo 机械配对的技术贯通证据；不构成策略有效性、盈利、
  生产或 HFT 延迟准入结论；历史冻结记录不被本迭代改写。
- 备注（既有约定，非本轮引入）：012_x 六个 pinned 文件的 manifest 哈希按**工作树
  原始字节**记录（含 CRLF）；跨平台 fresh checkout（`eol=lf`）下需在收尾轮统一
  归一（列 R9 事项），本轮不改变已验收字节。
