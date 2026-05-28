# 0247 横盘趋势 EA

## 策略来源

- MT5 源码：`ea/0247_横盘趋势_EA/flat_trend_ea.mq5`
- 指标源码：`ea/0247_横盘趋势_EA/flattrend.mq5`

## 策略逻辑

- EA 基于 `FlatTrend` 四个缓冲区信号交易：`Sell`、`Buy`、`End Sell`、`End Buy`。
- 在允许交易时间窗口内，出现 `Buy=1.0` 时开多，出现 `Sell=1.0` 时开空。
- `Buy`、`End Sell`、`End Buy` 会触发空头平仓；`Sell`、`End Sell`、`End Buy` 会触发多头平仓。
- 开仓附带固定 `SL/TP`。
- `Trailing Stop` 持续工作。
- 当前 backtrader 实现使用 `M15` 作为执行与信号周期。

## 与源码一致/差异说明

- 保留了 `FlatTrend` 的四缓冲区信号、交易时间窗口、固定 `SL/TP` 和持续 trailing stop 主流程。
- 当前版本按本地指标源码，用 `Parabolic SAR + DI+/DI-` 的组合关系近似还原 `FlatTrend` 四个缓冲区。
- 原说明示例为 `EURUSD M15`，仓库当前没有对应数据，因此这里使用 `XAUUSD_M15.csv` 做可运行验证。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_flat_trend_ea.py`：指标与策略实现。
- `run.py`：读取 `XAUUSD_M15.csv` 后回测。
- `config.yaml`：策略参数、数据区间和回测配置。
