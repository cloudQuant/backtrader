# 0583 IStochastic_Trading

## 策略概述

该策略是对 MT5 EA `0583_IStochastic_Trading` 的 Backtrader 迁移版本。

- 使用随机指标主线/信号线关系做首笔入场
- 达到反向 `gap` 后按 `2x` 量级继续同向加仓
- 固定 `SL/TP` 与 trailing stop

## 核心逻辑

1. 空仓时：
   - `main > signal` 且 `signal < zone_buy` 做多
   - `main < signal` 且 `signal > zone_sell` 做空
2. 已有持仓且层数未超过 `max_positions` 时：
   - 多头若价格相对最近一层入场价下跌超过 `gap`，再加一层，手数翻倍
   - 空头若价格上涨超过 `gap`，再加一层，手数翻倍
3. 持仓后按固定 `SL/TP` 和 trailing stop 管理。

## 迁移说明

- 原版在 MT5 中为每一层单独下单；迁移版在 Backtrader 单净仓模型下按“层”近似并记录最近一层价格/手数。

## 运行方式

```bash
python run.py
```
