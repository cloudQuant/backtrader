# 1043 Exp_ForexProfitBoost_2nb

## 策略概述

该示例是对 MT5 EA `1043_Exp_ForexProfitBoost_2nb` 的 Backtrader 迁移版本。
EA 在 `H6` 周期上读取 `ForexProfitBoost_2nb` 指标的颜色状态切换，并在趋势配色翻转时执行开平仓。

## 原始信号逻辑

1. 指标综合 `MA1`、`MA2` 与 `Bollinger Bands`
2. 当上一根已完成柱处于 `Up` 颜色状态且当前转入 `Dn` 状态时，EA 触发做多并关闭空头
3. 当上一根已完成柱处于 `Dn` 颜色状态且当前转入 `Up` 状态时，EA 触发做空并关闭多头
4. 默认使用固定止损与止盈

## 指标迁移说明

- 重建 `EMA(7)`、`SMA(21)` 与 `Bollinger Bands(15, 1)`
- 根据源码的 `MA1 > MA2` / `MA1 <= MA2` 状态切换重建 `up_state` 与 `down_state`
- EA 按上一根与当前已完成柱的状态翻转触发交易

## 数据与运行

- 基础数据：`../../../datas/XAUUSD_M15.csv`
- 信号周期：`H6`
- 运行：`python run.py`
- 绘图：`python run.py --plot`
