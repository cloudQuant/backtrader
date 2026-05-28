# 0152 LBS

## 策略概述

该样例是对 MT5 EA `0152_LBS` 的 Backtrader 迁移版。
原 EA 会在指定小时基于最近两根 K 线的高低点布置双向 stop 挂单；一旦一侧成交，就删除另一侧挂单，并仅通过初始止损与 trailing stop 管理持仓。

## 迁移思路

1. 将 `XAUUSD_M15` 重采样为 `H1`，用作 EA 当前图表周期近似
2. 在 `hour_1/hour_2/hour_3` 指定时刻布置双向 stop 进场单
3. 以最近两根 K 线的最高点 / 最低点作为突破触发位
4. 一侧成交后取消另一侧挂单
5. 保留初始止损与分步 trailing stop 的主流程

## 主要参数

- `fixed_lot`
- `stoploss_pips`
- `trailing_stop_pips`
- `trailing_step_pips`
- `atr_period`
- `hour_1`
- `hour_2`
- `hour_3`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`./run.py`
- 绘图：`./run.py --plot`

## 当前回测结果

- Trades: `167`
- Net P&L: `-47912.00`
- Win Rate: `21.56%`
- Profit Factor: `0.54`
- Max Drawdown: `51.43%`

## 对齐说明

- 原 EA 源码中创建了 `ATR` 句柄，但实际入场主逻辑体现为基于近两根 K 线高低点的双向 stop 触发，本迁移版按源码主路径复现
- Backtrader 版本保留了“双向挂单 -> 一侧成交后删除另一侧 -> trailing”的核心行为
- 为避免多组旧挂单长期堆积，当前实现每到计划时段会先替换成最新一组挂单，这是对原 EA 在离线回测环境中的稳定化近似
