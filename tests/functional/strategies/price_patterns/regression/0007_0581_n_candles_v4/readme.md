# 0581 N_Candles_v4

## 策略概述

该策略是对 MT5 EA `0581_N_Candles_v4` 的 Backtrader 迁移版本。

- 搜索连续 `N` 根同方向 K 线
- 连续阳线后做多，连续阴线后做空
- 加入“净头寸最大成交量”约束
- 固定 `SL/TP` 与 trailing stop

## 核心逻辑

1. 若最近 `N` 根已完成 K 线全部同向，则产生方向信号。
2. 在净头寸模式下，只有当前净头寸绝对量加上新一层手数不超过 `max_position_volume` 时才允许继续加仓。
3. 持仓后使用固定 `SL/TP` 和 trailing stop 管理。

## 迁移说明

- 原版区分 MT5 的 `hedging` 和 `netting` 账户模式；迁移版采用 Backtrader 单净仓模型，因此更接近原版的 `netting` 语义。

## 运行方式

```bash
python run.py
```
