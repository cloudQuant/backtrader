# 1188 2MA + RSI

## 策略概述

该策略是对 MT5 EA `1188_2MA_RSI` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为双均线交叉配合 RSI 超买超卖过滤。

## 核心逻辑

1. 计算快均线与慢均线
2. 当快线向上穿越慢线，且 RSI 未进入极端超买区域时做多
3. 当快线向下穿越慢线，且 RSI 未进入极端超卖区域时做空
4. 交叉失效或 RSI 条件反向时离场

## 主要参数

- `fast_period`
- `slow_period`
- `rsi_period`
- `rsi_overbought`
- `rsi_oversold`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `7`
- Net P&L: `+305`
- Win Rate: `71.4%`
- Profit Factor: `3.24`
- Max Drawdown: `0.14%`
