# 1294 2pbIdealXOSMA

## 策略概述

该策略是对 MT5 EA `1294_Exp_2pbIdealXOSMA` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为先构造 `2pbIdeal` 平滑快线与三段平滑慢线之差，再对该振荡值做平滑，并在指标形成拐点时入场或反手。

## 核心逻辑

1. 对价格序列计算一组 `IdealMA` 风格的双参数平滑快线
2. 再通过三段双参数平滑串联得到慢线
3. 用 `fast - slow` 构造振荡值，并对其做进一步平滑
4. 当 `SignalBar` 位置的指标形成局部低点后向上拐头时做多
5. 当 `SignalBar` 位置的指标形成局部高点后向下拐头时做空，并在反向信号时反手

## 主要参数

- `signal_bar`
- `period1`
- `period2`
- `periodx1`
- `periodx2`
- `periody1`
- `periody2`
- `periodz1`
- `periodz2`
- `smooth_method`
- `smooth_period`
- `smooth_phase`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `318`
- Net P&L: `+8,800.00`
- Win Rate: `42.14%`
- Profit Factor: `1.23`
- Max Drawdown: `7.00%`
