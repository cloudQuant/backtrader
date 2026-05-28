# 1253 BrakeExp

## 策略概述

该策略是对 MT5 EA `1253_Exp_BrakeExp` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为根据 `BrakeExp` 指标的大色点与趋势缓冲区执行开仓和平仓。

## 核心逻辑

1. 使用指数型轨迹 `BrakeExp` 跟踪当前多空状态
2. 轨迹被价格反向击穿时，趋势状态翻转
3. 翻转当柱生成大色点信号，用于开仓或反手
4. 若当前处于单边趋势但无新大点，EA 仍会按趋势缓冲区触发反向持仓平仓

## 主要参数

- `a`
- `b`
- `signal_bar`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `172`
- Net P&L: `-1908.70`
- Win Rate: `44.77%`
- Profit Factor: `0.76`
- Max Drawdown: `2.48%`
