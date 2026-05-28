# 0617 Candle

## 策略概述

该策略是对 MT5 EA `0617_Candle` 的 Backtrader 迁移版本。

- 当前 K 线阳线做多、阴线做空
- 反向 K 线先平仓，再允许反手
- 初始 `SL` 使用 trailing stop 距离，固定 `TP`

## 核心逻辑

1. 若当前 K 线 `close > open`，则开多。
2. 若当前 K 线 `close < open`，则开空。
3. 多头遇到阴线先平仓，再允许反手做空；空头遇到阳线先平仓，再允许反手做多。
4. 持仓盈利后按 `trailing_stop` 距离推进止损。

## 迁移说明

- 原 EA 使用当前 K 线实体方向直接交易，未使用独立指标入场。
- 原版开仓时直接把 `TrailingStop` 同时作为初始止损距离；迁移版保留这一行为。
- 原版 `InpMinBars` 仅作为最小历史长度门槛；迁移版保留对应 warmup 约束。

## 主要参数

- `take_profit`
- `trailing_stop`
- `min_bars`
- `lots`

## 运行方式

```bash
python run.py
```
