# 0182 Exp_ColorMETRO_Duplex

## 策略概述

该样例是对 MT5 EA `0182_Exp_ColorMETRO_Duplex` 的 Backtrader 迁移版。
EA 使用 `ColorMETRO` 指标的两条云边界线进行多空切换，并为 long / short 两套系统分别保留开平仓许可、止损止盈和仓位参数。当前迁移版以单净头寸近似原 EA 的双魔术号结构。

## 迁移思路

1. 将 `XAUUSD_M15.csv` 重采样为 `H4`，对应源码默认 `InpInd_Timeframe=PERIOD_H4`
2. 按指标源码重建 `RSI + 双步长阶梯云` 的 `MPlus/MMinus`
3. 多头开仓：`MPlus` 从不高于 `MMinus` 变为高于 `MMinus`
4. 空头开仓：`MPlus` 从不低于 `MMinus` 变为低于 `MMinus`
5. 当反向子系统触发时关闭当前持仓，并在许可条件下反手
6. 默认保留源码中的 `1000 / 2000` 点止损止盈

## 主要参数

- `indicator_minutes`
- `period_rsi`
- `step_size_fast`
- `step_size_slow`
- `l_signal_bar`
- `s_signal_bar`
- `l_stop_loss_points`
- `l_take_profit_points`
- `s_stop_loss_points`
- `s_take_profit_points`
- `l_mm`
- `s_mm`
- `l_pos_open`
- `l_pos_close`
- `s_pos_open`
- `s_pos_close`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `39`
- Net P&L: `-3383.10`
- Win Rate: `17.95%`
- Profit Factor: `0.33`
- Max Drawdown: `3.58%`

## 对齐说明

- 原 EA 通过两个魔术号独立管理多空子系统；当前 Backtrader 版本保留独立多空参数，但以单净头寸近似执行
- 原指标与 EA 默认 long / short 参数对称，因此当前样例先以一套 `H4` 指标信号同时驱动多空方向
- Backtrader 无法逐 tick 复刻 MT5 的服务器侧成交与订单检查细节，因此结果应视为可运行的逻辑迁移样例
