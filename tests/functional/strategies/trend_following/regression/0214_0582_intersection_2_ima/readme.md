# 0582 Intersection_2_iMA

## 策略概述

该策略是对 MT5 EA `0582_Intersection_2_iMA` 的 Backtrader 迁移版本。

- 基于快慢 EMA 的交叉信号
- 相反信号先平仓，再等待新方向入场
- 带 trailing stop

## 核心逻辑

1. 使用 `EMA(fast_per)` 与 `EMA(slow_per)`。
2. 若 `bar1` 与 `bar3` 的快慢关系发生反转，则产生交叉信号。
3. 买入信号出现时先关闭空仓；卖出信号出现时先关闭多仓。
4. 持仓期间使用 trailing stop 保护。

## 迁移说明

- 原版支持动态手数与 `close half` 参数；迁移版简化为固定手数，并未实现半仓逻辑。

## 运行方式

```bash
python run.py
```
