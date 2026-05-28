# 1008 Exp_Ergodic_Ticks_Volume_OSMA

## 策略概述

该示例是对 MT5 EA `1008_Exp_Ergodic_Ticks_Volume_OSMA` 的 Backtrader 迁移版本。
EA 在 `H8` 周期上计算 `Ergodic_Ticks_Volume_OSMA` 直方图，并在柱体方向反转时执行开平仓。

## 原始信号逻辑

1. 先按 `UpTicks / DownTicks` 构造 `TVI`
2. 对 `TVI` 做多级平滑得到 `Ergodic_TVI` 与 `Signal`
3. 计算 `MACD = Ergodic_TVI - Signal`
4. 对 `MACD` 再做一层平滑得到 `Ergodic_OSMA`
5. 在柱线收盘时：
   - 若上一柱低于上上柱，且当前柱高于上一柱，则买入
   - 若上一柱高于上上柱，且当前柱低于上一柱，则卖出

## 指标迁移说明

- 核心是 `1009` 指标链再加一层 `OSMA` 平滑，公式可完整重建
- 默认参数走 `tick volume + MODE_EMA`
- 保留默认 `H8` 信号周期与固定 `SL/TP`

## 数据与运行

- 基础数据：`../../../datas/XAUUSD_M15.csv`
- 信号周期：`H8`
- 运行：`python run.py`
- 绘图：`python run.py --plot`
