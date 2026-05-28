# 1263 TrendContinuation

## 策略概述

该策略是对 MT5 EA `1263_Exp_TrendContinuation` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为比较 `TrendContinuation` 指标的 `Up` / `Down` 双缓冲区，在两者交叉时交易。

## 核心逻辑

1. 统计价格变化的正负累积结构
2. 形成 `TrendContinuation` 的 `Up` 与 `Down` 双序列
3. 当 `Up` 与 `Down` 的相对位置发生翻转时开仓或反手

## 主要参数

- `nperiod`
- `xmethod`
- `xperiod`
- `xphase`
- `ipc`
- `signal_bar`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `365`
- Net P&L: `-1190.10`
- Win Rate: `50.96%`
- Profit Factor: `0.90`
- Max Drawdown: `2.74%`
