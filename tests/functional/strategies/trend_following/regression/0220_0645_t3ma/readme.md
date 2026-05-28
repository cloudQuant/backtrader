# 0645 T3MA

## 策略概述

该策略是对 MT5 EA `0645_T3MA` 的 Backtrader 迁移版本。

- 基于 Tillson T3 移动平均（六层级联 EMA）
- T3 方向变化产生买入/卖出信号
- 固定 SL/TP，单仓

## 核心逻辑

1. 计算 T3 移动平均（六层 EMA 级联 + volume factor 系数组合）。
2. T3 拐头向上 → 做多。
3. T3 拐头向下 → 做空。
4. 持仓使用固定 SL/TP 管理。

## 迁移说明

- 原 EA 使用 `iCustom("T3MA-ALARM")` 自定义指标；迁移版在 Python 中实现 T3 算法。
- T3 公式：`T3 = c1*e6 + c2*e5 + c3*e4 + c4*e3`，其中 `e1..e6` 为级联 EMA。
- 原版要求对冲账户；迁移版按单净仓实现。

## 主要参数

- `t3_period`
- `t3_vfactor`
- `stop_loss` / `take_profit`
- `lots`

## 运行方式

```bash
python run.py
```
