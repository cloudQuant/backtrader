# 0536 Nova

## 策略概述

该策略是对 MT5 EA `0536_Nova` 的 Backtrader 迁移版本。

- 比较当前价格与 `N-seconds ago` 的价格变化
- 结合上一根 K 线方向决定多空
- 触发止损后按 `coefficient` 放大下一笔手数

## 核心逻辑

1. 若上一根 K 线收阳，并且当前价格高于 `N-seconds ago` 的价格超过 `step`，则做多。
2. 若上一根 K 线收阴，并且当前价格低于 `N-seconds ago` 的价格超过 `step`，则做空。
3. 每笔交易使用固定 `SL/TP`。
4. 若上一笔因止损亏损，则下一笔手数按 `coefficient` 放大；若盈利，则恢复初始手数。

## 迁移说明

- 原版依赖秒级 tick 记忆与 `DEAL_REASON_SL/TP`；迁移版在 bar 级别近似为比较若干 bar 前的价格，并用上一笔盈亏结果维护手数状态。

## 运行方式

```bash
python run.py
```
