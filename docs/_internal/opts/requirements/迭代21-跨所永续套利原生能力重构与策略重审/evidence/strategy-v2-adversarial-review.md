# Strategy V2 独立对抗审查

> 历史快照：本文保留 V2 审查当时的反例和 `G2 FAIL`，不是 2026-09-08 最终
> 候选状态。后续修复、研究否决与未闭合生产阻断项以
> `final-implementation-review.md` 为准；原文保留作为演进证据。

- 审查对象：`012_1_midfreq_cross_exchange`、`012_2_event_driven_cross_exchange`
- 审查性质：独立只读代码、测试和反例审查
- 审查结论：`NO-GO`
- Gate：`G2 FAIL`
- 模拟双所下单：`NOT_APPROVED`

聚焦测试当时为 46 项通过，Store 本地入队性能诊断为 1 项通过。这些结果只证明已覆盖的
局部合同，没有推翻下列阻断项。

## P0 阻断项

| ID | 发现 | 影响 | 修复与独立验收要求 |
| --- | --- | --- | --- |
| V2-P0-001 | 引擎用 entry VWAP 与当前反向 VWAP 的差构造预计退出成本，entry spread/depth 在 entry executable edge 后又被扣一次 | forecast 与按同一盘口立即四笔成交的实际 ledger 不一致 | 明确预测退出参考价和残余 basis；改变 entry depth 时成本只变化一次；由独立 fill ledger 重算 |
| V2-P0-002 | AR(1) 点估计、half-life 和 MAD 位移会把随机游走误判为稳定；20 组各 180 点的 seeded random walk 中 16 组被放行 | 中低频候选会在无稳定关系时开仓 | 引入保守 unit-root/置信上界规则；覆盖多随机种子、near-unit-root、variance/regime break |
| V2-P0-003 | qualification artifact 未强制绑定数据哈希、venue/symbol、basis 定义、采样、训练区间和配置 | 任意手造 artifact 可绕过研究门 | 完整 fingerprint 必填并在引擎入口校验；错配一项即 fail closed |
| V2-P0-004 | Broker 使用 `cancel_execution_unknown`，策略只识别 `execution_unknown`；当前 pending ref 的迟到 terminal 仍可能提交 hedge | unknown 后可能继续增加风险并留下孤立持仓 | 覆盖 cancel ACK 丢失、query live、安全重试、当前 ref partial/full late fill、duplicate terminal；unknown 期间只允许受控补偿 |
| V2-P0-005 | `confirm_remote_flat()` 没有运行时调用者，并只检查 position 为零 | 挂单、unknown intent 或晚到成交可使“空仓证明”失真 | 使用 Broker 公共、带 as-of/fence 的完整 reconcile snapshot；同时验证双侧仓位、挂单、unknown、账户与环境 |
| V2-P0-006 | 第一腿成交、第二腿失败时还没有 active pair，补偿路径费用和损失没有计入 realized economics | 失败交易的净收益和风险被高估 | 使用通用不可变 fill ledger，支持不等量与多次补偿；独立重算 gross、fee、funding、net 和最大裸腿损失 |
| V2-P0-007 | 两策略均没有可靠、重启后保持的账户累计损失预算；事件候选连单 pair loss stop 也没有 | 连续小亏、手续费和补偿亏损不会触发 kill switch | 账户执行 ledger/权益基线累计；触发后冻结新开仓、平仓、持久 fence；覆盖多笔累计损失 |
| V2-P0-008 | 事件策略 markout 样本缺失时 fail open，一个样本即可放行，missed ratio 不阻断，且不进入净边际 | 不利选择风险没有被统一成本门约束 | 冻结 horizon、最小样本、最大缺失率；未达标拒绝；将保守 adverse selection reserve 纳入同一成本 oracle |

## P1 缺口

1. funding 仍由开仓快照估算，没有结算账单；缺实际 funding 时 realized net 必须保持
   `INCOMPLETE`。
2. 012_1 入场用目标数量 L2 VWAP，出场用 BBO，统计口径不一致。
3. margin 和 funding-window 风险出口没有接到实际运行输入。
4. 首个 delta、`continuity_status=unknown` 或无有效 sequence 的盘口可能进入可交易状态。
5. 缺 callback 到 enqueue、ACK、fill、hedge 的完整时延与关联 ID 证据。现有纯引擎和私有
   enqueue 基准不能通过 HFT Gate。

## 正确保留的结论

- IOC limit 已改为 L2 marginal price 并按交易方向做 tick 取整。
- 基于实际四笔 fill 的 realized ledger 没有再次扣预测 reserve。
- 缺失或过期 qualification 会拒绝入场。
- 012_2 已降级命名为 `event_driven`，HFT 状态保持 `FAIL/NOT_ADMITTED`。
- 本审查不能证明策略盈利，也不批准任何双所 demo 写入。

所有 P0 必须有对应反例测试并通过第二轮独立复核，才允许把 G2 从 `FAIL` 改为 `PASS`。
