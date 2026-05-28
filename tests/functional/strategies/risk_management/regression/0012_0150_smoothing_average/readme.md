# 0150 平滑平均

## 策略概述

该样例是对 MT5 EA `0150_平滑平均` 的 Backtrader 迁移版。
原 EA 基于移动平均线与价格之间的 `delta` 偏离做单仓位交易，并支持 `reverse_signals` 开关反转开平仓方向。

## 迁移思路

1. 用典型价格 `(H+L+C)/3` 计算 MA
2. 保留 `ma_period / ma_shift / ma_method` 参数
3. 在空仓时按 `MA ± delta` 触发开仓
4. 在持仓时按 `MA ± delta * close_coefficient` 触发平仓
5. 保留 `reverse_signals` 反向语义

## 主要参数

- `fixed_lot`
- `ma_period`
- `ma_shift`
- `ma_method`
- `delta_pips`
- `delta_close_coefficient`
- `reverse_signals`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`./run.py`
- 绘图：`./run.py --plot`

## 当前回测结果

- Trades: `290`
- Net P&L: `44319.00`
- Win Rate: `17.93%`
- Profit Factor: `1.13`
- Max Drawdown: `42.86%`

## 对齐说明

- 原 EA 用 `iMA` 的 `PRICE_TYPICAL` 作为输入，当前版本按同一价格定义重建
- `ma_shift` 在 Backtrader 中近似为比较当前价格与向后偏移的 MA 值
- 由于离线回测中没有独立 `Bid/Ask` 流，当前实现用 bar close 作为双边报价近似
