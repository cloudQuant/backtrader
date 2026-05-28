# 1232 SuperTrend

## 策略概述

该策略是对 MT5 EA `1232_Exp_Kolier_SuperTrend` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为基于 ATR 的 SuperTrend 趋势翻转。

## 核心逻辑

1. 计算 ATR
2. 根据 `multiplier` 构建上下 SuperTrend 带
3. 价格站上趋势带时做多
4. 价格跌破趋势带时做空
5. 趋势带翻转时离场 / 反手

## 主要参数

- `atr_period`
- `multiplier`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `18`
- Net P&L: `+493`
- Win Rate: `44.4%`
- Profit Factor: `1.14`
- Max Drawdown: `10.63%`
