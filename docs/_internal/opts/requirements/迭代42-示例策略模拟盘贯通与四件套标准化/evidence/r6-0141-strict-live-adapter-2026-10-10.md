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
| **组合链（打标 tick → 真实 feed 密封 → provider 握手）** | `tests/unit/test_iteration42_options_live_chain.py` **4 passed**：wrapper 队列 → `_prepare_tick`/`_ingest_tick`（与生产 poll 路径同序）→ 桶密封 → 示例 provider 构造 `BarEvidence` → feed 侧身份校验全部通过（域/代次/rules/session/candidate/序列/桶边界逐项断言，桶外 tick 不泄漏）；**负例**：未打标 tick 在密封时按 provenance 合同 ValueError 拒绝 |
| **quote 捕获（014_2 前置原语）** | 主仓附加式 `closed_bar_quote_capture`（默认关、上限可配、溢出丢最旧+旗标）：captured quotes 全部通过**真实 `validate_quote_against_bar`**（身份/域/代次/质量/窗口逐项）；limit=1 溢出时 `complete=False`；`tests/unit/feeds` + 相关聚合 **914 passed** |
| 014_1 dry / replay | exit 0 / eligible+no_edge `LOCAL_REPLAY_PASS`（live 段经 legacy 剥离） |
| option + iteration42 单测 | **640 passed**（含 583 option、组件边界/挂载、provenance） |
| btapistore 回归 | `tests/unit/stores` 710 passed / 13 skipped |
| Lint | ruff 全部改动文件 clean |

打标 lane 说明：真实直连 CTP tick 不带 `ctp.quote.v2` schema/时钟质量声明，打标后走
feed 的 legacy 质量 lane（不伪造 v2 上游执行资格/新鲜度声明）；密封证据的
`rules_hash`/`session_segment`/`clock_domain` 由 caller 身份保证，feed 质量旗标为空、
`complete=True`（组合链测试已证）。策略侧另有自身质量与证据门。

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
  FQ2 分钟特征消费 5s/60s **quote 窗口**（barrier 以 `BarEvidence.quote_events` 经
  `_quote_filter` 构造 `accepted_quotes`）。**feed 侧逐桶 quote 捕获已实现并离线验收**
  （见下）；剩余= 014_2 run.py 复用 014_1 的 `_LiveClock`/provider 结构 + quote_events
  候选注入 + 真实合约映射（F_LOCAL→SA）。
  - **关键运维事实**：CTP `UpdateTime` 为秒级，水印=max(事件秒)+摄取耗时，会使密封
    时刻相对真实时钟**回拨最多约 1 秒**；因此每桶末尾 ≤1s 的 quote 会按因果规则被
    `QUOTE_AFTER_SEAL` 拒绝（属设计内因果截断）。014_2 的 5s/60s 窗口完整性约束
    （每段 ≤2s 缺口）在此尾部损失下仍可满足；窗口设计须按 ≥58s 有效覆盖评估。
- **015**：tick-only cohort 路径（`CtpCohortNow`）语义在 store 的 SDK-event 管线；
  live 需把已打标 tick（本轮 `live_tick_provenance`）接入其 cohort/证据面，并在
  015 run.py 复用同一 `_LiveClock`/provider 结构；HFT 延迟结论保持排除。
- 两者均共享本轮的主仓打标与 `simnow_direct.configure_live_tick_provenance`，
  无需再次改动 CTP 路由本身。

## 首跑彩排（2026-10-10 05:44 北京，7x24；与周一命令逐字一致）

014_1 的 live 写 drill 此前 0 次真实执行；本次以 Monday 计划同一条命令首跑：
`--live --allow-write --drill --run-seconds 3000 --drill-delay-seconds 300
--drill-window-seconds 900`。

链路实际走到：front 选择（index 4，7x24 唯一 eligible，whitelisted）→ Store 启动与登录
（read_only_ready）→ 账户/持仓/合约元数据查询 → **交易所涨跌停价闸门**：
`BLOCKED / no_admissible_front_pair`（attempts.details: `exchange_limits_unavailable`,
symbol `CZCE.SA701`；7x24 环境无涨跌停价，与 014_2 同日预检事实一致），exit 2。

零写入：拒绝发生在三腿武装之前（run.json 无 arm/orders/写计数字段），无任何订单动作。
证据：`examples/014_1_ctp_options_lowfreq/evidence/live-20261009T214444Z-5a848a7f/`。

判定：写 drill 验收路径 = **时段内标准前置**（周一 09:55，计划不变）；本次彩排验证了
入口从选择、登录、查询到涨跌停价闸门的完整 fail-closed 行为，并确认 7x24 前置不会
被误用作写路径（干净、快速、有据可查的拒绝）。

## 周一窗口网格余量修正（2026-10-10 复核）

014_1 的工程触发由 `_engineering_trigger_direction()` 以墙钟 `time.time()` 判定，但**只在
15 分钟闭合 bar 的决策路径评估**（tick 只记录 cutoff 特征，不产生普通决策）。原 Monday
命令（delay 300 / window 900）在 09:55 起跑下窗口 ≈ [10:00:30, 10:15:30]，仅覆盖 10:15:01
一个网格决策点且余量 ~29 秒，对封存延迟与时钟相位敏感。已改为 **delay 120 / window 1500**
（窗口 ≈ [09:57, 10:22]，覆盖 10:00:01 与 10:15:01 两个决策点），`--run-seconds 3000`
覆盖至 10:45；argv 预检同步重跑。

## 周一前就绪审计（2026-10-10 午后）

- **三腿 arm 序列（014_1 未实跑过的唯一新元素）**：属性判断=低风险组合，无新代码路径——
  三腿提交流水线对既有原语做两次顺序切换（A→B→C，平仓反向），而原语已被 2 腿（013_2 彩排 #6
  实测）与跨交易所切换（`test_ensure_arm_switches_only_between_writes` 精确覆盖
  M2612/DCE↔RM612/CZCE，`test_native_dispatch_switches_to_the_outbound_instrument` 覆盖
  出站合约触发的 disarm→arm）离线锁定；其余新元素（打标链/密封证据/provider 握手）有专测
  （provenance 3 + live chain 4）。触发窗口余量见上节（两点网格）。
- **首次实跑预期顺序**：09:55 起跑 → 预检（flat 账户、逐腿元数据/涨跌停/手续费回读）→
  三腿武装（逐腿验证+写入间切换）→ 等待 10:00/10:15 网格决策点 trigger → 双腿开仓成交
  → 15 分钟 bar 后按 exit_offset/平仓映射出场 → 会话级逐腿成交核算；终态台账见 run.json。
