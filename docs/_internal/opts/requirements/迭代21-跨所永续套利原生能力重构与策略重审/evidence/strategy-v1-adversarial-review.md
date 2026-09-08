# Iteration 21 策略 V1 对抗审查

> 历史快照：本文保留 V1 审查时的反例；当前候选结论见
> `final-implementation-review.md`。

> 审查状态：`FAIL / NO-GO`
> 适用候选：`midfreq-robust-basis-v1`、`event-taker-taker-ioc-v1`
> 处置：V1 只能保留为历史研究证据，不得签发自动 demo pair 或实盘准入。

## 1. 结论

原有 012_1 与 012_2 的窄测试虽通过，但没有证明真实订单状态机、完整成交经济性或 HFT
名称门。现有 candidate manifest 将研究状态保持为 `INCOMPLETE`、把自动 demo pair 关闭是
正确的；V1 代码本身仍存在足以阻止 G3/G4/G5B 的缺陷，因此不得通过调整旧 holdout 参数
使其转为 PASS。

012_1 的可执行基差均值回归假设仍可作为新候选研究，但必须增加独立、冻结的稳定性和
半衰期资格。012_2 可保留 taker-taker IOC 作为事件驱动基线；在真实
Strategy → Broker → Store 入队路径、SDK 连续订单簿和 shadow 延迟证据完成前，取消
`highfreq` 名称。

## 2. 阻断项与 V2 处置

| ID | 级别 | V1 缺陷 | V2 必须满足的处置 | 验收边界 |
|---|---|---|---|---|
| SR-001 | P0 | 多档 VWAP 平均价被直接用作 IOC limit，目标数量可能无法成交 | oracle 同时返回 VWAP 与吃完目标数量所需的边际价格；订单按 side/tick 向市场方向量化边际价格 | 多档成交量、VWAP、limit 三者守恒 |
| SR-002 | P0 | 012_1 无 entry/hedge/cancel/pair deadline；012_2 deadline 依赖下一条有效行情 | Broker 的无 bar 轮询执行 monotonic execution/cancel deadline；策略只提交显式截止信息 | 无行情、gap、stale 下均能有界进入 cancel/query/unknown |
| SR-003 | P0 | 迟到 fill、重复累计量和本地 flatten 后远端状态未证明 | 按 venue/client/order ID 合并累计成交；未知状态冻结开仓；最终以远端 reconcile 证明 flat | 本地队列空不得等同远端 flat |
| SR-004 | P0 | 012_1 只有 median/MAD z-score，没有稳定性/半衰期资格 | 新候选读取绑定 data hash、方法、样本量、半衰期、有效期和 qualified 状态的不可变资格 | 缺失、过期、不合格一律 fail-closed |
| SR-005 | P0 | 实际退出 L2 已计 close spread/depth，却再次扣预计退出执行成本 | expected 与 realized/preview ledger 分离；实际 close 只计四次成交、实际 fee/funding 和明确的风险项各一次 | Decimal 逐项重算严格守恒 |
| SR-006 | P0 | replay 直接伪造 4 orders/4 fills、partial、loss 和 PnL | 公式 fixture 不再报告真实订单、成交、收益率或胜率；执行 fixture 必须经过 Strategy/Broker 通知路径 | synthetic 数据只允许 `R0_FORMULA_FIXTURE` |
| SR-007 | P0 | 所谓 HFT 性能测试只对纯 engine 的零信号做 `deque.append(None)` | 012_2 先改名 event-driven；重新申请 HFT 时必须覆盖真实 callback/order/enqueue 并产生可交易 intent | 未过完整门时 `hft_label=event_driven`、HFT=`FAIL` |
| SR-008 | P1 | 500 ms 后一帧同时填充 10/50/100/500 ms markout | 记录实际 elapsed 和误差容限；超窗 horizon 为 missing | 每个 horizon 可审计实际时间误差 |
| SR-009 | P1 | order_count 被当作 fill_count | submitted/accepted/partial/completed/canceled/rejected/unknown 与成交 delta 分开统计 | 拒单和零成交 IOC 不计 fill |
| SR-010 | P1 | 裸腿计时从 submit 开始，持仓计时从 signal 开始 | 裸腿从第一笔 confirmed fill 开始；完整 pair 从第二腿确认时开始 | 延迟分布与实际暴露一致 |
| SR-011 | P1 | 固定 20 USDT 止损与设计不一致，margin/funding 动态门未接线 | 风险预算按 notional/波动/成本上界表达；未接入的 readiness/funding 能力明确阻断 | 不允许未接线参数出现在准入声明 |
| SR-012 | P2 | 首腿评分直接相加秒、reject rate 和 `1/depth` | 统一为无量纲风险分数或 quote-currency 条件损失 | 每个分量及权重可重算 |

## 3. V1 证据解释

- 六类 `profitable/loss/no_edge/partial/unknown/gap` fixture 只能说明部分公式分支能被触发。
- V1 fixture 没有创建真实 Backtrader order，不得把固定的 `orders_submitted=4`、`fills=4`
  或人工改写的 gross/net 当作机制、模拟账户或盈利证据。
- 原 15 分钟 holdout 的零 intent、零 closed pair 继续记为
  `INCOMPLETE/INSUFFICIENT_SAMPLE`；V2 改变执行与经济语义后必须使用新候选 ID 和新的冻结
  OOS 数据，不能复用 V1 holdout 作为 V2 样本外通过证据。

## 4. 允许继续的范围

V2 在 G3 完成前只允许单元测试、公式 fixture、冻结历史数据研究和零写入 shadow。G4 完整
通过后可执行只读 demo preflight；G5A 仅允许单交易所最小 LONG/SHORT 开平校准。只有新候选
达到预注册 OOS 门槛并获得绑定收据，才允许 G5B 自动跨所 pair demo。
