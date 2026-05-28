# 0498 Momo_trades

## 策略概述

该策略是对 MT5 EA `0498_Momo_trades` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为 `MACD 主线转正/转负` 配合 `SMA` 位置过滤，只在空仓时入场，并保留固定止损、盈亏平衡与尾盘平仓控制。

## 核心逻辑

1. 计算 `MACD main line` 与 `SMA`
2. 读取从 `MACD bar = 2` 开始的历史片段，识别主线由负转正或由正转负的动量结构
3. 当 `close[ma_bar] - SMA[ma_bar]` 大于价格偏移阈值时允许做多
4. 当 `SMA[ma_bar] - close[ma_bar]` 大于价格偏移阈值时允许做空
5. 若 `take_profit_pips = 0`，则启用 `breakeven`；否则可配合 `trailing_stop_pips` 做移动止损
6. 若到达日终截止小时，持仓强制平仓

## 主要参数

- `manual_lot`
- `lot`
- `stop_loss_pips`
- `take_profit_pips`
- `trailing_stop_pips`
- `breakeven_pips`
- `price_shift_pips`
- `ma_period`
- `ma_bar`
- `fast_ema_period`
- `slow_ema_period`
- `signal_period`
- `macd_bar`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

 ## 当前回测结果

 - Trades: `122`
 - Net P&L: `-1,138.30`
 - Win Rate: `47.54%`
 - Profit Factor: `0.78`
 - Max Drawdown: `2.31%`

## 对齐说明

- 原 EA 支持手工手数和基于可用保证金的风险仓位；当前迁移版本默认使用手工手数，并提供近似的风险仓位换算
- 原 EA 在 MT5 逐 tick 环境下执行 `breakeven / trailing / end-of-day close`；当前版本基于 bar 级 `OHLC` 做近似回放
- 原 EA 只在空仓时开新仓，当前版本保持相同约束
