# 0140 MACD_无样品

## 策略概述

该样例是对 MT5 EA `0140_MACD_无样品` 的 Backtrader 迁移版。
原 EA 使用加权价格上的 MA 作为趋势方向过滤，再结合 MACD 在零轴一侧发生交叉的条件触发开仓；出现反向条件时，会先平掉对手仓再开新仓，并可选用 trailing stop。

## 迁移思路

1. 在 `M15` 数据上构造 `PRICE_WEIGHTED = (H + L + 2C) / 4`
2. 使用 `Weighted Moving Average` 作为趋势方向过滤
3. 当 MA 上行、MACD 位于零轴下方且主线向上穿越信号线、同时幅度大于阈值时做多
4. 当 MA 下行、MACD 位于零轴上方且主线向下穿越信号线、同时幅度大于阈值时做空
5. 保留“先平反向仓，再开新仓”的单净头寸近似，以及默认仅启用 trailing stop 的主流程

## 主要参数

- `fixed_lot`
- `trailing_stop_pips`
- `trailing_step_pips`
- `ma_period`
- `macd_fast_period`
- `macd_slow_period`
- `macd_signal_period`
- `macd_level_pips`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`./run.py`
- 绘图：`./run.py --plot`

## 当前回测结果

- Trades: `19`
- Net P&L: `-93606.00`
- Win Rate: `100.00%`
- Profit Factor: `None`
- Max Drawdown: `132.95%`

## 对齐说明

- 原 EA 使用 MetaTrader 的 `PRICE_WEIGHTED` 输入；当前版本显式构造 `(H + L + 2C) / 4` 价格序列
- 原 EA 通过 `m_need_open_buy/m_need_open_sell` 状态机先平反向仓再开仓；当前版本保留相同顺序的单净头寸近似
- 原 EA 默认 `StopLoss/TakeProfit=0` 且启用 trailing stop；当前版本保持这一默认设定
