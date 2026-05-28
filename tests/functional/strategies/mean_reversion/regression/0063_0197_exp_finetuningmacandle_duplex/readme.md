# 0197 Exp_FineTuningMACandle_Duplex

## 策略概述

该样例是对 MT5 EA `0197_Exp_FineTuningMACandle_Duplex` 的 Backtrader 迁移版。
原 EA 使用 `FineTuningMACandle` 自定义指标作为信号源，并将多头系统与空头系统拆成两套独立参数和独立 `magic`。源码默认两套系统都启用，且指标参数对称。

## 迁移思路

1. 从 `XAUUSD_M15.csv` 读取基础行情，并重采样到源码默认使用的 `H4`
2. 按 `FineTuningMACandle.mq5` 重建平滑蜡烛的权重与颜色状态
3. 对长仓系统读取 `long_state`，状态变成 `2` 时开多，状态变成 `0` 时平多
4. 对短仓系统读取 `short_state`，状态变成 `0` 时开空，状态变成 `2` 时平空
5. 用两份相同的 H4 数据 feed 模拟 MT5 中两套独立 `magic` 的多空系统，使 Backtrader 也能同时持有“多系统”和“空系统”的仓位
6. 保留默认 `SL/TP`

## 主要参数

- `long_lot`
- `short_lot`
- `long_stop_loss_points`
- `long_take_profit_points`
- `short_stop_loss_points`
- `short_take_profit_points`
- `long_indicator.*`
- `short_indicator.*`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `43`
- Net P&L: `1156.90`
- Win Rate: `41.86%`
- Profit Factor: `1.22`
- Max Drawdown: `1.56%`

## 对齐说明

- 原 EA 使用 `SignalBar=1`，即依据上一根已完成的 H4 指标柱触发信号；当前版本通过 `cheat_on_open` 在下一根 H4 开盘近似执行
- 原 MT5 EA 能以两套 `magic` 独立管理多空仓位；当前版本通过双 feed 建模保留这一点
- `FineTuningMACandle` 中 `Gap` 条件按源码原样比较价格差值，没有额外乘 `_Point`
- 由于 Backtrader 是柱级回测，`SL/TP` 在同一根柱内若同时触发，当前实现优先按止损处理
