# 0709 MQL5 向导 MACD 抛物线 SAR

## 策略概述

该策略是对 MT5 EA `0709_MQL5_向导_MACD_抛物线_SAR` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的核心结构：

- `MACD` 与 `Parabolic SAR` 组成加权信号
- 达到开仓阈值时入场
- 达到平仓阈值或命中 `SL/TP` 时离场
- 固定手数资金管理

## 核心逻辑

1. `MACD` 与 `SAR` 各自产生方向评分。
2. 按配置权重合并成总信号值。
3. 总信号超过开仓阈值做多，低于负阈值做空。
4. 反向极值或 `SL/TP` 触发离场。

## 迁移说明

- 原 EA 基于 `MQL5 Wizard` 的 `CExpertSignal` 组合过滤器实现。
- 迁移版直接在 Backtrader 中重建等价的 `MACD + SAR` 加权信号。

## 主要参数

- `signal_threshold_open`
- `signal_threshold_close`
- `signal_stop_level`
- `signal_take_level`
- `signal_macd_period_fast`
- `signal_macd_period_slow`
- `signal_macd_period_signal`
- `signal_sar_step`
- `signal_sar_maximum`

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 尚未补做本地回测校验，建议台账先标记为 `实施中`，后续再补齐样本结果。
