# 0600 布林带的 N 个仓位

## 策略概述

该策略是对 MT5 EA `0600_布林带的_N_个仓位` 的 Backtrader 迁移版本。

- Bollinger Bands 突破后同向分层加仓
- 达到反向信号时先平掉反向仓位，再切换方向
- 固定 `SL/TP` 与 trailing stop

## 核心逻辑

1. `close > upper band` 视为做多信号。
2. `close < lower band` 视为做空信号。
3. 同方向持仓层数未达到 `max_positions` 时，继续按固定手数叠加。
4. 使用共享的聚合 `SL/TP` 与 trailing stop 管理净持仓。

## 迁移说明

- 原 EA 是 `hedging only` 且允许多笔同向独立仓位；迁移版在 Backtrader 单净仓框架下等价为按层数增加净头寸。
- 原版源码与说明在“买入信号时关闭哪一侧仓位”上存在不一致；迁移版按说明文档保留“同向开仓、反向切换”的核心意图。

## 运行方式

```bash
python run.py
```
