# 0488 Larry_Conners_RSI_2

## 策略概述

该策略是对 MT5 EA `0488_Larry_Conners_RSI_2` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为使用 `MA200` 判断大趋势，利用 `RSI(2)` 捕捉短期超买超卖反转，并使用 `MA5` 作为离场条件。

## 核心逻辑

1. 计算 `SMA(5)`、`SMA(200)` 和 `RSI(2)`
2. 多头入场：`RSI(2)[1] < 6` 且 `close[1] > SMA(200)[1]`
3. 空头入场：`RSI(2)[1] > 95` 且 `close[1] < SMA(200)[1]`
4. 多头离场：`close[1] > SMA(5)[1]`
5. 空头离场：`close[1] < SMA(5)[1]`
6. 可选固定 `SL/TP` 与单仓约束

## 主要参数

- `lot`
- `short_sma_periods`
- `long_sma_periods`
- `rsi_periods`
- `rsi_long_entry`
- `rsi_short_entry`
- `use_stop_loss`
- `stop_loss_pips`
- `use_take_profit`
- `take_profit_pips`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

 ## 当前回测结果

 - Trades: `173`
 - Net P&L: `+3,747.00`
 - Win Rate: `47.98%`
 - Profit Factor: `1.06`
 - Max Drawdown: `13.29%`

## 对齐说明

- 原 EA 不显式做“仅新 bar 一次”的时间门控，而是依赖单仓约束避免重复入场；当前版本在 bar 级回测下保持单仓逻辑
- 原 EA 会根据交易商最小止损距离调整 `SL/TP`；当前版本直接使用配置中的固定距离做近似
- 原 EA 在说明中推荐 `EURUSD H1`；当前示例按仓库统一基准数据 `XAUUSD M15` 回测
