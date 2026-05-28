# 0723 Exp_Fractal_MFI

## 策略概述

该策略是对 MT5 EA `0723_Exp_Fractal_MFI` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的主要结构：

- 在更高时间框架上重建 `Fractal_MFI`
- 从超卖区上穿做多
- 从超买区下穿做空
- 反向信号平掉原持仓
- 固定 `SL/TP`

## 指标重建说明

迁移版按源码思路近似重建：

- 使用指定价格序列作为输入
- 基于最近窗口估算分形特征/自适应速度
- 用该速度重新计算 `MFI`
- 输出为 0-100 振荡器

## 核心逻辑

1. `Fractal_MFI` 上穿 `LowLevel` 时做多。
2. `Fractal_MFI` 下穿 `HighLevel` 时做空。
3. 反向触发同时作为平仓信号。

## 主要参数

- `e_period`
- `normal_speed`
- `high_level`
- `low_level`

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 尚未补做本地回测校验，建议台账先标记为 `实施中`，后续再补齐样本结果。
