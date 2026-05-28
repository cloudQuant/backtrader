# 1247 AMkA

## 策略概述

该策略是对 MT5 EA `1247_Exp_AMkA` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，并在内部重建 `H4` 的 `AMkA` 趋势箭头信号。

## 核心逻辑

1. 在 `H4` 上先按原始 `AMA` 自适应均线公式计算 `AMABuffer`
2. 再按原始 `AMkA` 指标逻辑计算 `AMA` 增量的均值与标准差滤波器
3. 当最新柱产生 `UpSignal` 且上一段有效信号为 `DnSignal` 时做多，并可同步平掉空头
4. 当最新柱产生 `DnSignal` 且上一段有效信号为 `UpSignal` 时做空，并可同步平掉多头
5. 同时保留固定点数止损与止盈

## 主要参数

- `ama_period`
- `fast_ma_period`
- `slow_ma_period`
- `g_power`
- `dk`
- `signal_bar`
- `mm`
- `mm_mode`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 说明

原 MT5 EA 通过 `iCustom(..., "AMkA", ama_period, fast_ma_period, slow_ma_period, G, 0, dK)` 获取 `AMA / DnSignal / UpSignal` 三个缓冲区，并在 `PERIOD_H4` 柱线收盘时按最近一次箭头颜色翻转交易。
本迁移版直接依据仓库内 `amka.mq5` 与 `exp_amka.mq5` 源码重建核心计算，不依赖额外 `.ex5` 文件。
