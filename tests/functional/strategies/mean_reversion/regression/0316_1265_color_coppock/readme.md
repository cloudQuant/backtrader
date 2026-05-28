# 1265 ColorCoppock

## 策略概述

该策略是对 MT5 EA `1265_Exp_ColorCoppock` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为计算 Coppock 振荡器并按主线方向翻转交易。

## 核心逻辑

1. 计算两段 `ROC` 之和
2. 对 `ROC` 和做一次平滑，得到 `Coppock`
3. 当振荡器方向由降转升或由升转降时开仓或反手

## 主要参数

- `roc1_period`
- `roc2_period`
- `xma_method`
- `xma_period`
- `xma_phase`
- `applied_price`
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
