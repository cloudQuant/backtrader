# 迭代42 — 周一（2026-10-12）真实验收执行计划

目的：在 SimNow 交易时段内按序执行 R1/R4/R5 的有界 drill 成交往返验收（三次独立 run，
共享同一模拟账户与同一 `C:/anaconda3/python.exe` + dev SDK `D:/bt_api_py`）。

## 时段与顺序

所有步骤串行（同一账户；每步等上一步进程完全退出后再启动）。观察层步骤零写，但仍串行。

| 序 | 示例 | 建议窗口（北京） | 命令（示例目录内执行） |
| --- | --- | --- | --- |
| 1 | 013_3 SA 写 drill | 09:00 开盘后立即启动（CZCE 日盘 09:00–11:30） | `python run.py --live --allow-write --drill --drill-side long --run-seconds 2700 --drill-delay-seconds 1200 --drill-window-seconds 1500 --drill-warmup-bars 8` |
| 2 | 014_1 SA 期权三腿写 drill | 09:55 起（同日上午盘） | `python run.py --live --allow-write --drill --run-seconds 3000 --drill-delay-seconds 120 --drill-window-seconds 1500` |
| 3 | 014_2 SA 期权观察（零写） | 10:50 起（上午盘内，900s 窗口） | `python run.py --live --run-seconds 900` |
| 4 | 015 FG 期权观察（零写） | 11:10 起（上午盘内，300s 窗口） | `python run.py --live --run-seconds 300` |
| 5 | 013_1 m/RM 写 drill | 13:35 启动（DCE 午后盘 13:30–15:00） | `python run.py --live --allow-write --drill --drill-side long --run-seconds 2700 --drill-delay-seconds 1200 --drill-window-seconds 1200 --drill-warmup-bars 8` |
| 6 | 013_2 rb 写 drill | 21:05 启动（SHFE 夜盘 21:00–23:00） | `python run.py --live --allow-write --drill --drill-side long --run-seconds 2700 --drill-delay-seconds 1200 --drill-window-seconds 1200 --drill-warmup-bars 8` |

- 每次 run 结束（含 drain）后再启动下一个；同一账户串行。
- 标准前置仅交易时段 TCP 可达；选择器会先 7x24 后 standard（时段外）。若首轮
  admission 结果异常，记录 attempts 再决定人工干预。
- SimNow 标准前置在成交回报上可能缺少 `OnRspOrderInsert`：以场内侧订单查询为受理判定
  （R1 备忘录已有该事实）；`_order_state`/订单事件链正常时无需干预。

## PASS 判据（§2 成交往返）

- 013_3：`filled_entry>0 且 filled_close>=filled_entry`、终态 flat、无活动单、无 UNKNOWN。
- 013_1/013_2：会话归属 trades 中**每条腿** entry>0 且各腿 close>=entry（`entry_by_symbol`/
  `close_by_symbol`）、终态 flat、无活动单、无 UNKNOWN；`arm_history` 反映写入前腿部切换
  （013_1 应出现 m↔RM 切换；013_2 为 rb2701↔rb2705）。
- 014_2（观察层）：标准前置在时段内应选出 whitelisted standard pair；PASS = `status=OBSERVATION_PASS`
  且 `observation.feature_minutes>=1`（WARMUP/ORDINARY_DECISION 来自真实封存 BarEvidence）、
  `feed_evidence_fault=null`、`order_write=0`。若出现 `live_event_clock_outside_run_mapping`（事件钟
  与运行映射不匹配，7x24 环境曾观测到 ~47.9h 陈旧钟），说明该前置报价钟不满足 live 证据链，换时段
  或前置复跑，不降级判定。
- 015（观察层）：PASS = `status=OBSERVATION_PASS` 且 `observation.ticks_by_leg` 每条腿 ≥1
  （真实 tick 经标准入口进入 cohort 策略）、`order_write=0`；`reject_counts`（预期为
  `TRUSTED_NOW_INVALID`，直连源无 `ctp.quote.v2` 证明）与 `cohort_decisions` 为事实字段，
  不据此伪造合格 cohort。注意 `--run-seconds` 需覆盖准入（时段内标准前置可达时约 20s；
  仅 7x24 可达时 4 组不可达探测约 +70s；窗口耗尽会以
  `observation_window_exhausted_before_run` 证据化 BLOCKED）。
- 证据：各目录 `evidence/live-*/run.json`（git-ignored）；随后把脱敏摘要 + SHA-256 归档到
  迭代42 evidence 目录，并在 `r1-live-run-progress` 备忘补记数值。

## 失败处理

- `no_admissible_front_pair` → 记录 attempts（含 error_details），确认标准前置可达后重试一次；
  仍失败则当日按证据化 BLOCKED 记录并说明。
- **首跑彩排事实（2026-10-10 凌晨，7x24）**：014_1 首次 live 执行（周一同命令）在
  **交易所涨跌停价闸门**干净拒绝（`exchange_limits_unavailable`，7x24 无涨跌停价；拒绝
  发生在三腿武装之前，零写入）；014_2 观察层真实链走到密封分钟桶后因陈旧事件钟 BLOCKED。
  → 写 drill 的唯一可验收路径=**时段内标准前置**；7x24 只用于观察层。
- **013_2 首跑彩排发现并修复 drill 竞态**：`--drill` 运行把 `max_pairs=1`，而自然路径在
  warmup 未成熟期（`--drill-warmup-bars 8`）可用伪 z 消耗唯一尝试额度（彩排实录
  attempts=1/fired=false，随后 `_try_open` 永久短路，6789 tick 无一开仓）→ 策略新增
  "存在未触发 drill 时抑制自然开仓"门（`_natural_open_suppressed`，013_1/013_2 同源修复，
  回归测试 +2）。013_1/013_2 周一参数相应放宽为 `--drill-delay-seconds 1200
  --drill-window-seconds 1200`（窗口 [20,40] 分钟，容 warmup+就绪）；013_3 设计不同
  （显式 warmup 门+触发分离），未受影响。
- **014_1 窗口网格分析（2026-10-10 复核）**：014_1 为 15 分钟 bar 决策（tick 不产生普通决策），
  触发仅在各 bar 网格点检查 → 900s 窗口可能只覆盖一个网格点且余量仅 ~20–30s。已调整为首个
  决策点（约 10:00:01）前的 delay 120s + window 1500s（[~09:57, ~10:22]），覆盖 10:00/10:15
  两个网格决策点，双机会触发；`--run-seconds 3000` 覆盖至 10:45。
- 选择器排序确认：**standard kind 优先，其次延迟**（`_kind_rank`；配置顺序仅 tie-break），
  标准前置仅在全部端口探测失败时才落入 7x24。时段内若仍落入 7x24（标准 pair 全不可达，
  其报价钟曾观测 ~47.9h 陈旧）：封存证据类策略（013_x/014_x）会以
  `live_event_clock_outside_run_mapping` 等 fail-closed；014_2 观察层同样。此时记录 attempts
  与标准 pair 探测样本，确认标准前置可达后复跑。015 观察层对前置不敏感（仅到达级观察）。
- 腿成交不齐（partial_round_trip）→ 不重跑覆盖；保留证据，人工核对残余敞口（run.py 已冻结
  gate 不会继续写）。
- 任何 UNKNOWN → 停止后续 run，先对账（README/§2 层级）。

## 收尾（当日）

1. 更新三个示例的验收记录（r1/r4/r5 记录追加实跑数值与证据哈希）。
2. 生成迭代42 最终 tracker（JSON+MD，§7.1 字段：dry/replay/live/tier/trigger/env_scope/orders/
   cleanup/evidence_sha256/commit/status）。
3. 收尾轮提交（R9）：tracker + 基线清单 + 最终 AGENTS/README 校订。
