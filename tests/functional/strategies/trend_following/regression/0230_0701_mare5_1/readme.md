# 0701 MARE5.1

## 策略概述

该策略是对 MT5 EA `0701_MARE5.1` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的核心结构：

- 两条 `SMA`
- 比较 `0 / 2 / 5` 三个采样点的快慢关系
- 叠加上一根 K 线方向过滤
- 只在指定小时区间允许开仓
- 固定 `SL/TP`

## 核心逻辑

1. 计算快慢两条 `SMA`，并考虑 `MovingShift` 偏移。
2. 若快慢线在 `0/2/5` 三个采样点上满足特定翻转结构，且前一根 K 线同向，则开仓。
3. 只有当前小时位于 `HourTimeOpen` 到 `HourTimeClose` 之间才允许开仓。
4. 入场后按固定 `SL/TP` 管理。

## 迁移说明

- 原 EA 使用 `PERIOD_M1` 固定周期计算，迁移版也按 `M1` 示例组织。
- 重点保留其“多采样点比较 + 时间窗”这一核心结构。

## 主要参数

- `take_profit`
- `stop_loss`
- `ma_fast_period`
- `ma_slow_period`
- `moving_shift`
- `hour_time_open`
- `hour_time_close`

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 尚未补做本地回测校验，建议台账先标记为 `实施中`，后续再补齐样本结果。
