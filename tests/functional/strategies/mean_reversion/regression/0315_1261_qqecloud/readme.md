# 1261 QQECloud

## 策略概述

该策略是对 MT5 EA `1261_Exp_QQECloud` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为使用 `QQECloud` 云层方向确定做多或做空，并在固定开仓/平仓时点执行交易。

## 核心逻辑

1. 计算平滑 RSI 与动态跟踪线，形成 `QQECloud` 双缓冲区
2. 当 `Up > Down` 时视为多头云层，反之为空头云层
3. 只有在固定开仓时刻才允许按当前云层方向开仓
4. 在固定平仓时刻或时间越界时强制平仓

## 主要参数

- `start_hour`
- `start_minute`
- `stop_hour`
- `stop_minute`
- `rsi_period`
- `sf`
- `darfactor`
- `xma_method`
- `xphase`
- `signal_bar`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `67`
- Net P&L: `-36.60`
- Win Rate: `62.69%`
- Profit Factor: `1.00`
- Max Drawdown: `6.75%`
