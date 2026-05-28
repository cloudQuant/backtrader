# 0108 iCHO_趋势_CCIDualOnMA_过滤器

## 策略概述

该样例是对 MT5 EA `0108_iCHO_趋势_CCIDualOnMA_过滤器` 的 Backtrader 迁移版。
原 EA 使用 `Chaikin Oscillator (CHO)` 作为趋势与过零平仓触发器，并使用 `CCIDualOnMA` 作为过滤器；同时支持时间控制、固定 `SL/TP`、trailing、`OnlyOne`、`Reverse` 与 `CloseOpposite`。

## 迁移思路

1. 重建 `CHO = EMA(ADL, fast) - EMA(ADL, slow)`
2. 重建 `CCIDualOnMA`：先对 `close` 求 `SMA(12)`，再对该均线分别计算 `CCI Fast` 与 `CCI Slow`
3. 保留 `CHO` 过零平仓/反向触发逻辑
4. 保留 `CCI` 交叉过滤信号
5. 采用 `OnlyOne + CloseOpposite` 约束为单净头寸迁移子集
6. 保留时间控制与固定 `SL/TP`、trailing 主流程

## 主要参数

- `stop_loss_points`
- `take_profit_points`
- `trailing_stop_points`
- `trailing_step_points`
- `cho_fast_period`
- `cho_slow_period`
- `cci_fast_period`
- `cci_slow_period`
- `ma_period`
- `trade_mode`
- `only_one_position`
- `reverse`
- `close_opposite`
- `use_time_control`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`./run.py`
- 绘图：`./run.py --plot`

## 当前回测结果

- Trades: `163`
- Net P&L: `-23769.00`
- Win Rate: `26.38%`
- Profit Factor: `1.00`
- Max Drawdown: `44.63%`

## 对齐说明

- 原 EA 支持多仓位添加与更灵活的交易模式；当前版本选择 `OnlyOne + CloseOpposite` 的单净头寸子集
- 原 EA 的 `CCIDualOnMA` 使用 `CCI(MA(close))` 结构；当前版本保留同样层次关系进行近似重建
- 原 EA 只允许每个工作 bar 产生一笔交易；当前版本同样按 bar 级节奏限制信号处理
