# 0167 Extreme_EA

## 策略概述

该样例是对 MT5 EA `0167_Extreme_EA` 的 Backtrader 迁移版。
EA 基于 `M15` 上的快慢均线斜率关系和 `M30 CCI` 过滤进行入场，并以慢线方向反转作为离场条件。当前迁移版在 Backtrader 中用单净头寸近似原版最多 `3` 笔同策略仓位的行为。

## 迁移思路

1. 在 `M15` 执行层上重建 `MA Fast` 和 `MA Slow`
2. 将同一份 `M15` 数据重采样到 `M30`，计算 `CCI(12)`
3. 将 `M30 CCI` 前向映射回 `M15` 执行层
4. 满足 `MA Slow` 方向、`MA Fast` 当前斜率与 `CCI` 阈值条件时入场
5. 当 `MA Slow` 失去原方向时离场；若反向入场条件同时成立，则执行反手
6. 保留固定止损、止盈与 trailing stop 主流程

## 主要参数

- `fixed_lot`
- `stoploss_pips`
- `takeprofit_pips`
- `trailing_stop_pips`
- `trailing_step_pips`
- `cci_period`
- `cci_up_level`
- `cci_down_level`
- `ma_fast_period`
- `ma_slow_period`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `95`
- Net P&L: `-772.20`
- Win Rate: `30.53%`
- Profit Factor: `0.74`
- Max Drawdown: `1.14%`

## 对齐说明

- 原版允许最多 `3` 笔同策略仓位；当前迁移版以单净头寸近似其持仓行为
- 当前实现保留 `M15 MA + M30 CCI` 的分层信号结构，而不是将所有指标压回同一时间框架
- Backtrader 无法逐 tick 复刻 MT5 的成交与冻结级别校验，因此结果应视为可运行的逻辑迁移样例
