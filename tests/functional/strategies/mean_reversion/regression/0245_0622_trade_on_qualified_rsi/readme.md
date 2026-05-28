# 0622 在有效RSI上交易 (Trade on Qualified RSI)

## 策略概述

该策略是对 MT5 EA `0622_在有效RSI上交易` 的 Backtrader 迁移版本。

- RSI(28) 反转入场 + 多 bar 确认
- 基于前一 bar 收盘价的移动止损
- 无止盈

## 核心逻辑

1. RSI[1] >= 55 且 RSI[2..2+count_bars] 全部 >= 55 → 做空（反转信号）。
2. RSI[1] <= 45 且 RSI[2..2+count_bars] 全部 <= 45 → 做多（反转信号）。
3. 每根 bar 用 close[-1] 重新计算止损距离，只向有利方向推进。

## 迁移说明

- 原 EA RSI 周期固定为 28；迁移版暴露为可配置。
- 原 EA 无止盈；迁移版保留原始行为。
- 反转逻辑保留原始意图：RSI 持续高位视为顶部信号 → 做空。

## 主要参数

- `rsi_period` / `rsi_upper` / `rsi_lower`
- `count_bars` / `stop_loss`

## 运行方式

```bash
python run.py
```
