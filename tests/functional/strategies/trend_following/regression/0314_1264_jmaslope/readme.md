# 1264 JMASlope

## 策略概述

该策略是对 MT5 EA `1264_Exp_JMASlope` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为计算 `JMA` 斜率振荡器，并按默认 `breakdown` 模式在零轴突破时交易。

## 核心逻辑

1. 计算平滑价格线
2. 取当前平滑值与前值的差，形成 `JMASlope`
3. 默认 `breakdown` 模式下，在零轴突破时开仓或反手
4. 同时保留 `twist` 模式，支持按斜率方向翻转交易

## 主要参数

- `mode`
- `jlength`
- `jphase`
- `ipc`
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
