# 迭代42 R5 — 013_2（rb 跨期）实现与离线验收记录（2026-10-10）

状态：**实现与离线验收完成**；真实成交往返（rb 主力/次主力双腿 + 平仓 + 对账）待
周一 2026-10-12 SHFE 交易时段执行（建议夜盘 21:00 窗口，与 R1/R4 串行）。本记录为
该轮的实现与离线证据。

## 范围（实现轮）

- 013_2 四件套化：`README.md` + `config.yaml` + `calendar_arbitrage_strategy.py`
  （原 `strategy.py`，git mv）+ `run.py`（新标准入口，dry/`--replay`/`--live`）；
  旧 `run.py` → `legacy_runner.py`；`run_runtime.py` 同步改引 `legacy_runner`
  （登记 LOCAL_REPLAY_ONLY 路由恢复）。
- 策略迁移 = R4 同一组变更（§4 三类缺陷修复 + `close_offsets`/`deadline_clock`/
  `broker_position_mode`/`engineering_trigger` 参数），保留 013_2 的高频差异：
  `trade_logger_tick_interval=128`（报告节流）、period 60 / entry_z 1.5 /
  confirmations 1 / min_interval 0.1 / max_pairs 5 / max_holding 120s。
  与 013_1 迁移模块逐字 diff 仅剩上述高频差异（已核对）。
- 双腿同交易所（SHFE）：`run.py` 的腿部唯一性守卫由“交易所唯一”放宽为
  “合约唯一”（rb2701≠rb2705；013_1 的 m/RM 天然不同交易所，不受影响，已同步在
  013_1 中修正并复验 dry）。
- `simnow_direct.py`：013_3 同源字节副本（含 R4 双腿武装扩展），无漂移守卫已覆盖。
- 平仓 offset：rb 属 SHFE → 交易所元数据推导 `close_today`（与既有前缀启发一致，
  行为差异仅在离线默认被显式映射取代）。
- 配置：`live_contracts.symbols=auto`（rb 主力+次主力季度）、`exchanges.rb=SHFE`、
  `instrument_metadata.rb` tick=1/mult=10、`timeouts.run_seconds=1800`、
  `drill.hold_seconds=180`。冻结段保持原值（含 `run_timeout_seconds: 180`）。

## 离线验收（实际执行）

| 项 | 命令 | 结果 |
| --- | --- | --- |
| dry | `python run.py` | exit 0；合约 rb2701/SHFE + rb2705/SHFE；5 组 front pair；仅环境变量名 |
| replay | `python run.py --replay`（profitable/loss） | 均 `LOCAL_REPLAY_PASS`（profitable=4 组配对动作） |
| 登记回放 | `bt-runtime run --strategy-dir .../013_2.../runtime` | exit 0；`admission_status=LOCAL_REPLAY_ONLY`、`hft_status=FAIL/NOT_ADMITTED`（保持既有标注） |
| 聚焦测试 | `pytest tests/unit/test_ctp_pair_examples.py` | 34 passed（EX1/EX2 双迁移锚点） |
| 同源守卫 | `test_examples_self_contained.py` + multiarm 测试 | 013_2 simnow_direct 字节同源通过；其余 3 项为既有基线（R9 处置） |
| Lint | ruff（本轮变更文件） | 通过（013_2 仅剩既有 ctp_example_support 两处 SIM112 基线） |

## 待执行：真实成交往返验收（周一）

命令（建议 21:00 北京后启动；08 分钟级预热 + 触发窗口 + 有界持有平仓）：

```text
python run.py --live --allow-write --drill --drill-side long --run-seconds 1800 \
  --drill-delay-seconds 600 --drill-window-seconds 600 --drill-warmup-bars 8
```

PASS 判据：会话归属 trades 中 rb 两腿（rb2701/rb2705）均 entry 成交且各腿
close ≥ entry；终态无持仓、无活动委托、无 UNKNOWN；`arm_history` 反映写入前
腿部切换；对账通过。HFT 延迟结论不在本迭代范围（保持 `FAIL/NOT_ADMITTED` 标注）。

## 证据层级

本记录为**离线/源码级**证据：dry、回放、登记回放、聚焦测试与同源守卫；
不构成账户、provider 或成交结论。周一 live 结果另起记录追加。

## 首跑彩排与修复（2026-10-10 凌晨，7x24）

013_2 首次真实 live 执行（命令与周一一致）：front 选择（7x24 唯一 eligible）→ 双臂
**首次真实武装**（rb2701+rb2705，`set2_7x24_4000x`，managed+proof）→ RUNNING（6789 真实
tick）→ `FAIL / no_fill_round_trip`（1951.8s 有界返回、run_error=null、终态 flat、
`session_order_refs=0`、`open_position_rows=0`）。

归因（源码+诊断）：drill 分支 `max_pairs=1`，而 warmup 未成熟期的自然 z 尝试先消耗了唯一
额度（attempts=1 / fired=false），此后 `_try_open` 永久短路 → drill 永不触发。修复与回归
见 R4 记录同节；Monday 013_2 窗口放宽为 delay 1200 / window 1200（[20,40] 分钟）。
彩排同时验证：选择/登录/查询/双臂武装/证据落盘/有界清理全链真实可用。
