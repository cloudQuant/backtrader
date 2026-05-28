# 0633 EMA

## 策略概述

该策略是对 MT5 EA `0633_EMA` 的 Backtrader 迁移版本。

- 双 EMA(5/10) 交叉（使用 PRICE_MEDIAN）
- 交叉后等待确认：EMA 差距 > 2 点 + 价格回撤至前 bar 高低点附近
- 虚拟 SL/TP（基于入场价距离判断平仓）

## 核心逻辑

1. EMA(5) 与 EMA(10) 交叉 → 标记 `check=1`。
2. `check=1` 时，EMA10 - EMA5 > 2*point 且价格 >= Low[-1]+MoveBack → 做空。
3. `check=1` 时，EMA5 - EMA10 > 2*point 且价格 <= High[-1]-MoveBack → 做多。
4. 虚拟止盈 `virtual_profit_pips` 点，虚拟止损 `stop_loss` 点。

## 迁移说明

- 原 EA 指标参数固定在代码中；迁移版将其暴露为可配置参数。
- SL/TP 为虚拟方式（按 bar 收盘价判断），非挂单。

## 主要参数

- `ema_fast_period` / `ema_slow_period`
- `virtual_profit_pips` / `stop_loss`
- `move_back`

## 运行方式

```bash
python run.py
```
