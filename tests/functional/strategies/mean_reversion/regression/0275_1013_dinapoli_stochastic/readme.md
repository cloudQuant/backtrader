# 1013 Exp_DiNapoliStochastic

## 策略概述

该示例是对 MT5 EA `1013_Exp_DiNapoliStochastic` 的 Backtrader 迁移版本。
EA 在 `H6` 周期上计算 `DiNapoliStochastic` 指标，并在主线与信号线交叉时执行开平仓。

## 原始信号逻辑

1. 先对 `FastK` 窗口计算最高价/最低价区间
2. 计算 `100 * (close - LL) / (HH - LL)` 的归一化值
3. 对主线做一次 `SlowK` 递推平滑，再对信号线做一次 `SlowD` 递推平滑
4. 在柱线收盘时按源码条件触发：
   - 前一根主线高于信号线、当前主线回落到信号线下方时买入
   - 前一根主线低于信号线、当前主线上穿到信号线上方时卖出

## 指标迁移说明

- 指标源码完整公开，不依赖缺失外部平滑库
- 已保留默认 `FastK=8 / SlowK=3 / SlowD=3 / Shift=0`
- 保留默认 `H6` 信号周期与固定 `SL/TP`

## 数据与运行

- 基础数据：`../../../datas/XAUUSD_M15.csv`
- 信号周期：`H6`
- 运行：`python run.py`
- 绘图：`python run.py --plot`
