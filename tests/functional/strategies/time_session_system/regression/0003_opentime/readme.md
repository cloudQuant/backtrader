# 0547 OpenTime

## 策略概述

该策略是对 MT5 EA `0547_OpenTime` 的 Backtrader 迁移版本。

- 在指定时间开仓
- 可选在指定时间统一平仓
- 支持固定 `SL/TP` 与 trailing stop

## 核心逻辑

1. 到达 `trade_hour:trade_minute` 时按配置方向开仓。
2. 若启用 `time_close`，则在 `close_hour:close_minute` 的窗口内平仓。
3. 若启用 trailing，则在持仓盈利后按 `trailing_stop` / `trailing_step` 移动保护止损。

## 迁移说明

- 原版可分别允许买卖并在 MT5 对冲模型下同时存在；迁移版在 Backtrader 单净仓模型下做单仓近似。
- 原版 `duration` 是秒级时间窗，迁移版按 bar 级时间近似处理。

## 运行方式

```bash
python run.py
```
