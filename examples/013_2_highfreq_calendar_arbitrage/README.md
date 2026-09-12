# 013_2 高频跨期套利（螺纹钢 rb 主力 / 次主力）

> **历史参考示例（legacy-reference）**：本示例无归属需求/验收文档，定位为历史参考，
> 已知缺陷见迭代23 基线 B03 与迭代26 验收报告 A8/A9/A10；处置决策见
> [ADR-013-legacy-reference](../../docs/_internal/opts/requirements/迭代26-迭代20-21-22验收/ADR-013-legacy-reference.md)。
> **勿作新模板**；新开发请以 `013_3`/`014_1`/`014_2`/`015` 的目录独立性与 fail-closed 模式为准。

三件套结构：`strategy.py` + `config.yaml` + `run.py`（与 013_1 同构，参数更激进）。
信号与接线同样复用框架：`bt.indicators.SpreadZScore` 与
`examples/007_ctp/ctp_example_support.py`。

- 标的：rb 最近两个满足到期保护的季月（如 `rb2701`/`rb2705`；`--symbols` 可覆盖）
- 信号：价差 z-score 突破 ±1.5σ 开仓（单次确认、间隔 0.1s），回归 0.3σ/超时 120s 平仓
- 执行：同 013_1 的逐腿限价 IOC 纪律；rb 为上期所品种，平仓用 `close_today`

> 命名口径（与迭代21 FR-HFT-005 名称门一致）：本示例**不具备也不宣称 HFT 能力**。
> "高频"仅指事件驱动 + 激进参数；CTP 下单为 TCP 往返，无端到端时延、队列位置或
> 真实成交证据支持任何高频能力宣称。

```bash
python examples/013_2_highfreq_calendar_arbitrage/run.py --replay --scenario profitable
python examples/013_2_highfreq_calendar_arbitrage/run.py --config config.yaml
```

每次运行都会挂载通用的 `bt.observers.TradeLogger`：它实时汇总订单、成交、持仓、资金和
事件计数，并在结束时冻结报告；本策略只以 `pair_arbitrage` 扩展补充配对状态、风控和业务
字段。运行中可调用 `strategy.stats.trade_logger.snapshot()` 查看该扩展；策略只从 broker 的
本地 `get_cached_report_state()` 读取持仓和资金，不会因生成报告刷新 CTP 账户。为避免高频路径
每个 tick 都序列化完整状态，领域扩展会在订单/状态转换时立即更新，并最多每 128 个 tick 刷新一次
计数；发布失败也按最近一次尝试的 tick 水位重试，不能退化为逐 tick 序列化。最终 JSON 同时保留
完整 `trade_logger` 遥测，并给出排除该易变遥测和进程全局订单引用的 `business_summary` 与
`business_summary_hash`，可用于等价 replay 的稳定比对。若停止时最后成功快照之后仍有发布失败，
runner 会拒绝该陈旧扩展。合成回放与 SimNow 成交都不构成盈利证据。
