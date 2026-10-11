# 014_1 — CTP 期权期货低频 C/P/F 套利（迭代42 标准四件套）

本目录按迭代42 标准形态交付：**README.md + config.yaml + ctp_options_lowfreq_strategy.py
+ run.py**（唯一运行入口），另含运行必需的内部模块（下表）。策略信号基于
call/put/future 转换-反转平价的结构化残差 z-score；研究状态不变，回放与工程观察
均不构成盈利或真实成交证据。

## 运行方式

```text
python run.py                          # 干跑自检：配置校验 + live 就绪度报告（不联网）
python run.py --replay [--scenario S]  # 离线冻结 fixture 回放（零网络零写入）
python run.py --live --allow-write     # 严格 live 写层（需 Python 3.11；见下）
```

- 退出码：0 PASS / 1 FAIL / 2 BLOCKED / 3 UNKNOWN。
- 回放证据写入 `evidence/<run_id>/`（git-ignored）。
- 迭代41 登记回放路由（`runtime/`、`run_runtime.py`）已于 2026-10-11 精简轮退役；
  `run.py` 是唯一入口。

## live 层（严格三腿写 drill）

R6（`8c067982b`）已实现全严格 live 层：运行域非合成 `ClockMapping`、feed 密封
`BarEvidence`、`simnow_direct` registered-sim 直连、三腿逐腿 arm 切换（写入间
disarm→arm）、一次性 drill 触发与逐腿成交核算。`--live` 必须显式 `--allow-write`；
要求 Python 3.11（`C:/anaconda3/python.exe`）与 dev SDK 预载，其他解释器
fail-closed。写 drill 必须在交易时段内的标准前置运行（7x24 前置无涨跌停价数据，
首次彩排在 `exchange_limits_unavailable` 闸门干净拒绝、零写）；首次真实成交往返
待时段内验收。

## 内部模块（运行必需，非第二入口）

| 文件 | 职责 |
| --- | --- |
| `legacy_runner.py` | 冻结回放引擎与 fixture（原 `run.py` 内容） |
| `execution_timing.py` | 时钟/证据/执行窗口/持有投影合同 |

2026-10-11 精简轮退役：历史 SimNow 工程观察链（`simnow_adapter.py`）、独立启动器
（`simnow_launcher.py`）与迭代41 登记回放路由（`runtime/`、`run_runtime.py`）——
前者仅被测试引用、无运行入口，后者与 `run.py --replay` 行为重复。

## 历史本地回放说明（非 Iteration 41 启动指南）

本目录是一个独立策略单元。保留的 `run_replay` fixture 只生成本目录内的确定性 15 分钟 C/P/F 闭合 K 线，并通过 Backtrader 的
`Cerebro` 与本地回测 Broker 演示单篮子顺序限价逻辑。回放不读取网络、凭据或
其他 `examples/` 目录，也不会向 CTP 发出任何订单或查询。

回放还输出独立的本地 timing/risk projection：首腿期限为决策后 1 秒，整组三腿共享
60 秒完成期限，普通持仓至少 30 分钟、风险上限 120 分钟，纯 K 风险 bar 的保守年龄
上限为 910 秒。期限使用显式 monotonic clock；`notify_idle()` 没有可信时钟时会锁存拒绝，
不会把最后一根 bar 当作当前时间。15 分钟 OHLC 触价和成交量不能证明 60 秒内成交，报告
会保留 `FILL_TIMING_UNKNOWN` 与 0 个 confirmed fill；只有带明确时间区间的合成 execution
fact 才会单独标记为 `TIMESTAMPED_SYNTHETIC_ONLY`。

带显式时钟的本地时序回归还要求每个保护腿的完成回调先匹配同一 decision、basket、order、
fact、clock domain 和 generation 的时间事实，再允许发送下一腿；缺失或跨 scope 的事实会
进入恢复状态。普通退出使用全部确认成交的时间上界加最短持有期限，风险上限则从最早可能
暴露的时间下界计算，二者都不会由下一根 15 分钟 K 线的时间替代。

回放配置里的逐腿 tick/涨跌停来源带有 `synthetic-replay-price-limit-fixture` 标记，
只用于验证包络相交和限价边界，不能作为实时合约 reference 或执行授权。

本地 BackBroker 回调属于假设回放投影，退出状态只能是
`LOCAL_BASKET_FLAT_UNVERIFIED`。真实账户两轮归零、持久 token、O2 资金与取消/减险能力
仍由 SDK/CTP owner 提供；本例保持 `NOT_RUN`，不创建第二本执行或账户账本。

`--config` 只能读取本目录内的文件；包含 `..`、符号链接或任何外部绝对路径都会在
构造 Cerebro 前拒绝。因此配置不会成为读取另一个示例的隐式依赖。

`shadow`、`simnow` 和 `production` 会在构造 CTP 客户端之前以 `BLOCKED` 退出，直到
SDK 的多合约授权、期权规格/成本和真实会话预检均有独立验收证据。回放中的本地订单
不构成交易所成交、实际 PnL 或收益证明。

## 历史 SimNow engineering_smoke（已于 2026-10-11 退役）

Iter23 的注入式 fail-closed `simnow engineering_smoke` 链（`simnow_adapter.py`）只被
回归测试引用、无运行入口，已随 2026-10-11 精简轮退役。当前受审核的 live 路径是上面的
严格直连层；`python run.py`（dry/replay/live）是唯一入口。

## 策略逻辑与参数

策略只使用三腿（Put、Future、Call）同步闭合的 15 分钟 OHLCV。先用**当前 bar 之前**的
`window=40` 个残差计算均值和标准差，避免当前 bar 自我影响；随后以 put/call/future 的
可执行价格包络计算 conversion 或 reversal 的指示分数。只有 `|z| >= 2.5`、分数不少于
`20 CNY`、净边际覆盖 `round_trip_cost=20 CNY`，并连续 `confirmation_bars=2` 根均同向时才
产生一个本地决策。顺序是 Put 买入 → Future 买入 → Call 卖出；任一腿的 callback scope、
时钟域、generation 或期限不匹配都会停止后续腿并进入恢复，而不是猜测成交。

| 配置组 | 当前默认值 | 说明 |
| --- | --- | --- |
| `candidate` | SA701 / SA701C1080 / SA701P1080，1:1:1 | 本地 C/P/F fixture 身份；不是可直接用于交易的合约选择。 |
| `strategy_params` | 40 bar、`entry_z=2.5`、`exit_z=0.5`、`bar_minutes=15` | 残差统计、入/退出阈值和确认规则；`projected_entry_capital=6500` 必须在普通预算内。 |
| `budget` | 10,000 / 8,000 / 2,000 CNY | 总额 / 普通路径 / 恢复预留；replay 是投影，不是 O2 预算能力。 |
| `timing` | 首腿 1 秒、整篮子 60 秒、持仓 30–120 分钟 | 使用显式单调时钟；空闲回调只推进风险投影。 |

## 历史回放 API 与输出说明

历史 `run.py` 的 `--mode`、`--scenario` 与 `--output` 已被封口并会结构化拒绝；
`run.py` 的 dry/replay/live 标准模式是唯一入口。

`eligible`、`no_edge`、`budget_reject` 与 `misaligned` 是离线验证场景；它们均不会联网或写单。
报告中的 `LOCAL_REPLAY_PASS`、BackBroker 假设成交和 `LOCAL_BASKET_FLAT_UNVERIFIED` 只能说明
回放分支和本地顺序逻辑。`shadow`/`production` 会在建客户端前拒绝；真实写入只在
`--live --allow-write` 的严格直连层进行。


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

本目录的 live 通道是写 drill，第一步即要求显式 `--allow-write`（否则 `REJECTED / write_consent_missing`）；无写观察通道由迭代 43 的 R5b 轮补齐。
严格回放校验器把 `entry` 段投影掉（沿用既有 `live_adapter` 先例），所以新的入口字段不会放宽冻结回放契约的键集合，其他未知字段仍全面拒绝。
