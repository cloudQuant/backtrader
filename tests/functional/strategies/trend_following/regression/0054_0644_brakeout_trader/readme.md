# 0644 Brakeout Trader v1

## 策略概述

该策略是对 MT5 EA `0644_Brakeout_Trader_v1` 的 Backtrader 迁移版本。

- 人工设定突破价格水平
- 收盘价穿越该水平即触发入场
- 固定 SL/TP，单仓

## 核心逻辑

1. `Close[-1] > AppPrice` 且 `Close[-2] <= AppPrice` → 做多。
2. `Close[-1] < AppPrice` 且 `Close[-2] >= AppPrice` → 做空。
3. 若持有反向仓位且出现新的突破信号，则先平掉反向仓位再按新方向重入。
4. 可通过 `buys`/`sells` 参数限制只做单方向。
5. 持仓使用固定 SL/TP 管理。

## 迁移说明

- 原 EA 使用 `CMoneyFixedMargin` 手数管理；迁移版简化为固定手数。
- `app_price` 需根据实际品种价格区间设置。

## 主要参数

- `app_price`
- `stop_loss` / `take_profit`
- `buys` / `sells`
- `lots`

## 运行方式

```bash
python run.py
```
