# 1275 OsHMA

## 策略概述

该策略是对 MT5 EA `1275_Exp_OsHMA` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为计算快慢 `HMA` 的差值直方图，并按默认 `twist` 模式在直方图方向翻转时交易。

## 核心逻辑

1. 计算快速 `HMA`
2. 计算慢速 `HMA`
3. 用 `fast_hma - slow_hma` 得到 `OsHMA` 直方图
4. 默认 `twist` 模式下，当直方图斜率由降转升或由升转降时开仓或反手
5. 同时保留 `zero_cross` 模式，支持按零轴穿越交易

## 主要参数

- `mode`
- `fast_hma`
- `slow_hma`
- `signal_bar`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `1015`
- Net P&L: `2,881.50`
- Win Rate: `46.80%`
- Profit Factor: `1.09`
- Max Drawdown: `2.57%`
