# 0271 Sensitive

## 策略来源

- MT5 源码：`ea/0271_Sensitive/sensitive.mq5`

## 策略逻辑

- EA 在新柱线上读取 `MACD` 主线与信号线。
- 买入条件：`main[0] < 0`、`main[0] > signal[0]`、`main[1] < signal[1]`，且 `abs(main[0]) > MACDOpenLevel * Point`。
- 卖出条件：`main[0] > 0`、`main[0] < signal[0]`、`main[1] > signal[1]`，且 `abs(main[0]) > MACDOpenLevel * Point`。
- 买入信号先平空后开多，卖出信号先平多后开空。
- 开仓附带固定 `SL/TP`，并在逐笔更新中执行 trailing stop。
- 当前 backtrader 实现直接使用 `M15` 数据回测。

## 与源码一致/差异说明

- 保留了 `MACD` 交叉阈值过滤、反手开平与 trailing 主流程。
- 当前使用 Backtrader 内置 `MACD` 计算线值。
- 原说明示例为 `EURUSD M15` / `USDJPY M15`，仓库当前没有对应数据，因此这里使用 `XAUUSD_M15.csv` 做可运行验证。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_sensitive.py`：策略实现。
- `run.py`：读取 `XAUUSD_M15.csv` 后回测。
- `config.yaml`：策略参数、数据区间和回测配置。
