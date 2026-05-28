# 0499 ichimok2005

## 策略概述

该策略是对 MT5 EA `0499_ichimok2005` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为 Ichimoku 云层方向配合上一根 K 线实体方向，在云层内部触发入场，并设置固定止损与止盈。

## 核心逻辑

1. 计算 Ichimoku 的 `Senkou Span A/B`
2. 使用上一根已完成 K 线作为信号判断对象
3. 当 `Span A > Span B` 且前一根为阳线、收盘落在 `Span B` 与 `Span A` 之间时做多
4. 当 `Span B > Span A` 且前一根为阴线、收盘落在 `Span A` 与 `Span B` 之间时做空
5. 持仓使用固定 `SL/TP` 管理，出现反向信号时按净头寸模型近似反手

## 主要参数

- `tenkan`
- `kijun`
- `senkou`
- `lot`
- `stop_loss_pips`
- `take_profit_pips`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

 ## 当前回测结果

 - Trades: `280`
 - Net P&L: `-1,698.10`
 - Win Rate: `50.0%`
 - Profit Factor: `0.80`
 - Max Drawdown: `2.57%`

## 对齐说明

- 原 EA 在 MT5 对冲模型下可连续加同向仓位；当前版本在 Backtrader 中按净头寸模型近似
- 原 EA 读取的是 `iIchimoku(..., shift=1)` 与上一根 `Open/Close`，当前迁移版本保持相同的“上一根 bar 触发当前 bar 执行”语义
- 原 EA 的 `SL/TP` 为经纪商侧价格单；当前版本基于 bar 级 `OHLC` 做近似回放
