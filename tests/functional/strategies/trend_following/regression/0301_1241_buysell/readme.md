# 1241 BuySell

## 策略概述

该策略是对 MT5 EA `1241_Exp_BuySell` 的 Backtrader 迁移版本。
原 EA 调用 `BuySell` 指标，并依据上/下趋势缓冲线的切换在指标柱收盘时执行反手信号。

## 核心逻辑

1. 将 `M15` 数据重采样到指标周期 `H4`
2. 计算指定价格上的移动平均 `MA`
3. 计算 `ATR`，并在 `MA` 上下各偏移一个 `ATR`
4. 当 `MA` 向上时生成下方趋势线，当 `MA` 向下时生成上方趋势线
5. 如果当前柱出现下方趋势线且上一柱存在上方趋势线，则做多
6. 如果当前柱出现上方趋势线且上一柱存在下方趋势线，则做空

## 主要参数

- `indicator_minutes`
- `ma_period`
- `ma_method`
- `ma_price`
- `atr_period`
- `signal_bar`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 说明

原指标的四个 buffer 中，EA 实际只读取趋势切换相关的两条主缓冲线。
本迁移版直接在 Python 中重建 `MA ± ATR` 与缓冲线反转逻辑，以便在 Backtrader 中独立运行。
