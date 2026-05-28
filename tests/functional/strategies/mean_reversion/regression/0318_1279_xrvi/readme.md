# 1279 XRVI

## 策略概述

该策略是对 MT5 EA `1279_Exp_XRVI` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为先构造 `RVI=(close-open)/(high-low)`，再做两次平滑得到 `XRVI` 主线和信号线，并在二者交叉时交易。

## 核心逻辑

1. 计算单柱 `RVI`
2. 对 `RVI` 做第一次平滑，得到 `XRVI`
3. 对 `XRVI` 做第二次平滑，得到 `signal`
4. 当 `XRVI` 与 `signal` 交叉时开仓或反手

## 主要参数

- `rvi_method`
- `rvi_period`
- `rvi_phase`
- `sign_method`
- `sign_period`
- `sign_phase`
- `signal_bar`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `18`
- Net P&L: `99.10`
- Win Rate: `50.00%`
- Profit Factor: `1.42`
- Max Drawdown: `0.11%`
