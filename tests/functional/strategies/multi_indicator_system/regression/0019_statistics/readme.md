# 0605 Statistics (统计)

## 策略概述

该策略是对 MT5 EA `0605_Statistics(统计)` 的 Backtrader 迁移版本。

- 分析历史中与当前 K 线同一时刻（小时+分钟）的 K 线涨跌统计
- 阳线总长度 > 阴线总长度则做多，反之做空
- 固定 SL，亏损后手数按 martin 系数放大

## 核心逻辑

1. 每根新 K 线到来时先平掉已有仓位。
2. 回溯 `days_of_history` 天，找到与当前 K 线同 `hour:minute` 的历史 K 线。
3. 统计阳线总大小与阴线总大小（过滤低于 `candle_height` 的小蜡烛）。
4. 阳线总和 > 阴线总和 → Buy；反之 → Sell。
5. 亏损后手数乘以 `martin` 系数；盈利后恢复初始手数。

## 迁移说明

- 原版 `hedging only`；迁移版简化为单净仓，保留核心统计+入场逻辑。
- 原版 `OnTradeTransaction` 马丁格尔加码；迁移版在 `notify_trade` 等价实现。
- 原版固定手数 `0.1`；迁移版保留对应参数。

## 主要参数

- `candle_height` — 最小蜡烛高度过滤（0 为禁用）
- `lots` — 初始手数
- `stop_loss` — 止损点数
- `days_of_history` — 历史回溯天数
- `martin` — 亏损后手数放大系数

## 运行方式

```bash
python run.py
```
