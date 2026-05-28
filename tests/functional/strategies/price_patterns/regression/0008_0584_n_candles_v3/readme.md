# 0584 N_Candles_v3

## 策略概述

该策略是对 MT5 EA `0584_N_Candles_v3` 的 Backtrader 迁移版本。

- 搜索连续 `N` 根同方向 K 线
- 连续阳线后做多，连续阴线后做空
- 支持同方向最多 `max_positions` 层
- 固定 `SL/TP` 与 trailing stop

## 核心逻辑

1. 读取最近 `N` 根已完成 K 线。
2. 若全部为阳线，则产生做多信号；若全部为阴线，则产生做空信号。
3. 同方向层数未达到 `max_positions` 时继续加仓。
4. 持仓后使用固定 `SL/TP` 和 trailing stop 管理。

## 迁移说明

- 原版在 MT5 对冲账户上可同时存在多空独立持仓；迁移版在 Backtrader 中采用净头寸和分层加仓近似。

## 运行方式

```bash
python run.py
```
