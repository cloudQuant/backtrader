# 0273 1H EUR_USD

## 策略来源

- MT5 源码：`ea/0273_1H_EUR_USD/1h_eur_usd.mq5`

## 策略逻辑

- 结合两条均线、`MACD` 拐点与最近高低点突破判断入场。
- 多头：`MA First > MA Second`，`MACD` 在负值区形成局部低点，且当前价突破前 1-2 根高点。
- 空头：`MA First < MA Second`，`MACD` 在正值区形成局部高点，且当前价跌破前 1-2 根低点。
- 开仓附带固定 `SL/TP`，并在逐笔更新中执行 trailing stop。
- 当前 backtrader 实现直接使用 `M15` 数据回测。

## 与源码一致/差异说明

- 保留了 `MA + MACD + 最近高低点突破` 的主流程与 trailing 行为。
- 原说明示例为 `EURUSD H1`，仓库当前没有对应数据，因此这里使用 `XAUUSD_M15.csv` 做可运行验证。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_1h_eur_usd.py`：策略实现。
- `run.py`：读取 `XAUUSD_M15.csv` 后回测。
- `config.yaml`：策略参数、数据区间和回测配置。
