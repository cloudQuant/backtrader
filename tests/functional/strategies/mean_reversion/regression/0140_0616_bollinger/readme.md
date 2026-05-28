# 0616 Bollinger

## 策略概述

该策略是对 MT5 EA `0616_Bollinger` 的 Backtrader 迁移版本。

- 基于 Bollinger Bands（`iBands`）均值回归思路
- 价格突破上轨且低点在中轨之上则做空
- 价格突破下轨且高点在中轨之下则做多

## 核心逻辑

1. Buy：当前 K 线 `Low < LowerBand` 且 `High < MiddleBand`。
2. Sell：当前 K 线 `High > UpperBand` 且 `Low > MiddleBand`。
3. 无 SL / TP；持仓盈利时允许反向切换（先平再反手），亏损时不切换。

## 迁移说明

- 原版无止损止盈，迁移版保留此行为。
- 原版 `lot=0.01` 固定手数；迁移版保留对应参数。
- 原版反手条件要求当前持仓盈利 (`POSITION_PROFIT > 0`)；迁移版在 `next()` 中等价实现。

## 主要参数

- `bands_period` — Bollinger Bands 周期（默认 80）
- `deviation` — 标准差倍数（默认 3.0）
- `lots` — 固定手数

## 运行方式

```bash
python run.py
```
