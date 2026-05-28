# 1009 Exp_Ergodic_Ticks_Volume_Indicator

## 策略概述

该示例是对 MT5 EA `1009_Exp_Ergodic_Ticks_Volume_Indicator` 的 Backtrader 迁移版本。
EA 在 `H6` 周期上计算 `Ergodic_Ticks_Volume_Indicator` 指标，并在主线与信号线交叉时执行开平仓。

## 原始信号逻辑

1. 将成交量拆分为 `UpTicks / DownTicks`
2. 分别对 `UpTicks / DownTicks` 做两层平滑
3. 计算 `TVI = 100 * (DEMA_Up - DEMA_Down) / (DEMA_Up + DEMA_Down)`
4. 再对 `TVI` 连续做 `1/5/5/5` 四段平滑，得到 `Ergodic_TVI` 与 `Signal`
5. 在柱线收盘时按源码条件触发：
   - 前一根主线高于信号线、当前主线回落到信号线下方时买入
   - 前一根主线低于信号线、当前主线上穿到信号线上方时卖出

## 指标迁移说明

- 默认参数走 `tick volume + MODE_EMA` 的公开可重建路径
- 保留原始多级平滑链与交叉条件
- 保留默认 `H6` 信号周期与固定 `SL/TP`

## 数据与运行

- 基础数据：`../../../datas/XAUUSD_M15.csv`
- 信号周期：`H6`
- 运行：`python run.py`
- 绘图：`python run.py --plot`
