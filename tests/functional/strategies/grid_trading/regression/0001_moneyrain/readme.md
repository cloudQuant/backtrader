# 0647 MoneyRain

## 策略概述

该策略是对 MT5 EA `0647_MoneyRain` 的 Backtrader 迁移版本。

- DeMarker 震荡指标驱动入场
- 原版为马丁格尔手数管理；迁移版简化为固定手数
- 固定 SL/TP，单仓

## 核心逻辑

1. DeMarker > 0.5 → 做多。
2. DeMarker ≤ 0.5 → 做空。
3. 持仓使用固定 SL/TP 管理。

## 迁移说明

- 原 EA 使用基于历史亏损的马丁格尔手数；迁移版使用固定 `lots`。
- DeMarker 指标在 Backtrader 中手动实现（非内置）。

## 主要参数

- `demarker_period`
- `stop_loss` / `take_profit`
- `lots`

## 运行方式

```bash
python run.py
```
