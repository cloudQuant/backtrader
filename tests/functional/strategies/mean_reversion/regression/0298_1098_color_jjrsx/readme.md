# 1098 Exp_ColorJJRSX

## 策略概述

该示例是对 MT5 EA `1098_Exp_ColorJJRSX` 的 Backtrader 迁移版本。
EA 信号来自 `ColorJJRSX` 指标主线的方向拐点。

## 原始信号逻辑

EA 在 `H4` 指标周期上读取 `ColorJJRSX` 主线最近 3 个值：

1. 若 `Value[1] < Value[2]` 且 `Value[0] > Value[1]`，产生做多信号
2. 若 `Value[1] > Value[2]` 且 `Value[0] < Value[1]`，产生做空信号
3. 做多信号可触发空头平仓
4. 做空信号可触发多头平仓
5. 默认使用固定止损 / 止盈

## 指标迁移说明

- 原始指标 `ColorJJRSX` 依赖 `SmoothAlgorithms.mqh`
- 当前版本按公开 `SmoothAlgorithms` 中的 `CJurX` 与 `CJJMA` 逻辑在 Python 中预计算 `JJRSX`
- 指标值先在 `H4` 上计算，再作为信号数据喂给策略

## 主要参数

- `jurx_period`
- `jma_period`
- `jma_phase`
- `signal_bar`
- `stop_loss`
- `take_profit`
- `size`

## 数据与运行

- 基础数据：`../../../datas/XAUUSD_M15.csv`
- 信号周期：`H4`
- 运行：`python run.py`
- 绘图：`python run.py --plot`
