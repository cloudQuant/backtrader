# 0554 up3x1_Investor

## 策略概述

该策略是对 MT5 EA `0554_up3x1_Investor` 的 Backtrader 迁移版本。

- 基于上一根 K 线的大实体突破形态开仓
- 支持固定 `SL/TP`
- 支持 trailing stop
- 保留了简化的亏损后降仓逻辑

## 核心逻辑

1. 当上一根 K 线振幅超过 `difference_h1_l1`，并且实体长度超过 `difference_o1_c1` 时考虑开仓。
2. 若上一根 K 线为大阳线则做多。
3. 若上一根 K 线为大阴线则做空。
4. 持仓后用固定止盈止损与 trailing stop 管理。

## 迁移说明

- 原版包含基于可用保证金和历史亏损笔数的动态手数计算；迁移版保留了一个更轻量的 `decreased_factor` 近似实现。
- 原版只在空仓时开新仓，迁移版保持同样约束。

## 运行方式

```bash
python run.py
```
