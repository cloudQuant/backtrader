# 0601 cheduecoglioni

## 策略概述

该策略是对 MT5 EA `0601_cheduecoglioni` 的 Backtrader 迁移版本。

- 仓位关闭后（触及 SL 或 TP），自动在相反方向开新仓
- 初始方向为 Sell
- 固定 SL/TP

## 核心逻辑

1. 初始开 Sell 仓位，设置固定 SL 和 TP。
2. 当仓位被止损或止盈关闭后，在相反方向开新仓位。
3. 如此循环交替 Buy/Sell。

## 迁移说明

- 原版通过 `OnTradeTransaction` 监听平仓事件切换方向；迁移版在 `notify_trade` 等价实现。
- 原版固定手数 `0.1`；迁移版保留对应参数。
- 原版在 `OrderSend` 前检查可用手数；迁移版简化此检查。

## 主要参数

- `lots` — 固定手数（默认 0.1）
- `take_profit` — 止盈点数（默认 10）
- `stop_loss` — 止损点数（默认 10）

## 运行方式

```bash
python run.py
```
