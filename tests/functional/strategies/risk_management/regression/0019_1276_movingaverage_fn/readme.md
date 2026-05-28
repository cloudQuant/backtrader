# 1276 MovingAverage_FN

## 策略概述

该策略是对 MT5 EA `1276_Exp_MovingAverage_FN` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为对价格应用默认 `N44` 固定系数 FIR 滤波器，再做一层平滑，最后依据均线方向翻转产生交易信号。

## 核心逻辑

1. 从仓库内 `movingaverage_fn.mq5` 解析默认 `N44` FIR 系数
2. 对输入价格做固定系数数字滤波
3. 对滤波结果再做一层平滑得到最终均线
4. 当均线由下降转上升或由上升转下降时开仓或反手

## 主要参数

- `filter_number`
- `xma_method`
- `xlength`
- `xphase`
- `ipc`
- `signal_bar`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `244`
- Net P&L: `3,392.80`
- Win Rate: `45.90%`
- Profit Factor: `1.49`
- Max Drawdown: `0.98%`
