# 0516 GreenTrade

## 策略概述

该策略是对 MT5 EA `0516_GreenTrade` 的 Backtrader 迁移版本。

- 比较四个移位后的 `SMMA(median price)` 值
- 用 `RSI` 水平确认方向
- 固定 `SL/TP`
- 支持多笔同向持仓和 trailing

## 核心逻辑

1. 当四个移位后的 MA 值严格递增，且 `RSI` 高于买入阈值时，开多。
2. 当四个移位后的 MA 值严格递减，且 `RSI` 低于卖出阈值时，开空。
3. 每笔仓位带固定 `SL/TP`。
4. 持仓盈利达到 trailing 触发条件后，按 `Trailing Stop` 与 `Trailing Step` 推进止损。

## 迁移说明

- 原版允许多笔仓位，迁移版保留了分 tranche 的近似管理。
- 原版 `Max position` 判断在边界上略松，迁移版按更直观的上限处理。

## 运行方式

```bash
python run.py
```
