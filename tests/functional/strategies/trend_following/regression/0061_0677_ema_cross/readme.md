# 0677 EMA_CROSS

## 策略概述

该策略是对 MT5 EA `0677_EMA_CROSS` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的核心结构：

- 快慢 `EMA` 交叉作为入场信号
- `Reverse` 参数决定交叉方向解释
- 固定 `SL/TP`
- 持仓后使用 trailing stop 保护利润

## 核心逻辑

1. 计算 `EMA(short)` 与 `EMA(long)`。
2. 通过 `Crossed()` 状态机识别快慢线方向切换。
3. 若当前无持仓，则在交叉出现时开仓。
4. 开仓后设置固定 `SL/TP`。
5. 若持仓浮盈超过 trailing 阈值，则逐步推进止损。

## 主要参数

- `reverse`
- `take_profit`
- `stop_loss`
- `lots`
- `trailing_stop`
- `short_ema`
- `long_ema`

## 对齐说明

- 原 EA 使用内部 `Crossed()` 状态机而不是简单 `CrossOver` 指标；当前版本保留同类状态切换语义。
- 原 EA 允许 `Reverse=true` 反转信号解释，当前版本同样保留。
- 原 EA 没有单独的主动反向平仓规则，主要依赖 `SL/TP` 与 trailing；当前版本按相同思路实现。

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 尚未补做本地回测校验，建议台账先标记为 `实施中`，后续再补齐样本结果。
