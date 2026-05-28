# 1273 CorrectedAverage

## 策略概述

该策略是对 MT5 EA `1273_Exp_CorrectedAverage` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为先构造 `CorrectedAverage` 修正均线，再依据价格相对均线的阈值超出与回归来触发交易。

## 核心逻辑

1. 先计算基础均线与滚动标准差
2. 用 `k = 1 - std^2 / delta^2` 的方式递推修正均线
3. 设定突破阈值 `Level`
4. 当价格先突破 `CorrectedAverage ± Level`，随后回到阈值内时开仓或反手

## 主要参数

- `ma_method`
- `length`
- `applied_price`
- `level`
- `signal_bar`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `53`
- Net P&L: `-2,223.50`
- Win Rate: `39.62%`
- Profit Factor: `0.53`
- Max Drawdown: `3.64%`
