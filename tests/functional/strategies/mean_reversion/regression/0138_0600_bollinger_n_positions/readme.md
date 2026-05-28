# 0600 布林带的 N 个仓位

## 策略概述

该策略是对 MT5 EA `0600_布林带的_N_个仓位` 的 Backtrader 迁移版本。

- 基于 Bollinger Bands 突破入场
- 价格 > 上轨做空（先平多仓）；价格 < 下轨做多（先平空仓）
- 固定 SL/TP + 移动止损

## 核心逻辑

1. **Sell**: `Bid > Upper Band` → 平掉所有 Buy 仓位后做空。
2. **Buy**: `Ask < Lower Band` → 平掉所有 Sell 仓位后做多。
3. 固定 SL/TP 点数。
4. 移动止损：当浮盈达到 `trailing_stop` 点数后开始推进，步长 `trailing_step`。

## 迁移说明

- 原版 `hedging only`，支持最多 N 个同向仓位；迁移版简化为单净仓，保留核心 BB 入场 + 反向切换逻辑。
- 原版在 `OrderSend` 前检查双倍手数所需资金；迁移版简化此检查。
- 原版图表标记（箭头颜色）已省略。

## 主要参数

- `bb_period` — BB 周期（默认 20）
- `bb_deviation` — 标准差倍数（默认 2.0）
- `stop_loss` / `take_profit` — SL/TP 点数
- `trailing_stop` / `trailing_step` — 移动止损参数
- `lots` — 固定手数

## 运行方式

```bash
python run.py
```
