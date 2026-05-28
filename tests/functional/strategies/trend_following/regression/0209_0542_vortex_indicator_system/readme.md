# 0542 Vortex_Indicator_System

## 策略概述

该策略是对 MT5 EA `0542_Vortex_指标系统` 的 Backtrader 迁移版本。

- 使用 `Vortex` 指标交叉形成 setup
- 真正进场需要价格突破交叉柱高点/低点
- 出现反向 setup 时先平掉反向持仓

## 核心逻辑

1. 计算 `VI+` 和 `VI-`。
2. 当 `VI+` 自下向上穿越 `VI-` 时，记录多头 setup，并把前一根柱高点设为触发价。
3. 当 `VI-` 自下向上穿越 `VI+` 时，记录空头 setup，并把前一根柱低点设为触发价。
4. 当后续价格突破该触发价时进场。

## 迁移说明

- 原版依赖外部 `Vortex` 指标文件；迁移版直接在 Backtrader 中重建 `Vortex` 计算。
- 原版没有复杂的 SL/TP 管理；迁移版保持其核心入场与反向平仓结构。

## 运行方式

```bash
python run.py
```
