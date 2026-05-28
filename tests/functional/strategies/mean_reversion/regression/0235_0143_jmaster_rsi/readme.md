# 0143 jMaster_RSI

## 策略概述

该样例是对 MT5 EA `0143_jMaster_RSI` 的 Backtrader 迁移版。
原 EA 基于双周期的自定义平滑 RSI 指标与 H4 线性回归斜率过滤开仓，并在出现反向条件时平仓。默认参数下，止盈、止损和 trailing stop 模块均关闭，因此核心逻辑集中在趋势过滤与双 RSI 条件上。

## 迁移思路

1. 使用 `M5` 作为执行与短周期信号级别
2. 由同源数据重采样出 `M15` 长周期 RSI 与 `H4` 线性回归过滤
3. 用 `RSI(period) -> SMA(6)` 近似 `RSI Custom Smoothing` 指标主线
4. 当长周期平滑 RSI 高于 `long_buy_level`、短周期平滑 RSI 低于 `short_buy_level`，且两者满足原 EA 的趋势斜率比较时做多
5. 当长周期平滑 RSI 低于 `long_sell_level`、短周期平滑 RSI 高于 `short_sell_level`，且趋势比较满足时做空
6. 仅在 H4 线性回归绝对斜率大于阈值时允许开仓；反向条件出现时平仓

## 主要参数

- `fixed_lot`
- `long_timeframe_period`
- `short_timeframe_period`
- `long_buy_level`
- `short_buy_level`
- `long_sell_level`
- `short_sell_level`
- `long_trend_spread`
- `linreg_len`
- `linreg_trade_pips`
- `trade_trend`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M5.csv`
- 运行：`./run.py`
- 绘图：`./run.py --plot`

## 当前回测结果

- Trades: `0`
- Net P&L: `0.00`
- Win Rate: `0.00%`
- Profit Factor: `None`
- Max Drawdown: `0.00%`
- 说明：默认样本窗口内未出现满足原 EA 双 RSI 入场条件的 bar，因此没有触发开仓。

## 对齐说明

- 原 EA 使用 `RSI Custom Smoothing` 自定义指标；当前版本用 `RSI + SMA(6)` 近似其主缓冲区
- 原 EA 还支持多种 TP/SL/Trailing 模式；当前迁移先覆盖默认参数下关闭这些模块时的主交易流程
- 原 EA 使用 H4 线性回归通道宽度与斜率计算；当前版本保留实际用于开仓过滤的绝对斜率条件
