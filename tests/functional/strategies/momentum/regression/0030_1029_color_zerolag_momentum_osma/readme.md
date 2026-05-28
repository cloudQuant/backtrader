# 1029 Exp_ColorZerolagMomentumOSMA

## 策略概述

该示例是对 MT5 EA `1029_Exp_ColorZerolagMomentumOSMA` 的 Backtrader 迁移版本。
EA 在 `H4` 周期上读取 `ColorZerolagMomentumOSMA` 直方图，当最近已完成柱的方向由降转升或由升转降时执行开平仓。

## 原始信号逻辑

1. 计算 5 组不同周期的 `Momentum`
2. 按源码权重叠加得到 `FastTrend`
3. 用 `smoothing1` 对 `FastTrend` 做零滞后递推平滑得到 `SlowTrend`
4. 再用 `smoothing2` 对 `FastTrend - SlowTrend` 做递推平滑得到 `OSMA`
5. EA 在柱线收盘时读取最近 3 个已完成信号值：
   - `Value[1] < Value[2]` 且 `Value[0] > Value[1]` 触发买入
   - `Value[1] > Value[2]` 且 `Value[0] < Value[1]` 触发卖出

## 指标迁移说明

- 指标仅依赖内置 `iMomentum` 与源码公开的两段递推公式，可在 Python 中本地重建
- 保留默认 `smoothing1=15`、`smoothing2=15`、`PRICE_CLOSE`、`H4` 信号周期与固定 `SL/TP`
- 按源码保留第 3 组权重仍与 `Factor2` 相乘的实现细节

## 数据与运行

- 基础数据：`../../../datas/XAUUSD_M15.csv`
- 信号周期：`H4`
- 运行：`python run.py`
- 绘图：`python run.py --plot`
