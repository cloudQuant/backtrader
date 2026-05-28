# 1016 Exp_CoppockHist

## 策略概述

该示例是对 MT5 EA `1016_Exp_CoppockHist` 的 Backtrader 迁移版本。
EA 在 `H8` 周期上计算 `CoppockHist` 振荡器，并在振荡器方向反转时执行开平仓。

## 原始信号逻辑

1. 以所选价格计算两段 `ROC`
2. 将两段 `ROC` 相加得到 `ROCSum`
3. 对 `ROCSum` 做一次平滑得到 `CoppockHist`
4. 在柱线收盘时：
   - 若上一柱低于上上柱，且当前柱高于上一柱，则买入
   - 若上一柱高于上上柱，且当前柱低于上一柱，则卖出

## 指标迁移说明

- 指标核心公式在源码中完整可见，可直接在 Python 中重建
- 原实现虽引用 `SmoothAlgorithms.mqh`，但这里仅使用价格序列与常规均线平滑封装
- 保留默认 `H8` 信号周期与固定 `SL/TP`

## 数据与运行

- 基础数据：`../../../datas/XAUUSD_M15.csv`
- 信号周期：`H8`
- 运行：`python run.py`
- 绘图：`python run.py --plot`
