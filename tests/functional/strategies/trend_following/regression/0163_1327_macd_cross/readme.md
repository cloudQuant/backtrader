# 1327 MACD Crossover

## 策略概述

该策略是对 MT5 EA `1327_MQL5向导_-_基于MACD指标主线和信号线交叉的交易信号` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为 MACD 主线与信号线交叉。

## 核心逻辑

1. 计算 MACD 主线与信号线
2. 主线上穿信号线时做多
3. 主线下穿信号线时做空
4. 出现反向交叉时平仓或反手

## 主要参数

- `fast_period`
- `slow_period`
- `signal_period`
- `lot`
- `point`
- `price_digits`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 对齐说明

- 当前版本保留了标准 MACD 交叉信号框架
- 属于 MQL5 Wizard 中较基础的振荡器交叉策略
