# 1257 ATR Trailing Stop

## 策略概述

该策略是对 MT5 EA `1257_Exp_ATR_Trailing` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为 ATR 生成的动态跟踪止损带。

## 核心逻辑

1. 计算 ATR
2. 根据 `buy_factor / sell_factor` 生成多空跟踪带
3. 价格向上突破 trailing 带时做多
4. 价格向下跌破 trailing 带时做空
5. 跟踪带反转时离场 / 反手

## 主要参数

- `atr_period`
- `buy_factor`
- `sell_factor`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `290`
- Net P&L: `+5,009`
- Win Rate: `35.5%`
- Profit Factor: `1.12`
- Max Drawdown: `9.01%`
