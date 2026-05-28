# 1205 简单均线_EA

## 策略概述

该策略是对 MT5 EA `1205_简单均线_EA` 的 Backtrader 迁移版本。
原 EA 使用两条 EMA，短周期为 `Periods`，长周期为 `Periods + 2`，在交叉时交易。

## 核心逻辑

1. 计算 `EMA(Periods)` 与 `EMA(Periods + 2)`
2. 若短 EMA 从下向上穿越长 EMA，则做多
3. 若短 EMA 从上向下穿越长 EMA，则做空
4. 保留原 EA 的固定手数、止损与止盈设置

## 主要参数

- `periods`
- `lots`
- `stop_loss_points`
- `take_profit_points`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`
