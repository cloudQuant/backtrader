# 0490 Breakthrough_BB

## 策略概述

该策略是对 MT5 EA `0490_Breakthrough_BB` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为在均线方向过滤下捕捉布林带上/下轨突破，并在价格反穿中轨时退出。

## 核心逻辑

1. 使用 `SMA` 作为方向过滤器
2. 使用 `Bollinger Bands` 判断突破
3. 若 `close[4] < upper_band[1]` 且 `close[1] > upper_band[1]`，并且 `MA[1] > MA[4]`，则做多
4. 若 `close[4] > lower_band[1]` 且 `close[1] < lower_band[1]`，并且 `MA[1] < MA[4]`，则做空
5. 持有多头时，若 `close[1] < middle_band[1]` 则离场
6. 持有空头时，若 `close[1] > middle_band[1]` 则离场

## 主要参数

- `ma_period`
- `bands_period`
- `deviation`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

 ## 当前回测结果

 - Trades: `224`
 - Net P&L: `+4,402.20`
 - Win Rate: `33.04%`
 - Profit Factor: `1.15`
 - Max Drawdown: `5.77%`

## 对齐说明

- 原源码的 `OpenBuy/OpenSell` 实际传入 `0.0, 0.0`，因此当前迁移版本不额外引入固定止损/止盈
- 原说明提到买入止损应设置在布林带下轨下方，但该逻辑未在 EA 源码中实现；当前版本以源码行为为准
- 原 EA 仅允许单仓；当前 Backtrader 版本保持相同约束
