# 0587 EveningStar

## 策略概述

该策略是对 MT5 EA `0587_EveningStar` 的 Backtrader 迁移版本。

- 基于三根 K 线的 Evening Star 形态检测
- 可选 gap、第二根 K 线类型、蜡烛大小过滤
- 固定 `SL/TP`

## 核心逻辑

1. 最近三根 K 线满足：第 3 根阳线、第 1 根阴线。
2. 可选要求：
   - 第 2 根 K 线大小小于两侧主 K 线
   - 第 2 根 K 线必须为指定方向
   - 需要满足 gap 条件
3. 形态成立后按 `evening_star` 参数指定方向入场。
4. `opposite_signal=true` 时先平反向仓位。

## 迁移说明

- 原版使用风险百分比动态算手数；迁移版简化为固定手数。
- 原版允许把 Evening Star 形态映射到买入或卖出，迁移版保留该参数化行为。

## 运行方式

```bash
python run.py
```
