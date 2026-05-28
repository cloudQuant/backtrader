# 1229 Vortex Indicator

## 策略概述

该策略是对 MT5 EA `1229_Exp_VortexIndicator` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为 Vortex Indicator 的 `VI+ / VI-` 交叉。

## 核心逻辑

1. 计算 Vortex Indicator
2. 当 `VI+` 上穿 `VI-` 时做多
3. 当 `VI+` 下穿 `VI-` 时做空
4. 反向交叉时平仓 / 反手

## 主要参数

- `vortex_period`
- `lot`
- `point`
- `price_digits`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `678`
- Net P&L: `+12,321`
- Win Rate: `39.4%`
- Profit Factor: `1.29`
- Max Drawdown: `5.11%`
