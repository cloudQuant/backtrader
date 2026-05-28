# 0196 High frequency volatility trader

## 策略概述

该样例是对 MT5 EA `0196_High_frequency_volatility_trader_(_EURUSD_H1_ONLY)` 的 Backtrader 迁移版。
源码中真正启用的是一个买入路径：使用两条简单均线创建句柄，但实际只在活跃逻辑中使用快均线；卖出路径整段被注释掉。

## 迁移思路

1. 从 `XAUUSD_M15.csv` 读取基础行情并重采样到 `H1`
2. 按源码的活跃买入逻辑近似重建 `MA(5)` 与 `MA(25)`
3. 当 `MA(5) - 当前开盘价 < -0.0015` 且 `MA(5) > MA(5)[-2]` 时，触发买入候选
4. 买单止损沿用源码默认 `StopLoss=15`
5. 买单止盈沿用源码活跃路径里 `TP = MA_Val1[0]` 的写法
6. 若该 `TP` 不高于当前入场价，则视作 MT5 中的无效买单参数并跳过下单

## 主要参数

- `lot`
- `stop_loss_points`
- `take_profit_points`
- `buy_threshold`
- `fast_ma_period`
- `slow_ma_period`
- `point`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `0`
- Net P&L: `0.00`
- Win Rate: `0.00%`
- Profit Factor: `None`
- Max Drawdown: `0.00%`

## 对齐说明

- 原文件名写明 `EURUSD H1 ONLY`，当前样例仍按 `H1` 逻辑运行，但验证数据沿用项目统一的 `XAUUSD_M15.csv`
- 源码中的卖出分支被完整注释，因此当前迁移版只实现活跃的买入分支
- 原 EA 的 `TakeProfit` 输入参数在活跃买入路径中并未真正用于设置 TP；实际 TP 来自 `MA_Val1[0]`
- 原 EA 的保证金检查变量 `margin` 未被赋值，存在实现缺陷；当前版本仅保留核心信号与风控路径
