# 1260 Color3rdGenXMA

## 策略概述

该策略是对 MT5 EA `1260_Exp_Color3rdGenXMA` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为使用 `Color3rdGenXMA` 颜色均线判断方向，并在固定开仓时点入场、持仓固定分钟数后离场。

## 核心逻辑

1. 计算第三代 XMA 主线
2. 根据主线相对上一柱的方向为均线着色
3. 在固定开仓时点，`2=蓝色多头`，`0=红色空头`
4. 入场后持有固定 `TimeMin` 分钟，再强制平仓

## 主要参数

- `start_hour`
- `start_minute`
- `time_min`
- `xma_method`
- `xlength`
- `xphase`
- `ipc`
- `shift`
- `price_shift`
- `signal_bar`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `0`
- Net P&L: `0.00`
- Win Rate: `0.00%`
- Profit Factor: `N/A`
- Max Drawdown: `0.00%`
