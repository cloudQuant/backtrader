# 0142 日交易_PAMXA

## 策略概述

该样例是对 MT5 EA `0142_日交易_PAMXA` 的 Backtrader 迁移版。
原 EA 结合 `D1` 级别的 `Awesome Oscillator` 与 `H1` 级别的 `Stochastic` 形成两阶段信号：先由高周期 AO 过零给出方向，再由低周期随机指标进入阈值区确认入场，并保持单仓位状态机。

## 迁移思路

1. 在同一份 `M15` 数据上重采样得到 `H1` 与 `D1`
2. 当 `AO[-2] < 0` 且 `AO[-1] > 0` 时，视为买入方向激活
3. 若此时 `Stochastic` 主线或信号线低于 `sto_level_down`，则做多
4. 当 `AO[-2] > 0` 且 `AO[-1] < 0` 时，视为卖出方向激活
5. 若此时 `Stochastic` 主线或信号线高于 `sto_level_up`，则做空
6. 保留“先平反向仓，再开新仓”的单净头寸近似，以及固定 SL/TP 与 trailing stop

## 主要参数

- `fixed_lot`
- `stop_loss_pips`
- `take_profit_pips`
- `trailing_stop_pips`
- `trailing_step_pips`
- `sto_k_period`
- `sto_d_period`
- `sto_slowing`
- `sto_level_up`
- `sto_level_down`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`./run.py`
- 绘图：`./run.py --plot`

## 当前回测结果

- Trades: `0`
- Net P&L: `0.00`
- Win Rate: `0.00%`
- Profit Factor: `None`
- Max Drawdown: `0.00%`
- 说明：默认样本窗口内未出现 `D1 AO` 过零穿越，因此两阶段开仓条件未被触发。

## 对齐说明

- 原 EA 运行于当前图表周期，并从 `D1/H1` 指标句柄读取上级别信号；当前版本用同源 `M15` 数据重采样得到 `H1/D1`
- 原 EA 用 `m_need_open_buy/m_need_open_sell` 状态机先平反向仓再开仓；当前版本保留相同顺序的单净头寸近似
- 原 EA 的 trailing stop 逐 tick 更新；当前版本按 bar close 近似更新
