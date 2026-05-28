# 0705 移动均线交易系统

## 策略概述

该策略是对 MT5 EA `0705_移动均线交易系统` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的核心结构：

- 使用 `SMA5/20/40/60`
- `SMA40` 与 `SMA60` 的穿越是核心入场条件
- `SMA5` 和 `SMA20` 用作趋势过滤
- 固定 `SL/TP`
- 反向穿越离场并支持 trailing

## 核心逻辑

1. 当 `SMA5 > SMA20 > SMA40` 且 `SMA40` 上穿 `SMA60` 时做多。
2. 当 `SMA5 < SMA20 < SMA40` 且 `SMA40` 下穿 `SMA60` 时做空。
3. `SMA40/SMA60` 反向关系出现时平仓。
4. 持仓盈利后用固定 trailing 跟随。

## 迁移说明

- 原 EA 使用 `PRICE_MEDIAN` 计算 SMA；迁移版保留这一点。
- 原版有 `hedging only` 检查，但交易结构本质是单仓信号模型。

## 主要参数

- `take_profit`
- `stop_loss`
- `trailing_stop`
- `lots`

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 尚未补做本地回测校验，建议台账先标记为 `实施中`，后续再补齐样本结果。
