# 0539 Alligator

## 策略概述

该策略是对 MT5 EA `0539_Alligator` 的 Backtrader 迁移版本。

- 使用 `Alligator` 三线顺序判定方向
- 使用固定 `SL/TP`
- 支持 breakeven 与 trailing stop

## 核心逻辑

1. 当 `Lips > Teeth > Jaw` 时做多。
2. 当 `Lips < Teeth < Jaw` 时做空。
3. 持仓盈利达到 `zero_level` 后先把止损移到开仓价。
4. 随后按 `trailing_stop` 与 `trailing_step` 推动保护止损。

## 迁移说明

- 原版使用 MT5 的 `iAlligator` 指标句柄；迁移版用 Backtrader 平滑均线等价重建。
- 原版在每根新 bar 上检查信号，迁移版保持同样的 bar 级节奏。

## 运行方式

```bash
python run.py
```
