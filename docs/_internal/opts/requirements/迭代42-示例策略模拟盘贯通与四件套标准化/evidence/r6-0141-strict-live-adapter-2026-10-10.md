# 迭代42 R6 — 014_1 严格 live adapter 实现记录（2026-10-10）

状态：**严格 live 适配器实现与离线验收完成**；真实三腿 drill 待 SimNow 交易时段
（与 R1/R4/R5 同一 Monday 窗口串行，见 `monday-live-run-plan-2026-10-12.md`）。
本记录替代（并收窄）先前 `r6-r8-options-conversion-and-live-scope-record` 中的
"live=BLOCKED" 结论——该结论作为该来源时点的侦察记录保持历史用途。

## 实现（本轮）

1. **主仓附加式打标**（`backtrader/stores/btapistore.py`，默认关）：
   - `CtpClientWrapper` 新增可选配置 `live_tick_provenance`（caller-owned clock
     identity）；CTP 深度回调构造 TickEvent 后逐条打标：clock_domain_id /
     rules_hash / session_segment / connection_generation / ingest_seq / sequence /
     previous_sequence / continuity / source / event_id / received_monotonic_ns /
     exchange_time / delta_volume / volume_complete。未配置时行为与字段完全不变。
   - 该字段集与 `btapifeed._causal_event_kwargs` + bar builder 的读取面逐项对齐
     （新增测试直接调用 btapifeed 的读取函数断言）。
2. **示例内严格 live**（`examples/014_1_ctp_options_lowfreq/run.py`）：
   - `_LiveClock`（运行域 + 非合成 `ClockMapping` + 观测 provider）统一供给：tick 打标
     （`store.configure_live_tick_provenance`，login facts 之后、订阅之前）、
     `_LiveEvidenceProvider`（feed 密封 BarEvidence：mapping/candidate/rules 绑定）、
     策略 `clock_provider` 与执行窗口；
   - 三腿准入：账户清空检查、逐腿 `instruments` 元数据核对（tick 0.5 期权 / 1.0 期货、
     mult 20、涨跌停必须可用）、逐腿费率读回（provider_commission_rate）、
     逐腿 arm 演练 + 运行期逐腿 arm 切换模板（anchored 于首出腿）；
   - 策略参数：`require_feed_bar_evidence=True`、`bar_evidence_clock_mode="live"`、
     运行域、真实 price_ticks/exchange_limits/fee_schedule、dual_side +
     entry/exit offset；drill 触发一次性窗口 + `max_holding_bars=2`（30 分钟确定性
     max-hold 退出，满足全部冻结时序交叉校验）；
   - 运行期：15 分钟 bar feeds（`closed_bar_evidence_provider`）+ `notify_idle` 泵 +
     watchdog + 信号量 + 收割后按腿会话归属成交核算（entry/close per leg）+ 残余敞口
     冻结 + arm_history 证据。
3. **策略增量（默认回放不变）**：`broker_position_mode`/`entry_offset`/`exit_offset`/
   `engineering_trigger` 参数；`_submit_next_leg` 按状态附加 offset+position_side；
   drill 只替代 z/score 资格（确认、预算、token、执行窗口与全部冻结合同不变），
   首次真实开仓后 latch。
4. `simnow_direct.py`（canonical + 4 份字节同源副本）：新增
   `configure_live_tick_provenance`；`LEGACY load_config` 剥离 `live_adapter` 段保持
   冻结回放合同（含测试）。

## 离线验收（实际执行）

| 项 | 结果 |
| --- | --- |
| 打标字段测试 | `tests/unit/test_iteration42_live_tick_provenance.py` 3 passed（含 feed 读取面逐项对齐；默认关不变） |
| 014_1 dry / replay | exit 0 / eligible+no_edge `LOCAL_REPLAY_PASS`（live 段经 legacy 剥离） |
| option + iteration42 单测 | **640 passed**（含 583 option、组件边界/挂载、provenance） |
| btapistore 回归 | `tests/unit/stores` 710 passed / 13 skipped |
| Lint | ruff 全部改动文件 clean |

## 翻转后的真实验收（Monday）

```text
python run.py --live --allow-write --drill --drill-side conversion \
  --drill-delay-seconds 900 --drill-window-seconds 1200 --run-seconds 5400
```

PASS 判据：三条腿（SA701 / SA701C1080 / SA701P1080）各自 entry 成交 >0 且
close ≥ entry；终态无持仓、无活动单；策略状态非 HALTED/RECOVERY；`arm_history`
反映 PUT→(FUT)→CALL 写入前切换；`strategy_report.json` bar_only_access_audit
为 feed_sealed；断连/失败即 BLOCKED+证据。窗口内若期权腿无行情超出 drill 窗口，
记录 attempts 与 bar 证据后 BLOCKED。

## 证据层级

本记录为**离线/源码级**证据；不构成账户、provider 或成交结论。014_2/015 的
同模式移植在 014_1 实盘 drill 通过后进行（其策略共享同一架构）。

## 014_2/015 移植预侦察（2026-10-10，供 014_1 实盘验证后的 adapter 轮）

- **014_2**：策略拥有 `require_feed_bar_evidence` + `notify_bar` 同一 seam，但其
  FQ2 分钟特征消费 5s/60s **quote 窗口**；两者的互斥契约（有生产者则必须
  require=False）表明 live 需要 **feed 侧逐桶 quote 事件捕获**：stock `BtApiFeed`
  目前不保留 tick 历史、`BarEvidence.quote_events` 无生产者。翻转工作量 =
  btapifeed 附加式 `closed_bar_quote_capture`（桶内采样/逐步追加 + 密封事件附带
  quote_events）+ 014_2 run.py 复用 014_1 的 `_LiveClock`/`_LiveEvidenceProvider`
  并把 quote_events 传入 BarEvidence（provider 已留字段）+ 真实合约映射（F_LOCAL→SA）。
- **015**：tick-only cohort 路径（`CtpCohortNow`）语义在 store 的 SDK-event 管线；
  live 需把已打标 tick（本轮 `live_tick_provenance`）接入其 cohort/证据面，并在
  015 run.py 复用同一 `_LiveClock`/provider 结构；HFT 延迟结论保持排除。
- 两者均共享本轮的主仓打标与 `simnow_direct.configure_live_tick_provenance`，
  无需再次改动 CTP 路由本身。
