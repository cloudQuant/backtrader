# 0641 Currencyprofits

## 策略概述

该策略是对 MT5 EA `0641_Currencyprofits_01.1` 的 Backtrader 迁移版本。

- 双 SMA 趋势判断 + 6-bar 高低点突破入场
- 反向突破平仓
- 固定 SL，无 TP（通过突破平仓退出）

## 核心逻辑

1. `MA_fast[-1] > MA_slow[-1]` 且 `price <= 6-bar lowest` → 做多。
2. `MA_fast[-1] < MA_slow[-1]` 且 `price >= 6-bar highest` → 做空。
3. 持多时 `price >= 6-bar highest` → 平仓。
4. 持空时 `price <= 6-bar lowest` → 平仓。

## 迁移说明

- 原 EA 使用 `CMoneyFixedMargin` 手数管理；迁移版简化为固定手数。
- 原 EA 要求对冲账户；迁移版按单净仓实现。

## 主要参数

- `ma_period_first` / `ma_period_second`
- `stop_loss`
- `lots`

## 运行方式

```bash
python run.py
```
