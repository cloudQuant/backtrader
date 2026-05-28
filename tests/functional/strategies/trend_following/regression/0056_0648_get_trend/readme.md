# 0648 Get Trend

## 策略概述

该策略是对 MT5 EA `0648_Get_trend` 的 Backtrader 迁移版本。

- 双周期 MA 趋势确认 + Stochastic 超买超卖入场
- 原 EA 使用 `M15 + H1` 双时间框架；迁移版用同一数据流上的快/慢 `SMMA(PRICE_MEDIAN)` 近似
- 固定 `SL/TP` + trailing stop，单仓

## 核心逻辑

1. 价格低于快慢 MA 且距离不超过 `porog` 点。
2. Stochastic 主线在 20 以下且从下穿越信号线 → 做多。
3. 价格高于快慢 MA 且距离不超过 `porog` 点。
4. Stochastic 主线在 80 以上且从上穿越信号线 → 做空。
5. 持仓盈利后按 `trailing_stop` 距离推进止损。

## 迁移说明

- 原 EA 限定 `M15` 周期，并使用 `SMMA(99, PRICE_MEDIAN)` 与 `H1 SMMA(184, PRICE_MEDIAN)`；迁移版用同数据流上的 `99/184` 平滑均线近似多周期趋势过滤。
- 示例使用原始 M15 数据直接运行。

## 主要参数

- `ma_period_fast` / `ma_period_slow`
- `stoch_k` / `stoch_d` / `stoch_slow_d`
- `porog`
- `stop_loss` / `take_profit` / `trailing_stop`

## 运行方式

```bash
python run.py
```
