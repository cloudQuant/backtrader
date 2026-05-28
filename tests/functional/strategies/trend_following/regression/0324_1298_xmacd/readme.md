# 1298 XMACD

## 策略概述

该策略是对 MT5 EA `1298_Exp_XMACD` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为快慢平滑均线差构成 `XMACD`，并以信号线关系决定入场与反手。

## 核心逻辑

1. 对价格序列计算快线与慢线平滑均线
2. 两者差值形成 `XMACD`
3. 再对 `XMACD` 进行平滑得到 `Signal`
4. 默认使用 `MACDdisposition` 模式，在 `XMACD` 与 `Signal` 金叉死叉时入场或反手
5. 也支持 `breakdown`、`MACDtwist`、`SIGNALtwist` 模式

## 主要参数

- `mode`
- `signal_bar`
- `ma_method`
- `signal_method`
- `fast_period`
- `slow_period`
- `signal_period`
- `applied_price`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `503`
- Net P&L: `-3,648`
- Win Rate: `39.36%`
- Profit Factor: `0.94`
- Max Drawdown: `9.69%`
