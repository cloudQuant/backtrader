# 014_1 — CTP 期权期货低频 C/P/F 套利（迭代42 标准四件套）

本目录按迭代42 标准形态交付：**README.md + config.yaml + ctp_options_lowfreq_strategy.py
+ run.py**（唯一运行入口），另含运行必需的内部模块（下表）。策略信号基于
call/put/future 转换-反转平价的结构化残差 z-score；研究状态不变，回放与工程观察
均不构成盈利或真实成交证据。

## 运行方式

```text
python run.py                          # 干跑自检：配置校验 + live 就绪度报告（不联网）
python run.py --replay [--scenario S]  # 离线冻结 fixture 回放（零网络零写入）
python run.py --live --allow-write     # live 层：现为证据化 BLOCKED（见下）
```

- 退出码：0 PASS / 1 FAIL / 2 BLOCKED / 3 UNKNOWN。
- 回放证据写入 `evidence/<run_id>/`（git-ignored）。
- 也可经迭代41 登记路径运行同一冻结回放（`LOCAL_REPLAY_ONLY`）：
  `bt-runtime run --strategy-dir examples/014_1_ctp_options_lowfreq/runtime`。

## live 层状态（BLOCKED，非降级伪装）

本策略的 live 合同要求 **feed 密封的 closed-bar 证据**（`BarEvidence` + 运行域内
非合成 `ClockMapping` + candidate/rules/clock-domain 绑定）与写能力 adapter；
该 adapter 本迭代未集成。`--live` 因此在任何网络、凭据或 provider 之前
fail-closed，输出精确的集成需求清单与翻转路径；**不会**静默降级为 raw-line
回放合同。翻转工作项（实现轮）包括：

1. feed 密封证据 provider（逐腿 `BarEvidence`，绑定 store 事件的 clock domain/
   rules/candidate 与 run 级 clock mapping）；
2. 运行域 `clock_provider`（非合成、覆盖整个有界窗口）；
3. `RegisteredSimStore` 三腿武装模板（future + call + put，逐腿 preflight 身份）；
4. 策略 live 参数（`require_feed_bar_evidence=True` 等）与一次性 drill 触发；
5. SA/FG 期权合约与行权价只读回读（C/P/F 可用性、tick、涨跌停）后才允许写入。

## 内部模块（运行必需，非第二入口）

| 文件 | 职责 |
| --- | --- |
| `legacy_runner.py` | 冻结回放引擎与 fixture（原 `run.py` 内容）；亦被 `run_runtime.py`、`simnow_launcher.py` 复用 |
| `simnow_adapter.py` / `simnow_launcher.py` | 历史 SimNow 工程观察/启动器（只读、注入式；`run_live` 固定拒绝） |
| `execution_timing.py` | 时钟/证据/执行窗口/持有投影合同 |
| `runtime/`、`run_runtime.py` | 迭代41 的 LOCAL_REPLAY_ONLY bt-runtime 登记路径 |

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

## 历史注入式 SimNow engineering_smoke（非 Iteration 41 启动入口）

Iter23 增加了一个 fail-closed 的 `simnow engineering_smoke` 入口。它只接受 SDK
owner 注入的已创建 API 对象（测试使用纯 mock），不读取 `.env`、不创建第二客户端、
不联网、不下单。入口先做账户范围的持仓、活动委托和 unknown intent 预检，并绑定
`account_fingerprint`、TradingDay 和 connection generation；任一非空、缺失或跨代际
结果都会返回 `BLOCKED`。

非纯 mock 运行时优先调用 `BtApiStore.get_ctp_bundle_preflight_snapshot(...,
read_only=True)`，收口账户范围的公共 Store 证据；退出时调用两次
`BtApiStore.get_ctp_reconciliation_snapshot()`，不自行复制 native 查询实现。
预检通过后，运行时只组装一条
`BtApiStore(provider="btapi") → BtApiFeed（三腿）→ BtApiBroker(provider="btapi") → Cerebro → Strategy` 链，Broker 使用
`market_data_only`。退出前必须完成两轮身份一致且内容稳定的 reconciliation。即便
工程链路通过，报告仍固定为 `NO_NATIVE_CONFIRMATION`，不会声称发生成交、平仓或真实
收益；真实 native 启动必须由 SDK-owned launcher 注入 API 并另行满足授权与外部验收门。
当前 Iter22 信任根缺失时，engineering_smoke 仍固定 `market_data_only=true`、
`order_write_allowed=false`，不会生成、读取或写入任何密钥，也不会解除该限制。

这是历史的 SDK-owned 注入式工程接口，不读取或升级 `runtime/config.yaml`，也不是面向操作者的
Iteration 41 启动方式。`python run.py`、`python simnow_launcher.py` 与 `run_live` 都不能用来取得
SimNow 或受管模式；上述 replay 入口仍是当前受审核的用户路径。

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

历史 `run.py` 的 `--mode`、`--scenario` 与 `--output` 已被封口并会结构化拒绝；不要用它们替代上方的
`bt-runtime run --strategy-dir .../runtime`。只有后者会读取必填的 v4 runtime 配置并检查中央清单。

`eligible`、`no_edge`、`budget_reject` 与 `misaligned` 是离线验证场景；它们均不会联网或写单。
报告中的 `LOCAL_REPLAY_PASS`、BackBroker 假设成交和 `LOCAL_BASKET_FLAT_UNVERIFIED` 只能说明
回放分支和本地顺序逻辑。`shadow`/`production` 会在建客户端前拒绝；`simnow engineering_smoke`
必须由受治理上层显式注入已认证 API，且仍以 `market_data_only` 运行。
