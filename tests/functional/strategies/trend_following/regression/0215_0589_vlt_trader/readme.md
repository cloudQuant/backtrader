# 0589 VLT_TRADER

## 策略概述

该策略是对 MT5 EA `0589_VLT_TRADER` 的 Backtrader 迁移版本。

- 寻找最近若干 K 线中的最小波动蜡烛
- 若上一根 K 线的波动比这些都更小，则同时挂上下突破单
- 上破做多，下破做空

## 核心逻辑

1. 当前新 bar 到来时，先检查上一根 K 线的振幅 `VLT_1`。
2. 在更早的 `count_candles` 根 K 线中寻找最小振幅 `VLT_minimum`。
3. 若 `VLT_1 < VLT_minimum`，则：
   - 挂 `BuyStop` 在上一根高点上方 10 点
   - 挂 `SellStop` 在上一根低点下方 10 点
4. 触发后使用固定 `SL/TP`。

## 迁移说明

- 原版是双边挂单模式；迁移版在 `next()` 中用价格穿越模拟挂单触发。
- 原版会分别删除旧的 `BuyStop / SellStop`；迁移版每次新信号直接覆盖待触发设置。

## 运行方式

```bash
python run.py
```
