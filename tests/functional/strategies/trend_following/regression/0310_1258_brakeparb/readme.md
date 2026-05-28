# 1258 BrakeParb

## 策略概述

该策略是对 MT5 EA `1258_Exp_BrakeParb` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为根据 `BrakeParb` 抛物轨迹翻转后的大色点信号开平仓。

## 核心逻辑

1. 按时间和价格高低点生成抛物型轨迹
2. 当轨迹被价格反向击穿时切换多空状态
3. 状态翻转当柱生成大色点作为开仓与反手信号

## 主要参数

- `a`
- `b`
- `bigin_shift`
- `signal_bar`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `7`
- Net P&L: `-6734.20`
- Win Rate: `85.71%`
- Profit Factor: `N/A`
- Max Drawdown: `12.98%`
