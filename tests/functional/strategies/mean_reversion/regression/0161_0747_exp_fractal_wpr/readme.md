# 0747 Exp_Fractal_WPR

## 策略概述

该策略是对 MT5 EA `0747_Exp_Fractal_WPR` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的主要结构：

- 使用动态周期的 `Fractal_WPR`
- 超卖水平穿越触发做多，超买水平穿越触发做空
- `DIRECT / AGAINST` 两种方向解释方式均保留
- 交易使用固定 `SL/TP`

## 核心逻辑

1. 先按分形维数动态调整 `WPR` 周期。
2. 计算 `Fractal_WPR` 序列。
3. `DIRECT` 模式下，当指标从高于 `LowLevel` 下穿到不高于该水平时做多；从低于 `HighLevel` 上穿到不低于该水平时做空。
4. `AGAINST` 模式下，上述方向反转。
5. 若开仓方向与现有仓位相反，则先平仓再反手。

## 主要参数

- `trend`
- `high_level`
- `low_level`
- `e_period`
- `normal_speed`
- `stop_loss`
- `take_profit`

## 对齐说明

- 原 EA 将 `Fractal_WPR.ex5` 作为资源内嵌；当前迁移在 Python 中直接重建指标计算。
- 原说明提到“止损和止盈测试中未使用”，但源码接口保留了 `SL/TP` 参数，当前版本也保留。
- `DIRECT / AGAINST` 的方向解释已按源码分支逐条对应实现。

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 尚未补做本地回测校验，建议台账先标记为 `实施中`，后续再补齐样本结果。
