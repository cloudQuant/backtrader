# 1328 Two EMA Crossover

## 策略概述

该策略是对 MT5 EA `1328_MQL5向导-基于两个指数平滑移动平均线交叉的交易信号` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为快慢 EMA 交叉。

## 核心逻辑

1. 计算快 EMA 与慢 EMA
2. 当快线向上穿越慢线时做多
3. 当快线向下穿越慢线时做空
4. 反向交叉时平仓或反手

## 主要参数

- `fast_period`
- `slow_period`
- `lot`
- `point`
- `price_digits`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 对齐说明

- 当前版本保留了标准双 EMA 交叉趋势跟随结构
- `1326` 则是在此基础上增加了时间过滤与 ATR 风控
