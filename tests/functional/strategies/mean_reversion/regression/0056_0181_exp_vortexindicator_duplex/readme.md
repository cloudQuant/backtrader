# 0181 Exp_VortexIndicator_Duplex

## 策略概述

该样例是对 MT5 EA `0181_Exp_VortexIndicator_Duplex` 的 Backtrader 迁移版。
EA 使用 `VortexIndicator` 的多空交叉信号驱动两套独立的 long / short 交易子系统；当前迁移版保留了独立的多空开平仓许可、止损止盈和仓位参数，并用 Backtrader 的单净头寸模型近似原 EA 的双魔术号结构。

## 迁移思路

1. 将 `XAUUSD_M15.csv` 重采样为 `H4`，对应源码默认 `InpInd_Timeframe=PERIOD_H4`
2. 按指标源码重建 `VI+` / `VI-`
3. 多头开仓：`VI+` 从不高于 `VI-` 变为高于 `VI-`
4. 多头平仓：空头信号子系统触发反向条件时关闭多单
5. 空头开仓：`VI+` 从不低于 `VI-` 变为低于 `VI-`
6. 空头平仓：多头信号子系统触发反向条件时关闭空单
7. 默认保留源码中的 `1000 / 2000` 点止损止盈

## 主要参数

- `indicator_minutes`
- `vortex_period`
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
- Net P&L: `+14.80`
- Win Rate: `38.46%`
- Profit Factor: `1.01`
- Max Drawdown: `0.80%`

## 对齐说明

- 原 EA 允许 long / short 两套系统分别配置不同参数，并通过不同魔术号独立管理；当前 Backtrader 版本保留独立参数入口，但以单净头寸近似持仓层面的执行语义
- 原 EA 默认 long / short 的指标周期与参数对称，因此当前样例先使用共享的 `H4 + period=14` 信号骨架
- Backtrader 无法逐 tick 复刻 MT5 的服务器侧成交细节与挂单修改限制，因此结果应视为可运行的逻辑迁移样例
