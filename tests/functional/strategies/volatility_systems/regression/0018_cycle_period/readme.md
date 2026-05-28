# 1014 Exp_CyclePeriod

## 策略概述

该示例是对 MT5 EA `1014_Exp_CyclePeriod` 的 Backtrader 迁移版本。
EA 在 `H6` 周期上计算非归一化 `CyclePeriod` 振荡器，并在主线方向反转时执行开平仓。

## 原始信号逻辑

1. 以 `(high + low) / 2` 为基础价格序列
2. 依照源码递推计算 `Smooth`、`Cycle`、`Q1`、`I1`、`DeltaPhase`
3. 得到 `CyclePeriod` 主线
4. 在柱线收盘时：
   - 若上一柱低于上上柱，且当前柱高于上一柱，则买入
   - 若上一柱高于上上柱，且当前柱低于上一柱，则卖出

## 指标迁移说明

- 直接复用了仓库内已有 `CyclePeriod` 递推重建思路
- 不依赖缺失的外部平滑库，可按源码完整等价表达
- 保留默认 `H6` 信号周期与固定 `SL/TP`

## 数据与运行

- 基础数据：`../../../datas/XAUUSD_M15.csv`
- 信号周期：`H6`
- 运行：`python run.py`
- 绘图：`python run.py --plot`
