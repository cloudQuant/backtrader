# 1326 Two EMA Crossover + Intraday Time Filter

## 策略概述

该策略是对 MT5 EA `1326_MQL5向导_-_基于两条移动平均线带日内时间过滤的交易信号` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为双 EMA 交叉，叠加日内交易时段限制与 ATR 止损止盈。

## 核心逻辑

1. 计算快 EMA 与慢 EMA
2. 仅在指定交易时段内允许开仓
3. 快线向上穿越慢线时做多
4. 快线向下穿越慢线时做空
5. 使用 ATR 倍数设置止损与止盈

## 主要参数

- `fast_period`
- `slow_period`
- `atr_period`
- `sl_atr_mult`
- `tp_atr_mult`
- `trade_start_hour`
- `trade_end_hour`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

当前参数下的回测结果：

- Trades: `53`
- Net P&L: `+82`
- Win Rate: `41.5%`
- Profit Factor: `1.01`
- Max Drawdown: `2.97%`

## 对齐说明

- 当前版本保留了双 EMA 交叉 + 时间过滤 + ATR 风控的主体结构
- 可视为 `1328` 的时段与波动率风控增强版本
