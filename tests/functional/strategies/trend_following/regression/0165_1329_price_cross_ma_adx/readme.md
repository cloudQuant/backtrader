# 1329 Price Cross MA + ADX

## 策略概述

该策略是对 MT5 EA `1329_MQL5向导_-_基于价格交叉移动平均线并由ADX确认的交易信号` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为价格穿越移动平均线，并由 ADX 判断趋势强度。

## 核心逻辑

1. 计算移动平均线与 ADX
2. 当价格向上穿越 MA 且 `ADX >= min_adx` 时做多
3. 当价格向下穿越 MA 且 `ADX >= min_adx` 时做空
4. 出现反向穿越或趋势减弱时平仓 / 反手

## 主要参数

- `ma_period`
- `adx_period`
- `min_adx`
- `lot`
- `point`
- `price_digits`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 对齐说明

- 当前版本保留了“价格穿均线 + ADX 趋势确认”的主体框架
- 可视为 `1331 Price Cross MA` 的趋势强度过滤增强版
