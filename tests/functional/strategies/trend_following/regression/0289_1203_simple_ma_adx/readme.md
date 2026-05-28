# 1203 简单 EA, 基于简单均线和 ADX

## 策略概述

该策略是对 MT5 EA `1203_简单_EA,_基于简单均线和_ADX` 的 Backtrader 迁移版本。
原 EA 使用 EMA 趋势方向、前一根 K 线收盘价与均线的位置关系，以及 ADX / DI 过滤条件来开仓。

## 核心逻辑

1. 计算 `EMA(MA_Period)`
2. 若均线连续上升、前一根收盘价高于均线、`ADX > Adx_Min` 且 `+DI > -DI`，则做多
3. 若均线连续下降、前一根收盘价低于均线、`ADX > Adx_Min` 且 `-DI > +DI`，则做空
4. 保留原 EA 的固定手数、止损与止盈设置

## 主要参数

- `ma_period`
- `adx_period`
- `adx_min`
- `stop_loss_points`
- `take_profit_points`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`
