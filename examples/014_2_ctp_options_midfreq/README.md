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
- 也可经迭代41 登记路径运行同一冻结回放（`LOCAL_REPLAY_ONLY`）：
  `bt-runtime run --strategy-dir examples/014_2_ctp_options_midfreq/runtime`。

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
| `legacy_runner.py` | 冻结回放引擎与 fixture（原 `run.py` 内容）；亦被 `run_runtime.py`、`simnow_launcher.py` 复用 |
| `fq2_fixture.py` / `features.py` | 冻结 FQ2 分钟 fixture 与特征积分 |
| `execution_timing.py` / `execution_fixture.py` | 时钟/证据/执行窗口合同与执行 fixture |
| `simnow_adapter.py` / `simnow_launcher.py` | 历史 SimNow 工程观察/启动器（只读、注入式；`run_live` 固定拒绝） |
| `runtime/`、`run_runtime.py` | 迭代41 的 LOCAL_REPLAY_ONLY bt-runtime 登记路径 |

## 迭代 24 历史离线 runner（不属于 Iteration 41 受控入口）

以下内容描述迭代 24 保留的 import-level replay、timing 和 engineering fixture。它们只由回归测试或
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

## SimNow engineering_smoke adapter

`simnow_adapter.py` 是真实 SDK 链路的 fail-closed 装配层：一个
`BtApiStore(provider="btapi")` 产生三个 `BtApiFeed`，同一 Store 产生一个
`BtApiBroker`，再装入同一个 `Cerebro`。它不读取 `.env`，不创建客户端，不启动 Store，
不订阅行情，也不报单。历史 CLI 已统一封口，不接受隐式 API 注入，也不会加载该 adapter。

受治理的上层 launcher 可以在进程内显式传入已认证 SDK 对象调用
`run_engineering_smoke(..., api=api)`；本 adapter 只记录 transport 提供的 ACK、fill 和
terminal identity，绝不制造成交。三腿必须按确认成交推进；部分成交进入 compensation/
recovery 状态。持久日志为 append-only JSONL。实时 FQ2 只接受带
`event_time`、`recv_monotonic`、`generation`、`subscription_epoch` 且严格早于 bar cutoff
的同 cohort 事件。费用和保证金必须来自完整、身份绑定的外部输入；启动和停机均要求两轮
account-wide reconciliation。任一条件缺失即 `BLOCKED`。

当前验收中 `ITER22_APPROVAL_KEY_ID` 与 `ITER22_APPROVAL_HMAC_KEY` 均缺失，因此本路径
不会解除 `market_data_only`、不会接受空授权、不会生成或写入密钥；执行权限固定为
`NOT_PROVEN`，缺信任根时返回 `TRUST_ROOT_UNAVAILABLE`。

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

## Iteration 41 runtime 合同细节

本 README 开头的 `bootstrap` 与 `run` 是本示例唯一的 Iteration 41 用户入口。以下说明它与
迭代 24 根目录 runner 和配置的边界。

`bootstrap` 只会首次创建被忽略的 `runtime/config.yaml`，已有文件会以 `CONFIG_EXISTS` 拒绝而不会覆盖。首次建立配置必须使用上述 `bt-runtime bootstrap` 命令，避免手工复制到错误目录。该 runtime 配置与本目录原有根 `config.yaml` 的冻结 C/P/F fixture 参数是两个独立文件；模板不是
运行时回退来源。

`runtime/config.yaml` 是必填的 schema-v4 启动合同；缺失时会以 `CONFIG_REQUIRED` 拒绝，绝不从模板、当前目录或
父目录回退读取。

该入口只接受 `simulation/replay` 和唯一的 `parameters.scenario`；没有 CLI 模式、审批、账户、凭据或工程观察参数。它先校验代码拥有的运行时目录和 v4 配置，再读取既有根目录 `config.yaml` 作为冻结的本地 C/P/F fixture。`simnow_adapter.py`、`simnow_launcher.py` 和 engineering observation 不会由该入口加载或调用。

运行报告固定标记 `LOCAL_REPLAY_ONLY`，并声明它只是 synthetic C/P/F replay，不能作为 CTP/SimNow 行情、账户、成交、费用、PnL 或任何准入结论的证据。
