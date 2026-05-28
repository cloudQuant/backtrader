# 1346 Three Crows / Three Soldiers + Stochastic

## 策略概述

该策略是对 MT5 EA `1346_MQL5_向导_-_基于_3_乌鸦_3_白兵_+_Stochastic` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为三乌鸦 / 三白兵反转形态配合 Stochastic 确认。

## 核心逻辑

1. 检查连续三根 K 线是否构成 `Three White Soldiers` 或 `Three Black Crows`
2. 多头形态出现且 Stochastic 处于低位时做多
3. 空头形态出现且 Stochastic 处于高位时做空
4. 持仓后根据随机指标反向变化离场

## 主要参数

- `stoch_period_k`
- `stoch_period_d`
- `stoch_period_slow`
- `ma_period`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 对齐说明

- 当前版本保留了蜡烛形态 + Stochastic 过滤的 MQL5 Wizard 结构
- 与 1345/1344/1343 的区别仅在确认振荡器不同
