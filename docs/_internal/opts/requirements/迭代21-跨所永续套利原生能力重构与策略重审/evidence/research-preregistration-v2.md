# 迭代 21 策略研究预注册 V2

> 历史冻结记录：下列 candidate/runner/strategy/config/manifest/qualification hash 保留原值，
> 不用后续工程文件的 hash 回写。
> 2026-09-08 备注：动态 funding refresh/TTL、identity 绑定、风险窗口与 fail-closed 是工程/
> 风控改进，没有改变 alpha、训练数据或方向模型。两候选已在
> `PRE_R1_CALIBRATION_TRAINING_SCREEN` 被标记为
> `RESEARCH_REJECTED_AT_CALIBRATION_SCREEN`，OOS/holdout `NOT_CONSUMED`。

> 冻结时间：2026-09-08T03:43:20+08:00，在 V2 holdout 创建之前。
> 协议：`PREREG-2`。V1 捕获已用于成本和模型校准，禁止进入本轮样本外结论。
> 变更规则：读取 V2 holdout 的价格、机会或收益后，不得修改本协议或当前候选使其通过；
> 任何参数变化都必须生成新候选 ID，并重新采集未查看过的 holdout。

## 1. 冻结候选

| 项目 | 012_1 中低频 | 012_2 事件驱动 |
|---|---|---|
| candidate SHA-256 | `53ee786573a2367d46a795fedf156168190de47cbd3c9b787ad36861b9f57ac2` | `cdd4225b32cda583a808db58bd8ae451b51786a7ecc067ebfc6e1e4906da952f` |
| runner SHA-256 | `367448c71f287b4bfb9b705da5e98a1a576528d4a202ea0321569c1983acff07` | `5ab5be74e500f212fa9cd70fbaafcbde91c39d7e1ba97cee9529f5ef9564fff8` |
| strategy SHA-256 | `f6f105291e76fa5bace6ed12b13e0eb958e80f9e62c490daa3b28db246df8cc6` | `ff4bc3fa6baebe61b411a35691e8ad6ce6df55abcd2125269eaf6366b45b9f53` |
| config SHA-256 | `f6fbc302b19a120f72a9de8daa10ee9b9b42e9c82247ae1086867bfbb1157271` | `3a636935426271b7e9f5b8ffff2354761abac0e8dcf44bd4f46b662b8686c0f2` |

候选清单 SHA-256 为
`2419372c1a5fbfd55e280417c7d00b4efd92e6f4673afac5fa72a9f87b9b882f`。
012_1 的方向绑定资格文件 SHA-256 为
`230bdda11b8b0d3ee85687ab30af0db2416dcf9029c6e36dcf9a6f9c0c6fded9`；它只使用 V1
数据，角色固定为 `calibration_training_only`，不能作为 OOS、demo 或盈利证明。

## 2. V2 holdout 数据资格

- 只采集 OKX `BTC-USDT-SWAP` `books5` 与 Binance USD-M `BTCUSDT`
  `depth20@100ms` 的公开永续合约盘口。
- 两个连接必须在同一 Python 进程中记录同一 `clock_domain_id`、接收 monotonic ns、接收
  wall time、exchange time、connection generation、sequence、previous sequence 和原始多档深度。
- 捕获文件和 meta 文件使用排他创建；不得覆盖、拼接 V1 数据或补写缺失区间。
- 请求捕获时间至少 910 秒。有效资格要求首条至末条双所可用消息跨度至少 900 秒、每个交易所
  至少 1,000 条合法多档状态、两所均有消息、单一 clock domain，所有重连均由 generation
  边界标识。
- 任一事件只能与当时已经接收的另一交易所最新状态配对，禁止读取未来状态。合格配对要求
  monotonic skew 不超过 250 ms；更大的 skew、空档、交叉簿、非正价格或数量全部拒绝并计数。
- generation 内 sequence 倒退、重复或无法解释的缺口使该方向失效；只有后续合法完整 snapshot
  才能恢复。重连边界前后的状态不得混配。
- 不满足任一数据资格条件，两个候选均记为 `INCOMPLETE/DATA_QUALIFICATION_FAILED`，不计算
  OOS PASS，也不以缩短阈值补救。

## 3. 冻结成交与成本假设

- 目标数量为 0.01 BTC；OKX 使用 0.01 BTC/contract 和整数 contract 格点，Binance 使用
  BTC 数量与 0.001 BTC 格点。任一腿不满足数量、深度或最小名义要求即拒绝。
- entry 与 exit 都按当时可见 L2 逐档计算 taker executable VWAP。entry spread/depth 已包含在
  executable edge 中，不再重复扣除。
- 每个完整 round trip 计四笔 taker fee；没有账户费率证明时，每笔固定使用 6 bps 保守上界。
- 012_1 固定 `exit_reserve=2 bps`、`latency_reserve=1 bps`、`failure_reserve=2 bps`、
  `model_buffer=3 bps`；012_2 固定为 1/2/3/2 bps。两者净边际必须严格大于 1 bp。
- 持仓没有跨资金费结算点时 funding 精确为 0；跨越结算点但没有实际 signed funding ledger
  时经济结果为不完整，不能假定为 0。
- partial、reject、timeout、cancel unknown 和失败腿补偿产生的确认损失全部计入；没有确认成交
  不产生 PnL。订单提交数与确认 fill delta 数分开报告。

## 4. 冻结策略判据

012_1 使用 V1 校准得到的两个方向独立 AR(1) 资格工件。每个方向必须同时通过完整
rules+risk contract hash、数据来源、basis definition、127 次固定 bootstrap、单位根置信度、
半衰期和有效期检查。OOS 中使用 1 秒因果状态、120 状态 median/MAD、`|z| >= 3.0`、连续
3 次且至少持续 2 秒开仓；`|z| <= 0.5` 且完整退出成本后为正才作收敛退出；最长持有 300 秒。

012_2 只评估双腿 taker IOC 的独立事件策略：机会需连续存在至少 500 ms，quote age 不超过
500 ms、skew 不超过 250 ms、净边际严格大于 1 bp；第一腿和 hedge deadline 均为 1 秒，
pair deadline 和最长持有均为 2.5 秒。500 ms adverse markout 至少 21 个样本且缺失率不超过
25%；缺失或 adverse reserve 超预算即拒绝。lead-lag 未准入，maker-taker 延期。

## 5. OOS 结论门

每个候选独立满足以下全部条件才可把研究状态改为 `OOS_PASS`：

1. 至少 10 个有四腿确认成交或完整失败腿补偿的 closed pairs；不足即
   `INCOMPLETE/INSUFFICIENT_SAMPLE`，不得补造交易。
2. 总 realized net PnL 和每 pair expectancy 均严格大于 0；所有费用、impact、signed funding
   和失败腿损失可以从确认 fill ledger 重算。
3. 按时间等分的片段中至少一半净 PnL 非负，且单一最佳 pair 对总正净 PnL 的贡献不超过 50%。
4. 固定 seed `210921`、2,000 次有放回 bootstrap 中，均值大于 0 的比例至少 75%。
5. 最大回撤不超过目标交易名义价值的 1%；最大确认裸腿损失不超过名义价值的 10 bps。
6. 数据缺口、被拒机会、亏损、零机会和所有运行失败必须进入同一报告，禁止只选择盈利区间。

数据合格且样本充足但任一经济门失败时为 `RESEARCH_REJECTED`。数据合格但交易不足时为
`INCOMPLETE/INSUFFICIENT_SAMPLE`。这两种结论都不签发 demo approval，不允许自动跨所下单。

## 6. 运行顺序与名称边界

V2 holdout 分析只能在文件关闭、fsync、meta 与数据 SHA-256 固化后运行一次；分析不得回写
候选参数。随后仍需 G3 安装态一致性和 G4 公开网络 shadow 全部 PASS，才能进入 demo 私有
预检与单 venue G5A。012_2 的本地 callback/decision/enqueue 性能只作为工程诊断；公开网络、
交易所队列位置和成交延迟未被证明，因此名称固定为“事件驱动”，HFT gate 固定为 `FAIL`。
