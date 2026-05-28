# 0136 EMA_LWMA_RSI

## 策略概述

该样例是对 MT5 EA `0136_EMA_LWMA_RSI` 的 Backtrader 迁移版。
原 EA 使用同一价格输入上的 `EMA` 与 `LWMA` 均线交叉，再结合 `RSI` 是否位于 `50` 上下作为方向过滤；策略每次只保留一笔净头寸，买入信号同时作为空头平仓信号，卖出信号同时作为多头平仓信号。

## 迁移思路

1. 在单一执行周期上构造 `PRICE_WEIGHTED = (H + L + 2C) / 4`
2. 用 `EMA(28)` 与 `LWMA(8)` 的交叉作为主信号
3. 用 `RSI(14)` 是否高于或低于 `50` 作为方向过滤
4. 保留“先平反向仓，再开新仓”的单净头寸管理方式
5. 保留默认参数下的固定 SL / TP 主流程

## 主要参数

- `fixed_lot`
- `stop_loss_pips`
- `take_profit_pips`
- `ema_period`
- `lwma_period`
- `rsi_period`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`./run.py`
- 绘图：`./run.py --plot`

## 当前回测结果

- Trades: `243`
- Net P&L: `-14265.00`
- Win Rate: `26.75%`
- Profit Factor: `0.84`
- Max Drawdown: `29.24%`

## 对齐说明

- 原 EA 的 `MA` 与 `RSI` 都使用 `PRICE_WEIGHTED`；当前版本显式构造 `(H + L + 2C) / 4` 价格序列
- 原 EA 在新 bar 上检测 `EMA/LWMA` 交叉并用 `RSI 50` 过滤；当前版本保留相同条件组合
- 原 EA 允许常量或风险手数；当前版本先覆盖固定手数下的主策略逻辑
