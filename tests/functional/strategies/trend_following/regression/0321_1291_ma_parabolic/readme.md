# 1291 MA + Parabolic SAR

## 策略概述

该策略是对 MT5 EA `1291_Exp_ColorX2MA-Parabolic` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为 EMA 趋势方向配合 Parabolic SAR 翻转信号。

## 核心逻辑

1. 计算 EMA 方向
2. 计算 Parabolic SAR
3. 当价格 / SAR 关系与 EMA 趋势共同指向多头时做多
4. 当价格 / SAR 关系与 EMA 趋势共同指向空头时做空
5. SAR 翻转或趋势失效时平仓 / 反手

## 主要参数

- `ema_period`
- `sar_af`
- `sar_afmax`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `522`
- Net P&L: `+8,589`
- Win Rate: `39.3%`
- Profit Factor: `1.17`
- Max Drawdown: `5.30%`
