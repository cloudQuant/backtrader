# 1293 JBrainSig1 UltraRSI

## 策略概述

该策略是对 MT5 EA `1293_Exp_JBrainSig1_UltraRSI` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为将 `JBrainTrend1Sig` 箭头方向信号与 `UltraRSI` 云层切换信号进行组合过滤，并在确认同向时入场或反手。

## 核心逻辑

1. `JBrainTrend1Sig` 使用 `ATR + Stochastic + 平滑高低收` 生成买卖箭头
2. `UltraRSI` 使用多周期 RSI 平滑方向计数构造多头/空头云层
3. 默认 `Composition` 模式下，只要任一侧提供开仓信号且另一侧同时给出同向确认，就执行入场
4. 当两类信号同时要求对应平仓时执行离场
5. 反向开仓信号出现时执行反手

## 主要参数

- `mode`
- `signal_bar`
- `atr_period`
- `sto_period`
- `ma_method`
- `xlength`
- `rsi_period`
- `applied_price`
- `w_method`
- `start_length`
- `nstep`
- `nsteps_total`
- `smooth_method`
- `smooth_length`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `1`
- Net P&L: `-9,704.40`
- Win Rate: `0.00%`
- Profit Factor: `N/A`
- Max Drawdown: `14.07%`
