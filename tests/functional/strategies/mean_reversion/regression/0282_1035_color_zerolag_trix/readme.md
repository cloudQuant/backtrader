# 1035 Exp_ColorZerolagTriX

## 策略概述

该示例是对 MT5 EA `1035_Exp_ColorZerolagTriX` 的 Backtrader 迁移版本。
EA 在 `H4` 周期上读取 `ColorZerolagTriX` 指标，当快慢线发生交叉并触发云颜色切换时执行开平仓。

## 原始信号逻辑

1. 指标内部计算 5 组不同周期的 `TriX` 主线
2. 按固定权重叠加得到 `FastTrend`
3. 对 `FastTrend` 做递推平滑得到 `SlowTrend`
4. EA 在柱线收盘时读取最近已完成信号柱：
   - 前一柱 `Fast > Slow` 且当前柱 `Fast < Slow` 触发买入
   - 前一柱 `Fast < Slow` 且当前柱 `Fast > Slow` 触发卖出

## 指标迁移说明

- 重建 5 组 `TriX` 主线并按源码权重组合
- 保留 `smoothing=15` 的递推慢线
- 保留固定 `SL/TP` 与 `H4` 信号周期

## 数据与运行

- 基础数据：`../../../datas/XAUUSD_M15.csv`
- 信号周期：`H4`
- 运行：`python run.py`
- 绘图：`python run.py --plot`
