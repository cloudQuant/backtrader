# 0106 夺宝奇兵均值回复_EA

## 策略概述

该样例是对 MT5 EA `0106_夺宝奇兵均值回复_EA` 的 Backtrader 迁移版。
原 EA 的逻辑非常直接：当价格触及 `lookback` 区间最低点时做多、目标回到区间均值；当价格触及 `lookback` 区间最高点时做空、目标同样回到区间均值，并用对称方式设置止损。

## 迁移思路

1. 使用 `lookback` 窗口计算最高价与最低价
2. 将均值定义为 `(highest + lowest) / 2`
3. 当当前 bar 触及窗口最低点时做多
4. 当当前 bar 触及窗口最高点时做空
5. `tp = mean`，`sl = 2 * entry - tp`
6. 根据 `risk_per_trade` 近似计算下单手数

## 主要参数

- `lookback`
- `risk_per_trade`
- `min_lot`
- `lot_step`
- `max_lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`./run.py`
- 绘图：`./run.py --plot`

## 当前回测结果

- Trades: `31`
- Net P&L: `-11542.52`
- Win Rate: `29.03%`
- Profit Factor: `0.38`
- Max Drawdown: `14.67%`

## 对齐说明

- 原 EA 使用当前周期的最高/最低回归到区间中值；当前版本保留相同核心定义
- 原 EA 同时只允许一个仓位；当前版本保持相同行为
- 原 EA 按风险百分比计算手数；当前版本按止损距离与合约乘数做近似风险映射
