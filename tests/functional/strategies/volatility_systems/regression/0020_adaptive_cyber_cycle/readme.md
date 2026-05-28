# 1248 Adaptive Cyber Cycle

## 策略概述

该策略是对 MT5 EA `1248_Exp_AdaptiveCyberCycle` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，并在内部重建 `H4` 的 `AdaptiveCyberCycle` 信号流。

## 核心逻辑

1. 在 `H4` 上先按原始 `CyclePeriod` 指标算法计算自适应周期
2. 再按配置的 `mode` 计算 `Adaptive Cyber Cycle / Adaptive CG Oscillator / Adaptive RVI` 主线与触发线
3. 当主线从上方向下穿越触发线时做多，并可同步平掉空头
4. 当主线从下方向上穿越触发线时做空，并可同步平掉多头
5. 同时保留固定点数止损与止盈

## 主要参数

- `mode`
- `alpha`
- `signal_bar`
- `stop_loss_points`
- `take_profit_points`
- `mm`
- `point`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 说明

原 MT5 EA 通过 `iCustom(..., "AdaptiveCyberCycle" | "AdaptiveCGOscillator" | "AdaptiveRVI", Alpha, 0)` 获取指标主线与触发线，默认在 `PERIOD_H4` 上按交叉信号交易。
本迁移版直接依据仓库内 `adaptivecybercycle.mq5`、`adaptivecgoscillator.mq5`、`adaptivervi.mq5` 与 `cycleperiod.mq5` 源码重建核心计算，不依赖额外 `.ex5` 文件。
