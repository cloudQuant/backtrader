# 0730 Exp_WeightOscillator

## 策略概述

该策略是对 MT5 EA `0730_Exp_WeightOscillator` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的核心结构：

- 在更高时间框架上重建 `WeightOscillator`
- `WeightOscillator` 上穿 `LowLevel` 做多
- `WeightOscillator` 下穿 `HighLevel` 做空
- 反向信号平掉相反仓位
- 支持 `DIRECT/AGAINST` 两种解释方式

## 指标重建说明

`WeightOscillator` 按源码近似重建为以下量的加权平均并平滑：

- `RSI`
- `MFI`
- `WPR + 100`
- `DeMarker * 100`

然后再做一次平滑，形成最终振荡器主线。

## 核心逻辑

1. 计算 `WeightOscillator`。
2. 从超卖区上穿 `LowLevel` 时生成多头信号。
3. 从超买区下穿 `HighLevel` 时生成空头信号。
4. `trend=direct` 表示顺信号方向交易；`trend=against` 可做反向解释。

## 主要参数

- `rsi_weight`
- `mfi_weight`
- `wpr_weight`
- `demarker_weight`
- `high_level`
- `low_level`
- `trend`

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 尚未补做本地回测校验，建议台账先标记为 `实施中`，后续再补齐样本结果。
