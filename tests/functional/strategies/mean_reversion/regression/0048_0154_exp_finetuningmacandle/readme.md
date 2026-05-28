# 0154 Exp_FineTuningMACandle

## 策略概述

该样例是对 MT5 EA `0154_Exp_FineTuningMACandle` 的 Backtrader 迁移版。
原 EA 基于 `FineTuningMACandle` 指标的颜色切换信号交易：当平滑蜡烛颜色从非多头切到多头时开多并平空，从非空头切到空头时开空并平多。

## 迁移思路

1. 用源码中的 `FTMA/rank/shift` 权重公式重建 `FineTuningMACandle` 平滑蜡烛
2. 按原指标规则生成三态颜色：`0=空头`、`1=中性`、`2=多头`
3. 以 `SignalBar` 对齐原 EA 的颜色切换逻辑
4. 将 `BuyPosClose / SellPosClose` 语义映射为单净头寸的平仓与反手
5. 保留固定止损和止盈的基础风控结构

## 主要参数

- `fixed_lot`
- `stoploss_pips`
- `takeprofit_pips`
- `ftma`
- `rank1`
- `rank2`
- `rank3`
- `shift1`
- `shift2`
- `shift3`
- `gap_points`
- `signal_bar`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`./run.py`
- 绘图：`./run.py --plot`

## 当前回测结果

- Trades: `52`
- Net P&L: `-1347.80`
- Win Rate: `38.46%`
- Profit Factor: `0.82`
- Max Drawdown: `4.72%`

## 对齐说明

- 原 EA 依赖仓库内可见的 `FineTuningMACandle` 指标源码，因此当前版本按指标公式直接重建，而不是做黑盒近似
- 当前版本保留颜色切换触发开平仓的核心语义，并将其映射到 Backtrader 单净头寸模型
- 结果应视为可运行的逻辑迁移样例，不能逐 tick 等同 MT5 成交细节
