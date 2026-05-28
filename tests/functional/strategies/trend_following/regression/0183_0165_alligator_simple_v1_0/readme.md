# 0165 Alligator_Simple_v1.0

## 策略概述

该样例是对 MT5 EA `0165_Alligator_Simple_v1.0` 的 Backtrader 迁移版。
EA 基于 `Alligator` 指标三条线的排序关系入场，并在任何时刻仅保持一笔仓位；出场主要由固定止损、止盈和 trailing stop 管理。

## 迁移思路

1. 使用 `median price` 作为基础价格构造 `SmoothedMovingAverage`
2. 分别重建 `jaw / teeth / lips` 三条线
3. 按源码主逻辑比较 `Lips#1`、`Teeth#1`、`Jaws#1` 的排序关系
4. 无持仓时，若 `lips > teeth > jaw` 则开多；若 `lips < teeth < jaw` 则开空
5. 持仓后交由固定止损、止盈和 trailing stop 管理

## 主要参数

- `fixed_lot`
- `stoploss_pips`
- `takeprofit_pips`
- `trailing_stop_pips`
- `trailing_step_pips`
- `every_tick`
- `jaw_period`
- `jaw_shift`
- `teeth_period`
- `teeth_shift`
- `lips_period`
- `lips_shift`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `1705`
- Net P&L: `-134557.00`
- Win Rate: `32.84%`
- Profit Factor: `0.81`
- Max Drawdown: `158.60%`

## 对齐说明

- 原 EA 允许 `Every tick` 模式；当前版本支持参数开关，但默认仍按新柱检查入场
- 当前实现保留“一次仅一笔仓位”的核心语义，因此兼容 Backtrader 单净头寸模型
- Backtrader 无法逐 tick 复刻 MT5 的成交与冻结级别校验，因此结果应视为可运行的逻辑迁移样例
