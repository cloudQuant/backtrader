# 1296 Center of Gravity

## 策略概述

该策略是对 MT5 EA `1296_Exp_CenterOfGravity` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为 `center` 线与 `signal` 线的颜色状态切换，并在状态翻转时入场或反手。

## 核心逻辑

1. 计算价格序列的 `SMA(period)` 与 `LWMA(period)`
2. 用 `SMA * LWMA / point` 构造 `center` 线
3. 对 `center` 再做一次平滑得到 `signal`
4. 当 `center >= signal` 时状态记为 `1`，当 `center < signal` 时状态记为 `2`
5. 状态从 `2 -> 1` 时做多，从 `1 -> 2` 时做空，并在反向信号时反手

## 主要参数

- `period`
- `smooth_period`
- `ma_method`
- `applied_price`
- `signal_bar`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `763`
- Net P&L: `+1,382.50`
- Win Rate: `37.35%`
- Profit Factor: `1.02`
- Max Drawdown: `6.44%`
