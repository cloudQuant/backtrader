# 013_1 中低频跨品种套利（豆粕 m / 菜粕 RM）

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

报告写入 stdout；合成回放与 SimNow 成交都不构成盈利证据。
