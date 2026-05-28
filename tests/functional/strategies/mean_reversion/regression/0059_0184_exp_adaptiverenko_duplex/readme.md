# 0184 Exp_AdaptiveRenko_Duplex

## 策略概述

该样例是对 MT5 EA `0184_Exp_AdaptiveRenko_Duplex` 的 Backtrader 迁移版。
EA 基于 `AdaptiveRenko` 的趋势缓冲区为 long / short 两套子系统分别生成入场和离场信号。当前迁移版保留独立的多空开平仓许可、止损止盈和仓位参数，并用单净头寸近似原 EA 的双魔术号执行结构。

## 迁移思路

1. 将 `XAUUSD_M15.csv` 重采样为 `H4`，对应源码默认 `InpInd_Timeframe=PERIOD_H4`
2. 按指标源码重建 `ATR/StdDev -> 自适应砖宽 -> UpTrendBuffer/DnTrendBuffer`
3. 多头开仓：`UpTrendBuffer` 在当前信号柱首次出现
4. 空头开仓：`DnTrendBuffer` 在当前信号柱首次出现
5. 反向趋势首次出现时，先关闭已有净头寸，再按许可条件反手
6. 默认保留源码中的 `1000 / 2000` 点止损止盈

## 主要参数

- `indicator_minutes`
- `k`
- `indicator_mode`
- `vlt_period`
- `price_mode`
- `wide_min`
- `l_signal_bar`
- `s_signal_bar`
- `l_stop_loss_points`
- `l_take_profit_points`
- `s_stop_loss_points`
- `s_take_profit_points`
- `l_mm`
- `s_mm`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `7`
- Net P&L: `+525.50`
- Win Rate: `57.14%`
- Profit Factor: `2.15`
- Max Drawdown: `0.37%`

## 对齐说明

- 原 EA 的 long / short 子系统允许完全独立配置；当前 Backtrader 版本保留独立参数入口，但在持仓层面使用单净头寸近似
- 默认配置保持源码活跃默认值：`ATR + Close + K=1 + WideMin=2`
- Backtrader 无法逐 tick 复刻 MT5 的成交和订单服务器校验细节，因此结果应视为可运行的逻辑迁移样例
