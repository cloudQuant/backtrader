# 0500 EMA 6.12

## 策略概述

该策略是对 MT5 EA `0500_EMA_6.12` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为 `SMA(6)` 与 `SMA(54)` 的交叉，配合固定止盈与移动止损。

## 核心逻辑

1. 计算快线 `SMA(6)` 与慢线 `SMA(54)`
2. 当快线向上穿越慢线时，仅在当前无持仓时做多
3. 当快线向下穿越慢线时，仅在当前无持仓时做空
4. 若持有反向仓位，则先按交叉信号平仓，不在同一根 bar 立即反手
5. 持仓期间启用固定止盈与按源码规则模拟的 trailing stop

## 主要参数

- `fast_period`
- `slow_period`
- `lot`
- `take_profit_pips`
- `trailing_stop_pips`
- `trailing_step_pips`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

 ## 当前回测结果

 - Trades: `187`
 - Net P&L: `+560`
 - Win Rate: `49.2%`
 - Profit Factor: `1.01`
 - Max Drawdown: `16.15%`

## 对齐说明

- 原 MT5 源码名为 `EMA 6.12(barabashkakvn's edition)`，但默认参数实际为 `6/54` 双均线交叉
- 当前迁移版本保留了“新 bar 才评估一次”的执行方式
- 原 EA 的 `TP/Trailing` 属于 tick 级撮合；当前版本基于 bar 级 `OHLC` 做近似回放
