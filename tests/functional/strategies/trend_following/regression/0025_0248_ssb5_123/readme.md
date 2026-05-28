# 0248 ssb5_123

## 策略来源

- MT5 源码：`ea/0248_ssb5_123/ssb5_123.mq5`

## 策略逻辑

- EA 在新柱上检查一组顺序确认条件。
- 多头需要 `candle / AO / AO变化 / MACD / MACD变化 / OsMA变化 / SMMA位置 / Stochastic主线 / Stochastic信号线` 全部为非负。
- 空头需要同一组条件全部为非正。
- 若已有反向仓位，则先平仓，再在后续机会中反手。
- 原版没有固定 `SL/TP` 或 trailing，主要依赖信号反转来退出。
- 当前 backtrader 实现使用 `M15` 数据并重采样为 `H1` 做可运行验证。

## 与源码一致/差异说明

- 保留了多指标串行确认与反向信号先平后反手的主流程。
- 原说明示例为 `EURUSD H1`，仓库当前没有对应数据，因此这里使用 `XAUUSD_M15.csv` 并重采样为 `H1`。
- `OsMA` 使用 `MACD 主线 - 信号线` 近似，`SMMA` 使用 backtrader 的 `SmoothedMovingAverage`。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_ssb5_123.py`：策略实现。
- `run.py`：读取 `XAUUSD_M15.csv` 并重采样 `H1` 后回测。
- `config.yaml`：策略参数、数据区间和回测配置。
