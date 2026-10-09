# R1 验收记录：013_3 四件套化 + SimNow registered-sim 真实贯通（2026-10-10）

状态：**实现与诊断完成；真实成交往返验收等待 CZCE 交易时段（下一次：2026-10-12 周一 09:00 北京时间）**。

## 环境事实（决定性）

- 非交易时段（周六）标准前置 TCP 可达但无行情；7x24 工程前置有行情但**缺 LowerLimitPrice**
  （策略 `normalize_quote` 要求有限日涨跌限价字段）：诊断 run `live-20261009T184538Z-acedd8bd`
  显示 356 条 quote 全部 `quote:invalid_lower_limit`、closed_bars=0 → 无进场 → FAIL(no_fill_round_trip)。
- 结论：**R1 live 验收必须在真实交易时段、用标准前置执行**（周一 09:00 北京 / 01:00 UTC 起；
  选择器时段内自动优先 standard）。届时按同一命令以 drill 完成成交往返。

## 已修复（本轮全部真实验证）

1. **成交归属缺陷（重要）**：v2 的 "PASS" 实为误报——564 手来自共享模拟账户的既有/他人会话成交；
   策略全程 WARMING 无进场。已修：仅统计本会话 OrderRef（`_order_state`）的成交；
   诊断 run 验证：`session_order_refs=0, scoped trade_rows=0, account_trade_rows=15`，
   FAIL(no_fill_round_trip) 正确判定。
2. **策略诊断面**：run.json 新增 `strategy_diagnostics`（closed_bars/quote_window_seconds/
   invalid_quotes/block_counts/unknown_intents/evidence&risk 失败计数），定位效率大幅提升。
3. **启动契约**：`get_execution_summary`（armed=session_enabled；frozen→trading_blocked+unknown_id）
   + wrapper 订单状态跟踪 → 策略正常进入 WARMING（v1 的 MANUAL_INTERVENTION 消除）。
4. 期间修复（真实验证）：MD 请求编号 0 兼容（btapistore 增量透传）、dual-side 能力声明、
   旧校验器凭据键净化、dev SDK 路径遮蔽、CLI 不回显、watchdog 硬停机、时段感知前端选择。

## 验收链条

| 项 | 命令 | 结果 | 证据 |
| --- | --- | --- | --- |
| dry | `python run.py` | PASS | 输出 JSON |
| replay | `python run.py --replay` | LOCAL_REPLAY_PASS | `evidence/replay-*/` |
| 注册回放 | `python run_runtime.py` | LOCAL_REPLAY_PASS | runtime/reports |
| 单元切片 | `pytest tests/unit/test_ctp_sa_*` | 195 passed / 1 env-fail | 会话 |
| runtime 全量 | `pytest tests/unit/runtime` | 747 passed / 23 skipped | 会话 |
| store | `pytest tests/unit/stores/test_btapistore*.py` | 356 passed | 会话 |
| live 准入 | `run.py --live --allow-write --drill …` | **ARMED**（首个经 Store 链路；set1_/set2_ 前置） | `live-20261009T175637Z-a5eaef61/run.json` |
| live 行情→策略 | 诊断 run | 356 quotes 到达但被环境缺限价拒（见上） | `live-20261009T184538Z-acedd8bd/run.json` |
| **live 成交往返** | **周一 09:00 北京后重跑 drill** | **待执行（时段门控）** | — |

环境/基线说明、提交草稿见 `r1-live-run-progress-2026-10-10.md`。
