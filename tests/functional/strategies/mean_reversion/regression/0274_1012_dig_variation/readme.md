# 1012 Exp_DigVariation

## 策略概述

该示例是对 MT5 EA `1012_Exp_DigVariation` 的 Backtrader 迁移版本。
EA 在 `H8` 周期上计算 `DigVariation` 非归一化振荡器，并在主线方向反转时执行开平仓。

## 原始信号逻辑

1. 先对价格计算一条 `MA(price)`
2. 再对 `price - ma` 计算第二条 `MA`
3. 得到 `ExtCalc = 1000 * (price - (ma + vr))`
4. 对 `ExtCalc` 施加 `SP()` 平滑核，形成最终 `Variation`
5. 在柱线收盘时：
   - 若上一柱低于上上柱，且当前柱高于上一柱，则买入
   - 若上一柱高于上上柱，且当前柱低于上一柱，则卖出

## 指标迁移说明

- 默认参数走 `MODE_SMA + dig_1`，对应源码中公开可见的双均线与 FIR 平滑核
- 不依赖缺失的专有 `JJMA/T3` 核心实现
- 保留默认 `H8` 信号周期与固定 `SL/TP`

## 数据与运行

- 基础数据：`../../../datas/XAUUSD_M15.csv`
- 信号周期：`H8`
- 运行：`python run.py`
- 绘图：`python run.py --plot`
