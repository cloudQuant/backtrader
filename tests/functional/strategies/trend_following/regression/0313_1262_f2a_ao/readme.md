# 1262 F2a_AO

## 策略概述

该策略是对 MT5 EA `1262_Exp_F2a_AO` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为使用 `F2a_AO` 箭头信号入场，并用更高时间帧蜡烛方向作为开仓过滤。

## 核心逻辑

1. `F2a_AO` 基于快慢 EMA 差值与滤波线生成买卖箭头
2. 箭头可触发平仓与反手信号
3. 只有当高一级趋势蜡烛方向同向时，才允许真正开仓
4. 若当前柱无直接反向平仓信号，仍回溯最近反向箭头补平仓

## 主要参数

- `inp_timeframe`
- `trend_bar`
- `ma_filtr`
- `ma_fast`
- `ma_slow`
- `signal_bar`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `0`
- Net P&L: `0.00`
- Win Rate: `0.00%`
- Profit Factor: `N/A`
- Max Drawdown: `0.00%`
