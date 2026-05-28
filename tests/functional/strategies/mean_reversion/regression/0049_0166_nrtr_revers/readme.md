# 0166 NRTR_Revers

## 策略概述

该样例是对 MT5 EA `0166_NRTR_Revers` 的 Backtrader 迁移版。
EA 基于 `ATR` 波动阈值和一段窗口内的高低点来维护当前趋势状态；当价格对当前趋势产生足够幅度的反向突破时，切换趋势并执行平仓或反向开仓。

## 迁移思路

1. 在执行周期上计算 `ATR`
2. 维护与源码一致的 `Trade` 状态机，默认从 `buy` 状态启动
3. `buy` 状态下，用历史低点和 `ATR * coefficient` 形成反转线
4. `sell` 状态下，用历史高点和 `ATR * coefficient` 形成反转线
5. 满足 `different` 或 `reverse_pips` 条件时切换趋势
6. 保留固定止损、止盈与 trailing stop 主流程

## 主要参数

- `fixed_lot`
- `stoploss_pips`
- `takeprofit_pips`
- `trailing_stop_pips`
- `trailing_step_pips`
- `atr_period`
- `reverse_pips`
- `coeff_of_volatility`
- `initial_trade_state`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `3596`
- Net P&L: `-99930.00`
- Win Rate: `38.29%`
- Profit Factor: `0.91`
- Max Drawdown: `100.51%`

## 对齐说明

- 当前版本保留了源码的趋势状态切换、ATR 波动过滤、窗口高低点比较和 trailing 逻辑
- 原源码在已有持仓时更偏向“先平仓，再等待下一次条件触发”，当前迁移版本也保留这一语义，而不是强制同柱反手
- Backtrader 无法逐 tick 复刻 MT5 的成交与冻结级别校验，因此结果应视为可运行的逻辑迁移样例
