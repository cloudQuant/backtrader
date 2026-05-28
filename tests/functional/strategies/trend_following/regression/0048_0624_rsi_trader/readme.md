# 0624 RSI Trader v0.15

## 策略概述

该策略是对 MT5 EA `0624_RSI_trader_v0.15` 的 Backtrader 迁移版本。

- RSI 均线化 + 双价格 MA 交叉确认
- 可选方向反转
- 无 SL/TP（纯信号进出）

## 核心逻辑

1. RSI(14) 分别做 SMA(9) 和 SMA(45) 平滑。
2. 价格上做 SMA(9) 和 LWMA(45)。
3. RSI_Short > RSI_Long 且 MA_Short > MA_Long → 做多。
4. RSI_Short < RSI_Long 且 MA_Short < MA_Long → 做空。
5. `reverse=true` 时信号方向翻转。

## 迁移说明

- 原 EA 无 SL/TP（sl=0, tp=0）；迁移版保留原始行为。
- 原 EA 使用 1.0 手；迁移版默认改为 0.1 手适配 XAUUSD。

## 主要参数

- `rsi_period` / `short_rsi_ma` / `long_rsi_ma`
- `ma_short_period` / `ma_long_period`
- `reverse`

## 运行方式

```bash
python run.py
```
