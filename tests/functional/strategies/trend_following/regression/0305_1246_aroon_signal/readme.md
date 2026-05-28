# 1246 Aroon Signal

## 策略概述

该策略是对 MT5 EA `1246_Exp_AroonSignal` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，并在内部重建 `H4` 的 `AroonSignal` 菱形信号。

## 核心逻辑

1. 在 `H4` 上按原始 `AroonSignal` 指标公式计算 `BULLS` 与 `BEARS`
2. 当 `BULLS > HighLevel` 且 `BEARS < LowLevel` 时标记为多头极值区；反向条件则标记为空头极值区
3. 只有当极值区方向相对上一次记录发生翻转时，才生成新的 `UpSignal / DnSignal` 菱形
4. 出现 `UpSignal` 时做多并可同步平掉空头；出现 `DnSignal` 时做空并可同步平掉多头
5. 同时保留固定点数止损与止盈

## 主要参数

- `high_level`
- `low_level`
- `aroon_period`
- `signal_bar`
- `stop_loss_points`
- `take_profit_points`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 说明

原 MT5 EA 通过 `iCustom(..., "AroonSignal", HighLevel, LowLevel, AroonPeriod, 0)` 获取 `UpSignal / DnSignal` 两个缓冲区，并在 `PERIOD_H4` 柱线收盘时根据新出现的彩色菱形交易。
本迁移版直接依据仓库内 `aroonsignal.mq5` 与 `exp_aroonsignal.mq5` 源码重建核心计算，不依赖额外 `.ex5` 文件。
