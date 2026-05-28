# 1210 CandleTrend

## 策略概述

该策略是对 MT5 EA `1210_Exp_CandleTrend` 的 Backtrader 迁移版本。
原 EA 不依赖指标，只统计指定数量的同向 K 线，作为开平仓触发条件。

## 核心逻辑

1. 读取指标周期上的 `open/close`
2. 统计最近 `CandleTrendTotal` 根 K 线的方向
3. 若全部为阳线则做多并平空
4. 若全部为阴线则做空并平多

## 主要参数

- `candle_trend_total`
- `signal_bar`
- `stop_loss_points`
- `take_profit_points`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`
