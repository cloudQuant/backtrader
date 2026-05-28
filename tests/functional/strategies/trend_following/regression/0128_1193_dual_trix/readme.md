# 1193 Dual TRIX Crossover

## 策略概述

该策略是对 MT5 EA `1193_Dual_Trix_EA_交易` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为快慢 TRIX 交叉，并结合固定止盈止损。

## 核心逻辑

1. 计算快 TRIX 与慢 TRIX
2. 快线向上穿越慢线时做多
3. 快线向下穿越慢线时做空
4. 使用固定 `SL / TP` 控制单笔交易风险
5. 反向交叉时可离场 / 反手

## 主要参数

- `fast_period`
- `slow_period`
- `sl_points`
- `tp_points`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `521`
- Net P&L: `-7,231`
- Win Rate: `36.5%`
- Profit Factor: `0.88`
- Max Drawdown: `13.57%`
