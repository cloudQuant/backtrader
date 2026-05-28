# 1269 EF_distance

## 策略概述

该策略是对 MT5 EA `1269_Exp_EF_distance` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为用 `EF_distance` 计算价格能量加权均值，再依据该均值方向翻转交易，并用 `Flat-Trend` 做入场过滤。

## 核心逻辑

1. 计算 `EF_distance` 能量加权均线
2. 当均线方向由降转升或由升转降时开仓或反手
3. 仅在 `Flat-Trend` 状态满足波动等级阈值时允许开仓
4. 平仓不受波动过滤约束

## 主要参数

- `xlength`
- `power`
- `ipc`
- `signal_bar`
- `stdev_period`
- `stdev_method`
- `stdev_length`
- `atr_period`
- `atr_method`
- `atr_length`
- `volatil`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `1193`
- Net P&L: `181.30`
- Win Rate: `48.28%`
- Profit Factor: `1.01`
- Max Drawdown: `2.77%`
