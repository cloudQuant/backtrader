# 014_2 — CTP 期权/期货中频 C/P/F 套利（迭代42 标准四件套）

本目录按迭代42 标准形态交付：**README.md + config.yaml + ctp_options_midfreq_strategy.py
+ run.py**（唯一运行入口），另含运行必需的内部模块（下表）。当前合约映射仍为本地
`F_LOCAL` fixture；回放与工程观察均不构成盈利或真实成交证据。

## 运行方式

```text
python run.py                          # 干跑自检：配置校验 + live 就绪度报告（不联网）
python run.py --replay [--scenario S]  # 离线一分钟 FQ2 fixture 回放（零网络零写入）
python run.py --live                   # live 观察层（零写；需 Python 3.11，见下）
python run.py --live --allow-write     # 显式 BLOCKED：本策略无下单路径
```

- 退出码：0 PASS / 1 FAIL / 2 BLOCKED / 3 UNKNOWN；回放/观察证据写入 `evidence/<run_id>/`（git-ignored）。
- 迭代41 登记回放路由（`runtime/`、`run_runtime.py`）已于 2026-10-11 精简轮退役；
  `run.py` 是唯一入口。

## live 层（观察，零写）

本策略按合同为**决策专用**（token 结果 `ENGINEERING_WRITE_DISABLED` / `REPLAY_WRITE_DISABLED`，
不存在下单路径），因此 live 层采用 R7/R8 计划修正案的**观察层**：真实直连
registered-sim（SimNow）链——front 选择 → Store 登录与账户/持仓/合约元数据只读查询 →
3 × `BtApiFeed` 分钟桶（`closed_bar_quote_capture`）→ 策略在 feed 密封的
`BarEvidence`（live 时钟域、非 synthetic `ClockMapping`）上计算 FQ2 特征与决策。
零写：不 arm、不下单；`--allow-write` 明确 BLOCKED
（`write_tier_not_implemented_for_decision_only_strategy`）。

- 环境要求：Python 3.11（`C:/anaconda3/python.exe`）+ dev SDK `D:/bt_api_py`；其他解释器
  fail-closed `live_tier_requires_python_3_11`（dry/replay 不受限）。
- PASS = 观察窗内 ≥1 个完成分钟特征窗（`WARMUP`/`ORDINARY_DECISION`）且
  `feed_evidence_fault=null`、`order_write=0`；证据 `evidence/live-*/run.json`。
- 已知环境事实：7x24 前置报价事件钟可能陈旧（曾观测 ~47.9h），无法满足 live 时钟域时
  以 `BLOCKED / live_event_clock_outside_run_mapping`（含可用年龄秒数）知会；标准前置
  交易时段内正常；不会降级为伪造证据。

## 内部模块（运行必需，非第二入口）

| 文件 | 职责 |
| --- | --- |
| `legacy_runner.py` | 冻结回放引擎与 fixture（原 `run.py` 内容） |
| `fq2_fixture.py` / `features.py` | 冻结 FQ2 分钟 fixture 与特征积分 |
| `execution_timing.py` / `execution_fixture.py` | 时钟/证据/执行窗口合同与执行 fixture |

2026-10-11 精简轮退役：历史 SimNow 工程观察链（`simnow_adapter.py`）、独立启动器
（`simnow_launcher.py`）与迭代41 登记回放路由（`runtime/`、`run_runtime.py`）。

## 迭代 24 历史离线 runner（不属于 Iteration 41 受控入口）

以下内容描述迭代 24 保留的 import-level replay 与 timing fixture。它们只由回归测试或
受治理的代码调用；`python run.py` 执行上面四个标准模式，历史 CLI 参数会被拒绝。

`fq2_fixture.py` 先明确生成 synthetic clock mapping、三腿 bar seal 和每腿 60
个一秒 quote 状态，策略只消费 barrier 冻结的 `MinuteDecisionInput`。
`features.py` 按 `[T-5s,T)`、`[T-60s,T)` 做时间积分，检查每段不超过 2 秒、三腿
source/receive skew 不超过 500ms，并在第 61 分钟使用此前 60 个有效分钟计算
median/MAD。默认 `no_edge` 序列结果为 `NO_EDGE`；回归测试可用 `run_replay(..., scenario="edge")` 查看
完整 FQ2 特征通过、一次性 token 被当前 `next()` 消费、但仍被 replay 写入禁令
拦下的决策记录：

`inject_cutoff_tick` 只用于离线验证：它在回放结束后把一条由 producer 明确携带
bid/ask/量、scope、sequence、wall/monotonic receive 证据的 cutoff tick 交给
`notify_tick`。该回调只能记录特征，不能创建普通决策、改变 60-bar 历史或提交订单；
`inject_at_cutoff_tick` 验证等于 T 的接收时间会被拒绝。

配置是严格 schema。未知键、非有限数、重复 C/P/F 合约、非 1:1:1 手数、不是一分钟/
60-bar 的参数，以及超过 10,000 元或不满足工作预算与恢复预留关系的配置都会在创建
Cerebro 前拒绝。`shadow`、`simnow` 和 `production` 同样会在配置解析阶段失败关闭；
本目录没有 CTP 客户端、凭据或网络路径。

MF-T1 的本地时序投影由 `run_timing_replay()` 通过真实 Cerebro 的无参 idle 回调运行，且仅用于回归测试。

`execution_timing.py` 只消费显式 synthetic scope、UTC/monotonic mapping 和脱敏的
执行事实快照。单腿、未对冲篮子、撤单和恢复期限分别从持久意图起点计算；普通退出使用
最近完整成交的上界加最短持仓，并由后续合法 minute barrier 决定，最大持仓从最早可能
暴露的下界计算。实际 feed 返回 `None` 时 Cerebro 会调用 `notify_idle()`，该路径只推进
风险投影，不创建普通开仓。缺少 SDK grant、reservation、offset 或真实账户对账时，输出
始终是 `execution_permission=NOT_PROVEN`，零外部请求和零交易写入；此 synthetic replay
不替代 CTP/SDK 执行验收。

保留 fixture 的 config reader 只能读取本目录内的文件；包含 `..`、符号链接或任何外部绝对路径都会在
构造 Cerebro 前以 `CONFIG_PATH` 拒绝，避免形成对其他示例配置的隐式读取依赖。

JSON 输出明确标出 `external_network_requests=0`、`external_trade_writes=0`、
`actual_order_permission=NOT_PROVEN` 及 `actual_pnl=null`。根目录提供的独立 180 quote
oracle 只用于测试输入与边界对照，策略没有用产品函数倒算 expected。当前 producer
是显式 synthetic replay 输入，不能替代真实 CTP Feed/Store/Broker、期权合约资格、
三腿执行恢复、账户预算、安装包和第一套环境验收；这些边界仍按迭代 24 文档保持
`BLOCKED` 或 `NOT_RUN`。

## SimNow engineering_smoke adapter（已于 2026-10-11 退役）

Iter24 的注入式 fail-closed `simnow_adapter.py` 装配层（三腿 Store/Feed/Broker/
Cerebro 链、ACK/fill 记录、append-only JSONL）只被回归测试引用、无运行入口，已随
2026-10-11 精简轮退役。策略的 `engineering_observation` 模式语义保留（live 观察层
使用），由 `run.py` 的严格直连链驱动。

## 策略逻辑与参数

该策略以 C/P/F 三腿的一分钟闭合 bar 作为唯一普通决策入口。每分钟的 `MinuteDecisionInput`
必须由同一 candidate、TradingDay、generation、规则哈希和 session segment 的 barrier 冻结；
tick 仅用于冻结 FQ2 特征，不能在 `notify_tick` 创建订单。FQ2 对 5 秒与 60 秒窗口做时间积分，
要求每个片段不超过 2 秒，三腿 source/receive skew 不超过 500ms；第 61 分钟才用前 60 分钟的
median/MAD 得到 residual z-score。符合 edge 时，也只生成一次性本地 token；replay 永远不提交。

| 配置组 | 当前默认值 | 说明 |
| --- | --- | --- |
| `candidate` | F/C/P local 三腿、1:1:1、multiplier 10 | 冻结的本地身份与 tick size；不表示已核验的 CTP 合约。 |
| `signal` | 1 分钟、60 根历史、`z_entry=2.5`、净边际至少 20 CNY | FQ2 合格后才可发出局部 edge 决策。 |
| `features` | 5s/60s、片段 ≤2s、skew ≤500ms、至少 3 次新快照、持久度 0.8 | 保证三腿行情的因果、时间质量与方向稳定性。 |
| `budget` | 10,000 / 8,000 / 2,000 CNY，路径需求 7,600 | 总预算、工作预算、恢复预留与单路径上限。 |
| `timing` | 决策 30s、单腿 5s、整篮子 15s、撤单 5s、恢复 60s | `notify_idle()` 只投影风险截止点，不能产生普通开仓。 |

## 迭代 24 历史 runner 的验收边界

历史 CLI 参数不再可执行；它们会在 framework/provider 导入前拒绝。`edge`、cutoff-tick 注入和
timing fixture 都是确定性测试输入。它们输出的 `LOCAL_REPLAY_PASS` 或
`LOCAL_TIMING_REPLAY_PASS` 不证明真实 CTP 行情、账户、成交、费用、PnL 或 G1–G4；非 replay
模式在无受治理 API 注入时应失败关闭，缺失审批信任根时执行权限保持 `NOT_PROVEN`。

## Iteration 41 runtime 登记路由（已于 2026-10-11 退役）

迭代41 的 `runtime/`、`run_runtime.py` 登记回放路由（`bootstrap`/`run`、schema-v4
配置）已随 2026-10-11 精简轮退役；`run.py` 的 dry/replay/live 标准模式是唯一入口。


## 运行层选择（迭代 43）

本目录的通道由 `config.yaml` 的 `entry.tier` 决定，命令行模式参数只能**保持或降低**它，不能上调：

| `entry.tier` | 无模式参数 | `--dry` | `--replay` | `--live` |
| --- | --- | --- | --- | --- |
| 未声明 | `dry`（与迭代 43 之前逐字一致） | `dry` | `replay` | `live` |
| `dry` | `dry` | `dry` | `dry` | BLOCKED `config_tier_conflict` |
| `replay`／`backtest` | `replay` | `dry` | `replay` | BLOCKED `config_tier_conflict` |
| `live` | `live` | `dry` | `replay` | `live` |

- 规范值 `dry | replay | live`；`backtest` 是 `replay` 的文档别名，证据里记 `effective_tier: replay`。
- 非法值、错误类型或 `entry: null` 在**任何 handler 与 provider 副作用之前**返回
  BLOCKED `config_tier_invalid`，绝不回落到 live。
- 输出 JSON 的 `tier` 字段记录 `config_tier / cli_tier / effective_tier / tier_selection_reason`，
  `write_grant_result` 记录写授权结果。`--allow-write` 与选层正交：判定器不读它，
  本目录原有的写准入条件一字未改。
- 判层依赖本目录自带的 `entry_tier.py`（`examples/_support/entry_tier.py` 的逐字节副本，
  由 `tests/unit/test_examples_self_contained.py` 漂移守卫），因此整个目录被复制到别处后
  仍能自行判层。

声明方式（追加到本目录 `config.yaml` 末尾）：

```yaml
entry:
  tier: replay   # dry | replay | live（backtest 为 replay 别名）
```

本目录的 live 通道按契约**只观察不下单**：`--allow-write` 在 `run_live` 的第一条语句就被拒绝（`write_tier_not_implemented_for_decision_only_strategy`），因此可用它来证明确实分发到了 live 通道而不产生任何 provider 副作用。
严格回放校验器把 `entry` 段投影掉（沿用既有 `live_adapter` 先例），所以新的入口字段不会放宽冻结回放契约的键集合，其他未知字段仍全面拒绝。
