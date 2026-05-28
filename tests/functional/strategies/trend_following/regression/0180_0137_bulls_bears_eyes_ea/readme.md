# 0137 BullsBearsEyes_EA

## 策略概述

该样例是对 MT5 EA `0137_BullsBearsEyes_EA` 的 Backtrader 迁移版。
原 EA 基于自定义 `BullsBearsEyes` 指标：当上一根已收盘 bar 的指标值等于 `0.0` 时做多，等于 `1.0` 时做空；若持有反向仓位，则先平仓再开新仓，并支持时间窗口、止损、止盈和 trailing stop。

## 迁移思路

1. 用 `EMA` 构造 `Bulls Power` 与 `Bears Power`
2. 按原指标中的四级递归平滑公式重建 `BullsBearsEyes`
3. 当指标值接近 `0.0` 时做多，接近 `1.0` 时做空
4. 保留“先平反向仓，再开新仓”的单净头寸近似
5. 仅在配置的交易时段内允许新开仓，并保留 SL/TP/trailing 主流程

## 主要参数

- `fixed_lot`
- `stop_loss_pips`
- `take_profit_pips`
- `trailing_stop_pips`
- `trailing_step_pips`
- `indicator_period`
- `gamma`
- `use_time_control`
- `start_hour`
- `end_hour`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`./run.py`
- 绘图：`./run.py --plot`

## 当前回测结果

- Trades: `236`
- Net P&L: `-13325.00`
- Win Rate: `36.02%`
- Profit Factor: `0.80`
- Max Drawdown: `16.98%`

## 对齐说明

- 原 EA 通过 `iCustom(BullsBearsEyes)` 读取自定义指标；当前版本直接在 Backtrader 中重建其递归公式
- 原 EA 使用 `custom[1] == 0.0 / 1.0` 作为开仓信号；当前版本用接近阈值的判断来避免浮点误差
- 源码中 `InpTimeControl/InpStartHour/InpEndHour` 体现为日内交易时段约束；当前版本将其作为开仓时间窗口保留
