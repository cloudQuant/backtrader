# 两个冻结候选的成本前置筛选

- 证据级别：`PRE_R1_CALIBRATION_TRAINING_SCREEN`
- 结果：两个候选均为 `RESEARCH_REJECTED_AT_CALIBRATION_SCREEN`
- demo pair：禁止
- OOS/holdout：`NOT_CONSUMED_TRAINING_SCREEN_FAILED`

结构化 JSON 的 schema-v3 历史值 `RESEARCH_REJECTED_CALIBRATION_ECONOMIC_SCREEN`
在本文档集中规范化表达为 `RESEARCH_REJECTED_AT_CALIBRATION_SCREEN`；两者是同一
否决结论，不改写已生成证据。JSON SHA-256 为
`306a701b33493c1f4c39ff91a2e4abcf3b6f863e4a1c2183b5a4ea70d321cff3`。

本次重新使用 Iter21 已冻结的公开双 venue L2 校准记录，按因果顺序把每条行情与当时已知的
另一交易所最新完整快照配对。每个方向均用 0.01 BTC 的可执行深度计算开仓 VWAP，再在
10、50、100、500、1000 和 2500 毫秒后按可执行深度计算平仓 VWAP。每个 round trip
固定计入四笔 6 bps taker fee。

17,533 条原始记录产生 12,469 个因果配对状态和 149,387 个有效的方向/时距 round trip。
四笔手续费后的正收益次数为 0，最佳净结果仍为 -1.14246520 USDT。该筛选还没有扣资金费、
网络延迟、失败腿损失和模型误差缓冲，因此它是对候选有利的上界筛选；加入这些成本只会使
结果更差。

012_1 的均值回归模型资格通过只说明时间序列性质达到校准门槛，不能抵消交易成本；012_2
的本地 callback/decision/enqueue 延迟通过也不能抵消四笔 taker fee。两者均不得签发
`STRATEGY_APPROVED_FOR_DEMO`，`paper-live` 和 `demo` 的自动 pair write 必须保持为零。

本结果没有消费预留 holdout。重新研究需要形成新候选、新预注册和新数据，不能在原候选上
调阈值后重用本结论。约 15 分钟公开行情也不能证明其他市场状态、私有成交、排队位置或实盘
盈利能力。

该证据位于 R1/OOS 之前；它使用训练校准窗口对冻结候选做乐观上界排除，不是
样本外交易结果。结构化摘要见 `strategy-economic-screen-v3.json`。完整逐 horizon 分布保存在 checkout-local
ignored evidence，SHA-256 为
`631b9b0771b5e0ef824bc7d3f3fdf0b4050963ccacbae8800fd0fc7af1d04d10`。
