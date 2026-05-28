# 0110 MA_趋势_2

## 策略概述

该样例是对 MT5 EA `0110_MA_趋势_2` 的 Backtrader 迁移版。
原 EA 基于单根延迟 MA 参考值生成方向信号，并支持 `OnlyOne`、`Reverse`、`CloseOpposite`、固定 `SL/TP` 与 trailing stop 等参数。

## 迁移思路

1. 使用 `PRICE_WEIGHTED` 构造加权价格输入
2. 重建 `LWMA(12)` 主线
3. 用 `ma_shift=3` 近似原 EA 的水平平移参考
4. 采用 `only_one_position=true` 与 `close_opposite=true` 约束为单净头寸模式
5. 保留固定 `SL/TP` 与 trailing stop 主流程

## 主要参数

- `fixed_lot`
- `stop_loss_pips`
- `take_profit_pips`
- `trailing_stop_pips`
- `trailing_step_pips`
- `ma_period`
- `ma_shift`
- `type_trading`
- `only_one_position`
- `reverse`
- `close_opposite`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`./run.py`
- 绘图：`./run.py --plot`

## 当前回测结果

- Trades: `579`
- Net P&L: `-99990.00`
- Win Rate: `27.98%`
- Profit Factor: `0.71`
- Max Drawdown: `100.66%`

## 对齐说明

- 原 EA 允许单双向与多种持仓模式；当前版本选择 `OnlyOne + CloseOpposite` 的单净头寸子集进行迁移
- 原 EA 使用 `PRICE_WEIGHTED + LWMA + ma_shift` 产生信号；当前版本保留同样的指标构成，并对位移做近似映射
- 原 EA 在新 bar 上产生信号，并在持仓阶段管理 trailing；当前版本保持相同节奏
