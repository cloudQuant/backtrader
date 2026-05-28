# 0577 Expert_RSI_Stochastic_MA

## 策略概述

该策略是对 MT5 EA `0577_Expert_RSI_Stochastic_MA` 的 Backtrader 迁移版本。

- MA 决定做多/做空方向
- RSI 与 Stochastic 同时进入超买/超卖区触发入场
- 按盈利/亏损状态结合 Stochastic 条件离场
- 可选 trailing stop 与 allow loss

## 核心逻辑

1. `price > MA` 时只考虑做多，`price < MA` 时只考虑做空。
2. 做多入场：`RSI < rsi_dn_level` 且 `Stochastic main/signal < st_dn_level`。
3. 做空入场：`RSI > rsi_up_level` 且 `Stochastic main/signal > st_up_level`。
4. 持仓后：
   - 盈利状态下按反向 Stochastic 区域触发 trailing 或直接离场
   - 亏损状态下按 `allow_loss` 与 Stochastic 条件离场

## 迁移说明

- 原版的离场逻辑较偏“状态机式”条件组合；迁移版保留主要行为，但以 Backtrader 单净仓模型近似实现。

## 运行方式

```bash
python run.py
```
