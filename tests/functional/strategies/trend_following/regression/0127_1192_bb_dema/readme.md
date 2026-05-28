# 1192 Bollinger Bands + DEMA

## 策略概述

该策略是对 MT5 EA `1192_基于布林带的EA交易` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为 Bollinger Band 结构配合 DEMA 方向过滤。

## 核心逻辑

1. 计算 Bollinger Bands
2. 计算 DEMA 作为趋势过滤
3. 当价格与布林带边界形成突破/回归信号，且 DEMA 方向一致时开仓
4. 当价格重新回到均值附近或方向失效时离场

## 主要参数

- `bb_period`
- `bb_dev`
- `dema_period`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `72`
- Net P&L: `-2,403`
- Win Rate: `59.7%`
- Profit Factor: `0.78`
- Max Drawdown: `5.46%`
