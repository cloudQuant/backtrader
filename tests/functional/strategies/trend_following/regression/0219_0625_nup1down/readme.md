# 0625 NUp1Down

## 策略概述

该策略是对 MT5 EA `0625_NUp1Down` 的 Backtrader 迁移版本。

- N 根阳线（每根收盘高于前根收盘）+ 1 根阴线 → 做空
- 移动止损
- 固定 SL/TP，单仓

## 核心逻辑

1. 检测最近 `n_bars_up` 根连续阳线且收盘逐步上升。
2. 当前 bar 为阴线（close < open）→ 做空。
3. 盈利后按 `trailing_stop` / `trailing_step` 推进止损。

## 迁移说明

- 原 EA 使用 `CMoneyFixedMargin` 手数管理；迁移版简化为固定手数。
- 原 EA 只做空（均值回归思路）；迁移版保留原始单方向逻辑。

## 主要参数

- `n_bars_up`
- `stop_loss` / `take_profit`
- `trailing_stop` / `trailing_step`

## 运行方式

```bash
python run.py
```
