# 1010 Exp_EMA_Prediction

## 策略概述

该示例是对 MT5 EA `1010_Exp_EMA_Prediction` 的 Backtrader 迁移版本。
EA 在 `H6` 周期上计算 `EMA_Prediction` 指标，并在出现新的买卖箭头时执行开平仓。

## 原始信号逻辑

1. 计算一条快 `EMA` 和一条慢 `EMA`
2. 要求前一根与当前根完成有效交叉
3. 同时要求当前柱实体方向与交叉方向一致：
   - 多头信号要求 `open < close`
   - 空头信号要求 `open > close`
4. 原指标用 `ATR * 3/8` 将箭头画在高低点外侧，EA 只读取箭头缓冲区开平仓

## 指标迁移说明

- 指标核心完全公开：`EMA` 交叉 + 当前柱方向过滤 + `ATR` 偏移
- 保留默认 `FastEMA(1)`、`SlowEMA(2)` 与 `H6` 信号周期
- 保留固定 `SL/TP`

## 数据与运行

- 基础数据：`../../../datas/XAUUSD_M15.csv`
- 信号周期：`H6`
- 运行：`python run.py`
- 绘图：`python run.py --plot`
