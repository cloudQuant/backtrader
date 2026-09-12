# 013_1 中低频跨品种套利（豆粕 m / 菜粕 RM）

> **历史参考示例（legacy-reference）**：本示例无归属需求/验收文档，定位为历史参考，
> 已知缺陷见迭代23 基线 B03（`_limit()` 盘口缺失回退 close、按品种前缀猜平仓 offset、
> 订单超时依赖数据时钟）与迭代26 验收报告 A8/A10；处置决策见
> [ADR-013-legacy-reference](../../docs/_internal/opts/requirements/迭代26-迭代20-21-22验收/ADR-013-legacy-reference.md)。
> **勿作新模板**；新开发请以 `013_3`/`014_1`/`014_2`/`015` 的目录独立性与 fail-closed 模式为准。

三件套结构：`strategy.py`（策略逻辑）+ `config.yaml`（配置）+ `run.py`（接线）。
策略信号完全复用 Backtrader 框架能力：`bt.indicators.SpreadZScore`
（本迭代新增于 `backtrader/indicators/spread.py`）在 `next()` 中给出双腿价差
z-score；限价参考 `notify_tick` 缓存的买卖一档。SimNow 接线复用
`examples/007_ctp/ctp_example_support.py`。

- 标的：m 主力 × RM 主力（`run.py` 按交割月历自动识别，郑商所三位代码如 `RM701`；
  `--symbols` 或 yaml `symbols` 可覆盖）
- 信号：价差 z-score 突破 ±2σ 开仓（三次确认、间隔 5s），回归 0.5σ/超时 30min/亏损平仓
- 执行：逐腿顺序限价 IOC；先空腿、按第一腿实际成交量提交多腿；裸腿立即反向平掉；
  平仓 offset 按交易所规则（上期所 `close_today`，大商所/郑商所 `close`）

```bash
# 合成 tick 回放（无需网络/凭据）：profitable / loss / no_edge
python examples/013_1_midfreq_cross_arbitrage/run.py --replay --scenario profitable

# SimNow 7x24 实盘模拟（凭据见 SIMNOW_USER_ID/SIMNOW_PASSWORD，同 007 约定）
python examples/013_1_midfreq_cross_arbitrage/run.py --config config.yaml
```

每次运行都会挂载通用的 `bt.observers.TradeLogger`：它实时汇总订单、成交、持仓、资金和
事件计数，并在结束时冻结报告；本策略只以 `pair_arbitrage` 扩展补充配对状态、风控和业务
字段。运行中可调用 `strategy.stats.trade_logger.snapshot()` 查看该扩展；策略只从 broker 的
本地 `get_cached_report_state()` 读取持仓和资金，不会因生成报告刷新 CTP 账户。最终 JSON 同时
保留完整 `trade_logger` 遥测，并给出排除该易变遥测和进程全局订单引用的
`business_summary` 与 `business_summary_hash`，可用于等价 replay 的稳定比对。发布失败后重试按
最近一次尝试的 tick 水位节流；若停止时最后成功快照之后仍有发布失败，runner 会拒绝该陈旧扩展。
报告写入 stdout；合成回放与 SimNow 成交都不构成盈利证据。
