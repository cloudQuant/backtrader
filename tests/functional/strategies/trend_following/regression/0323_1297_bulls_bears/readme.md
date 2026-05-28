# 1297 Bulls / Bears Power

## 策略概述

该策略是对 MT5 EA `1297_Exp_BullsBears` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为 Elder Bulls Power / Bears Power 相对于 EMA 的强弱切换。

## 核心逻辑

1. 计算 `EMA(ema_period)`
2. 由价格与 EMA 的偏离计算 Bulls Power 与 Bears Power
3. Bulls Power 占优时偏多，Bears Power 占优时偏空
4. 强弱关系反转时平仓或反手

## 主要参数

- `ema_period`
- `lot`
- `point`
- `price_digits`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `914`
- Net P&L: `+3,622`
- Win Rate: `38.2%`
- Profit Factor: `1.06`
- Max Drawdown: `4.94%`
