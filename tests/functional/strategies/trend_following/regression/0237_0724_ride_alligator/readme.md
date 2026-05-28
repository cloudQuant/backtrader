# 0724 RideAlligator

## 策略概述

该策略是对 MT5 EA `0724_RideAlligator` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的核心结构：

- 只在空仓时开新仓
- 使用 Alligator 三线关系判断方向
- 按资金风险比例计算 lot
- 持仓后用 `Jaws` 线动态推进止损

## 核心逻辑

1. 构造 Alligator 三线。
2. 当 `lips` 上穿到 `jaws` 上方且 `teeth` 位于 `jaws` 下方时做多。
3. 当 `lips` 下穿到 `jaws` 下方且 `teeth` 位于 `jaws` 上方时做空。
4. 开仓后将 `Jaws` 线作为动态保护止损。

## 主要参数

- `alligator_period`
- `risk_factor`

## 对齐说明

- 原 EA 用一组按黄金分割扩展的 Alligator 周期；迁移版保留相同思路。
- 原版没有固定 `TP`，核心离场依赖 `Jaws` 的动态止损；迁移版保持这一点。

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 尚未补做本地回测校验，建议台账先标记为 `实施中`，后续再补齐样本结果。
