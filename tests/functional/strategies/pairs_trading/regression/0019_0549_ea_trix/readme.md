# 0549 EA_Trix

## 策略概述

该策略是对 MT5 EA `0549_EA_Trix` 的 Backtrader 迁移版本。

- 使用 `TRIX` 与 `Signal` 交叉箭头开仓
- 反向箭头平仓并反手
- 支持 break-even 与 trailing stop

## 核心逻辑

1. 计算三重 EMA 收益率形式的 `TRIX` 主线与信号线。
2. 当信号线向上穿越主线时做多。
3. 当信号线向下穿越主线时做空。
4. 出现反向信号时先平当前持仓，再按新方向开仓。
5. 持仓期间使用 `break_even` 和 trailing stop 管理。

## 迁移说明

- 原版依赖本地 `TRIX ARROWS` 指标；迁移版直接在 Backtrader 中重建其核心三重 EMA 交叉逻辑。
- 原版 `trade_at_close_bar` 对应 MT5 当前/收盘柱读取方式，迁移版做了等价近似。

## 运行方式

```bash
python run.py
```
