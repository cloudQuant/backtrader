# 0105 波段_R_平方

## 策略概述

该样例是对 MT5 EA `0105_波段_R_平方` 的 Backtrader 迁移版。
原 EA 基于布林线反向穿越形态和东契安通道方向过滤，在 `ATR` 派生的固定 `SL/TP` 下交易；此外源码中还包含权益曲线 `R^2` 统计，但不影响实际入场出场逻辑。

## 迁移思路

1. 使用 `Bollinger Bands(period=100, dev=1)` 检查前一根 K 线的反向穿越形态
2. 使用 `Donchian Channel(period=100)` 判断通道方向
3. 若下轨持续上升，则允许做多；若上轨持续下降，则允许做空
4. `SL/TP` 采用 `ATR(21) * 4`
5. 持仓后若价格再次突破东契安通道上下轨，则强制平仓

## 主要参数

- `lots`
- `b_period`
- `b_deviation`
- `donch_period`
- `c_period`
- `atr_period`
- `stop_atr`
- `take_atr`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`./run.py`
- 绘图：`./run.py --plot`

## 当前回测结果

- Trades: `17`
- Net P&L: `-6402.06`
- Win Rate: `17.65%`
- Profit Factor: `0.17`
- Max Drawdown: `7.52%`

## 对齐说明

- 原 EA 每根新 bar 只做一次判定；当前版本同样按 bar 级节奏运行
- 原 EA 使用东契安上下轨单边趋势过滤；当前版本保留同一过滤思想
- 原 EA 的 `R^2` 统计只做日志输出，不影响交易；当前版本未迁移该统计输出
