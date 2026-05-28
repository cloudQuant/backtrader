# 0279 Russian20-hp1

## 策略来源

- MT5 源码：`ea/0279_Russian20-hp1/russian20-hp1.mq5`

## 策略逻辑

- 若当前无持仓，则检查开仓条件。
- 多头：`close > MA`、`Momentum > 100`、且 `close > close[-1]`。
- 空头：`close < MA`、`Momentum < 100`、且 `close < close[-1]`。
- 持有多头时，`Momentum < 100` 则平仓。
- 持有空头时，`Momentum > 100` 则平仓。
- 买卖方向分别使用独立的 `SL/TP` 参数。
- 当前 backtrader 实现默认按新柱模式运行。

## 与源码一致/差异说明

- 保留了 `MA + Momentum` 的开平仓主流程与独立买卖 `SL/TP` 设置。
- 源码还支持 `every tick` 模式与独立 work timeframe；当前实现先使用单数据流近似验证可运行性。
- 原说明示例为 `EURUSD`，仓库当前没有对应数据，因此这里使用 `XAUUSD_M15.csv` 做可运行验证。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_russian20_hp1.py`：策略实现。
- `run.py`：读取 `XAUUSD_M15.csv` 后回测。
- `config.yaml`：策略参数、数据区间和回测配置。
