# 迭代 21 策略研究预注册

> 历史冻结记录：本文的候选、参数、数据边界和 hash 保留原值，不因后续实施覆写。
> 2026-09-08 备注：后续只增加 dynamic funding refresh/TTL、identity 绑定和 fail-closed 等工程/
> 风控配置，alpha 假设、方向模型和训练数据未变。当前证据是
> `PRE_R1_CALIBRATION_TRAINING_SCREEN`，两候选均
> `RESEARCH_REJECTED_AT_CALIBRATION_SCREEN`，OOS/holdout `NOT_CONSUMED`。

> 冻结时间：2026-09-07，公开 L2 首轮采集进行中、任何价格/收益结果分析之前。
> 版本：`PREREG-1`
> 变更规则：查看 validation/holdout 后不得修改本登记来让候选通过；任何新参数必须使用
> 新数据和新候选 ID。

### PREREG-1A 数据边界修订

首轮采集请求 900 秒，但从第一条到最后一条有效双所消息只有 898.185 秒，因此按上文硬门槛
判为数据资格 `FAIL`，不会放宽成 898 秒。该问题在任何价格、信号或收益分析之前发现。
阈值、成本和策略参数保持不变；首轮数据仅作为 calibration/train/validation，随后启动的
独立 910 秒捕获被预先锁定为 holdout。第二次捕获完成前不得查看其价格或收益统计。holdout
仍须自身满足两个 venue 各 1,000 条、同一 clock domain、多档有效簿、可识别重连以及至少
900 秒有效消息跨度。此修订提高隔离强度，不允许把首轮结果选择性拼入 holdout。

## 1. 数据和切分

- 标的限定为 OKX `BTC-USDT-SWAP` 与 Binance USD-M `BTCUSDT`。
- 两个 WebSocket 由同一进程采集，记录 exchange time、wall receive time、monotonic receive
  time、clock domain、sequence/previous sequence、5 档以上 bid/ask 和重连次数。
- 按本次完整捕获的接收顺序做连续 `50% train / 25% validation / 25% holdout`；边界一旦由
  总行数计算就写入 data card，任何段不重排、不删除。
- 任一 venue 事件到达时，只能使用当时已到达的另一 venue 最新状态；禁止使用未来事件。
- 配对时两簿 monotonic skew 必须不大于 250 ms；两簿 age 必须不大于 500 ms。
- 数据资格最低要求：总时长至少 900 秒、两个 venue 各至少 1,000 个有效多档状态、同一
  clock domain、所有未连续/重连区间可识别。未达到时状态为 `INCOMPLETE`。
- 首轮 900 秒捕获用于工程和短窗 OOS 候选判断，不能声称覆盖完整市场状态或资金费周期；
  对未来实盘研究仍需多日和至少一个实际 funding 周期。

## 2. 成本和成交假设

- 只使用按目标 base quantity 逐档吃单得到的 entry/exit executable VWAP；若任一侧深度不足，
  缩量到共同格点或拒绝。
- Entry spread/depth impact 已包含在 executable edge 中，不重复扣减。
- Round trip 计四笔实际账户 taker fee。G5A 前拿不到实际 fee 时，以每笔 6 bps 的保守上界
  运行候选筛选并把 fee source 标为 `conservative_bound`；不能标“实际净收益已验证”。
- Exit reserve 使用 validation 段观察到的 95% 不利退出成本，并设最低每腿 1 bp。
- HFT latency reserve 使用 10/50/100/500 ms 后验 markout 的较坏方向 95% 分位；在该分位
  尚不可得时使用每腿 1 bp 下界。
- Funding 只在持仓跨实际结算点时按 long 支付/收取和 short 相反方向逐次计入；未跨结算点
  为精确 0，不使用绝对值储备代替 cashflow。
- partial/reject/timeout 的失败腿损失全部计入，unknown 在收敛前冻结新开仓。

## 3. 012_1 中低频候选

- 候选 ID：`midfreq-robust-basis-v1`。
- 基差定义为在共同 base quantity 上的两方向 executable spread，中心与尺度使用滚动
  median/MAD；窗口 120 个合格配对状态。
- Entry：`|robust_z| >= 3.0`、同方向连续至少 3 个状态、完整 round-trip 费用后预期边际
  大于 1 bp、深度/连续性/时间全部合格。
- Exit：`|robust_z| <= 0.5` 且费用后可实现收益为正；风险出口包括继续发散到 entry z 的
  1.5 倍、持有 300 秒、数据 stale、margin/readiness 或净损失预算触发。
- 每方向最大同时 1 个 pair，base quantity 先用 0.01 BTC 并按实时 InstrumentSpec 共同格点
  向下量化。

## 4. 012_2 事件候选

- 候选 ID：`event-taker-taker-ioc-v1`；默认执行为双腿 taker IOC。
- maker-taker 因缺真实 queue position、撤单生效和 adverse-selection 证据而延期。
- lead-lag 不在本候选中启用；任何未来模型必须另行预注册特征、标签、方向风险和新 holdout。
- Entry：两方向 executable edge 在完整 round-trip 成本、latency reserve 和 failure reserve
  后大于 1 bp；连续有效机会寿命至少 500 ms，且大于候选测得的保守 p99 双腿路径。
- sequence gap、previous mismatch、stale、skew、重连恢复、深度不足或 overload 均停止开仓；
  连续两个合格 snapshot 后才恢复。
- 第一腿根据更深盘口和较低预估冲击动态选择；第二腿只按第一腿 confirmed fill delta；每腿
  deadline 1 秒，pair deadline 2.5 秒。超限进入 cancel/query/flatten，不盲目重发。

## 5. 样本外准入

每个候选在 holdout 同时满足以下条件才把研究状态写为 `OOS_PASS`：

1. 至少 10 个完整 closed pairs；不足为 `INSUFFICIENT_SAMPLE`，不得补造交易；
2. total net PnL 和 per-pair expectancy 都大于 0；
3. 至少一半时间分段的净 PnL 非负，且单一最佳交易贡献不超过总净 PnL 的 50%；
4. 对 closed-pair PnL 做固定 seed 的 2,000 次有放回 bootstrap，均值大于 0 的概率至少 75%；
5. 最大回撤不超过交易名义价值的 1%，最大已实现裸腿损失不超过名义价值的 10 bps；
6. 所有费用、funding、impact、latency 和失败腿损失均可由独立报告重算。

数据合格且交易数足够但经济门失败时为 `RESEARCH_REJECTED`；数据合格但交易不足时为
`INCOMPLETE/INSUFFICIENT_SAMPLE`。二者均不签发 `STRATEGY_APPROVED_FOR_DEMO`，也不允许
自动跨所 pair 写入。合成 profitable/loss/no-edge/partial/unknown/gap 只给
`MECHANICS_PASS`，不进入上述统计。

## 6. HFT 名称门

只有以下条件全部在候选代码上通过，manifest 才允许 `hft_label=true`：

- 012_2 不继承或导入 012_1；
- 标准事件连续性和 Store 守恒测试通过；
- callback/decision/enqueue 10 万次固定负载 p99 不超过 5 ms；
- 策略回调无网络 I/O；
- 实际 shadow 报告包含机会寿命和 markout，且所有 write/fill/PnL 为 0；
- 机会寿命门使用保守 p99 路径，不能只靠本地平均延迟。

若本地实现门失败，目录改名为 `012_2_event_driven_cross_exchange` 并记录 HFT `FAIL`；若仅
外部样本不足，则保留候选代码但 HFT 状态为 `BLOCKED_BY_EXTERNAL_EVIDENCE`，不得夸大为
共址或微秒级 HFT。
