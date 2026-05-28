# 0044 WPR + Bollinger Bands + ATR

## 策略概述

该策略是对 MT5 EA `0044_基于_WPR、布林带和_ATR_指标的简单专家顾问工具` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为 Williams %R 超买超卖信号配合 Bollinger 中轨过滤，并用 ATR/布林宽度设置止盈止损。

## 核心逻辑

1. 计算 `Williams %R`
2. 计算 `Bollinger Bands`
3. 计算 `ATR`
4. 当 WPR 从超卖区域回升，且价格位于布林中轨下方时做多
5. 当 WPR 从超买区域回落，且价格位于布林中轨上方时做空
6. 使用 ATR 与布林带宽度组合设置止损 / 止盈

## 主要参数

- `wpr_period`
- `wpr_overbought`
- `wpr_oversold`
- `bb_period`
- `bb_dev`
- `atr_period`
- `sl_mult`
- `tp_mult`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `294`
- Net P&L: `-14,154`
- Win Rate: `59.9%`
- Profit Factor: `0.69`
- Max Drawdown: `17.78%`
