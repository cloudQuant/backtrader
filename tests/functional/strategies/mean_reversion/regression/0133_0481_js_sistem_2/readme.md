# 0481 JS_SISTEM_2

## 策略概述

该策略是对 MT5 EA `0481_JS_SISTEM_2` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为三条 EMA 排列确认方向，`OsMA` 与 `RVI` 共振确认动量，并在反向信号出现时切换仓位，同时可选基于最近波动区间的影线 trailing。

## 核心逻辑

1. 计算 `EMA(55)`、`EMA(89)`、`EMA(144)`、`OsMA(13,55,21)` 与 `RVI(44)`
2. 多头入场：`OsMA[1] > 0`、`RVI主线[1] > RVI信号线[1]`、`RVI信号线[1] >= 0.04`、三均线多头排列，且 `EMA(55)-EMA(144)` 小于阈值
3. 空头入场：`OsMA[1] < 0`、`RVI主线[1] < RVI信号线[1]`、`RVI信号线[1] <= -0.04`、三均线空头排列，且 `EMA(144)-EMA(55)` 小于阈值
4. 若反向信号出现，则先平掉反向单，再切换到新方向
5. 使用固定 `SL/TP`
6. 可选根据最近 `volatility` 根 K 线的高低点更新 trailing stop

## 主要参数

- `lots`
- `stop_loss_pips`
- `take_profit_pips`
- `volatility`
- `min_difference`
- `ma_1_period`
- `ma_2_period`
- `ma_3_period`
- `osma_fast_ema_period`
- `osma_slow_ema_period`
- `osma_signal_period`
- `rvi_ma_period`
- `rvi_max`
- `rvi_min`
- `trailing_shadows`
- `indent_sl`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `0`
- Net P&L: `0.00`
- Win Rate: `0.00%`
- Profit Factor: `N/A`
- Max Drawdown: `0.00%`

## 对齐说明

- 原 EA 只在新 bar 运行，当前版本保持上一根柱取值与 bar 级决策
- 原 EA 的 trailing shadow 基于单独配置的更低时间周期；当前示例在仓库统一的 `XAUUSD M15` 数据上用当前周期近似该逻辑
- 原 EA 支持风险百分比算手数；当前示例默认按固定手数 `0.01` 回测
