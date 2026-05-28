# 1330 Three EMA Trend

## 策略概述

该策略是对 MT5 EA `1330_MQL5向导_-_基于三条移动平均线的交易信号` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为三条 EMA 的多空排列。

## 核心逻辑

1. 计算快、中、慢三条 EMA
2. 当 `fast > medium > slow` 时做多
3. 当 `fast < medium < slow` 时做空
4. 排列被破坏或方向反转时平仓 / 反手

## 主要参数

- `fast_period`
- `medium_period`
- `slow_period`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 对齐说明

- 当前版本保留了三均线排列趋势策略的主框架
- 该策略属于典型趋势跟随模型
