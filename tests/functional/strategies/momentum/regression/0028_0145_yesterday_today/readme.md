# 0145 昨天今天

## 策略概述

该样例是对 MT5 EA `0145_昨天今天` 的 Backtrader 迁移版。
原 EA 将当前价格与前一交易日的高点、低点比较：突破前一日高点做多，跌破前一日低点做空，并保持单仓位交易。

## 迁移思路

1. 使用 `M15` 行情作为执行级别
2. 从同一份基础数据重采样出 `D1` 数据，提取前一完成日的 `high/low`
3. 当当前 bar 的 `close` 上破前一日高点时开多
4. 当当前 bar 的 `close` 下破前一日低点时开空
5. 保留固定 `stop_loss_pips / take_profit_pips`

## 主要参数

- `fixed_lot`
- `stop_loss_pips`
- `take_profit_pips`
- `point_size`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`./run.py`
- 绘图：`./run.py --plot`

## 当前回测结果

- Trades: `1292`
- Net P&L: `-115625.00`
- Win Rate: `28.17%`
- Profit Factor: `0.77`
- Max Drawdown: `129.53%`

## 对齐说明

- 原 EA 使用 D1 高低点与当前价格比较，当前版本用同源 M15 数据重采样生成 D1 参考线
- 原 EA 在出现反向信号时会先平掉对手仓，再等待下一次满足条件时重新开仓；当前单净头寸近似为“仅在空仓时开仓”
- 由于离线回测没有独立 `Bid/Ask`，当前版本以 bar close 近似触发突破判断
