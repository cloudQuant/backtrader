# 1250 Extremum

## 策略概述

该策略是对 MT5 EA `1250_Exp_Extremum` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，并在内部重采样为 `H4` 以复现原 EA 的指标信号周期。

## 核心逻辑

1. 在 `H4` 级别按原始 `Extremum` 指标源码计算极值直方图状态
2. 当直方图由空头状态翻转为多头状态时做多
3. 当直方图由多头状态翻转为空头状态时做空
4. 出现反向信号时平仓并允许反手
5. 同时保留固定点数止损与止盈

## 主要参数

- `n_bars`
- `stop_loss_points`
- `take_profit_points`
- `mm`
- `point`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 说明

原 MT5 EA 通过 `iCustom(..., "Extremum", NBars, 0)` 调用自定义指标，并在 `PERIOD_H4` 上取信号。
本迁移版直接依据仓库内 `extremum.mq5` 源码重建核心计算，不依赖额外 `.ex5` 文件。
