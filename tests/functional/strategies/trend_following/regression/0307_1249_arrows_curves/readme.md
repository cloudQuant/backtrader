# 1249 Arrows Curves

## 策略概述

该策略是对 MT5 EA `1249_Exp_Arrows_Curves` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，并在内部重建 `H4` 的 `Arrows_Curves` 信号流。

## 核心逻辑

1. 在 `H4` 上按原始 `Arrows_Curves` 指标源码计算买卖箭头与止损叉号
2. 出现 `Buy` 箭头时做多，并可同步平掉空头
3. 出现 `Sell` 箭头时做空，并可同步平掉多头
4. 出现 `BuyStop / SellStop` 叉号时只执行平仓信号
5. 同时保留固定点数止损与止盈

## 主要参数

- `ssp`
- `channel`
- `ch_stop`
- `relay`
- `stop_loss_points`
- `take_profit_points`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 说明

原 MT5 EA 通过 `iCustom(..., "Arrows_Curves", SSP, Channel, Ch_Close, relay)` 获取 `Buy/Sell/BuyStop/SellStop` 四类信号。
本迁移版直接依据仓库内 `arrows_curves.mq5` 源码预计算信号，不依赖额外 `.ex5` 文件。
