# 1052 Elder Impulse System

## 策略概述

该策略是对 MT5 EA `1052_Exp_ElderImpulseSystem` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为 Elder Impulse System：EMA 方向与 MACD 柱变化共同决定柱子颜色与交易方向。

## 核心逻辑

1. 计算 EMA
2. 计算 MACD 柱状图
3. 当 EMA 上升且 MACD 柱增强时，视为绿色柱，多头有效
4. 当 EMA 下降且 MACD 柱减弱时，视为红色柱，空头有效
5. 颜色失配或转为中性时离场

## 主要参数

- `ema_period`
- `macd_fast`
- `macd_slow`
- `macd_signal`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `1338`
- Net P&L: `+3,187`
- Win Rate: `32.2%`
- Profit Factor: `1.05`
- Max Drawdown: `4.70%`

## 对齐说明

- 原 MT5 EA 属于 Kositsin `Exp_*` 模板，但其底层 Elder Impulse 逻辑可直接用内置指标近似复现
- 当前版本没有依赖外部 `.ex5` 指标，而是直接用 EMA + MACD histogram 构建信号
