# 0465 TimeEA

## 策略概述

该策略是对 MT5 EA `0465_TimeEA` 的 backtrader 迁移版本。
原 EA 的逻辑非常直接：在设定的开仓时刻打开指定方向仓位，在设定的平仓时刻关闭对应仓位，并支持固定 `SL/TP`。

## 核心逻辑

1. 每个交易日按设定时刻检查开仓触发
2. `opened_type=buy` 时开多，`opened_type=sell` 时开空
3. 到达平仓时刻后关闭对应持仓
4. 支持固定 `SL/TP`
5. 保持单一净头寸

## 主要参数

- `hour_open`
- `minute_open`
- `hour_close`
- `minute_close`
- `opened_type`
- `volume`
- `stop_loss_points`
- `take_profit_points`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- 数据区间：`2025-12-03 01:15:00` → `2026-03-10 09:00:00`
- K线数量：`6129`
- 买入次数：`34`
- 卖出次数：`33`
- 平仓交易数：`33`
- 期末权益：`105794.80`
- 净收益：`5794.80`
- 总收益率：`5.79%`
- 胜率：`55.88%`
- Profit Factor：`1.87`
- 最大回撤：`4.45%`

## 对齐说明

- 原 EA 在 tick 级别判断时间跨越，因此若同一 bar 内因止损出场，理论上可再次开仓；当前 backtrader 版本按 bar 级别执行，不复现该 tick 内重复开仓细节
- 默认配置使用 `01:00` 开仓、`00:00` 平仓、方向为 `buy`
- 原 EA 默认不设置固定 `SL/TP`；当前配置同样保持 `0/0`
