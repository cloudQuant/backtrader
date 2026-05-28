# 1213 MBKAsctrend3

## 策略概述

该策略是对 MT5 EA `1213_Exp_MBKAsctrend3` 的 Backtrader 迁移版本。
原 EA 使用三组 Williams %R 的加权组合与长周期过滤，在趋势翻转时绘制买卖箭头。

## 核心逻辑

1. 将 `M15` 数据重采样到指标周期 `H4`
2. 计算三组 `WPR`
3. 按权重组合出 `wprvalue`
4. 结合长周期 `WPR3` 判断多空趋势翻转
5. 趋势翻转时绘制箭头，并保留原 EA 的历史箭头回扫平仓逻辑

## 主要参数

- `indicator_minutes`
- `wpr1_len`
- `wpr2_len`
- `wpr3_len`
- `swing`
- `aver_swing`
- `w1`
- `w2`
- `w3`
- `signal_bar`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 说明

该指标原公式中的阈值常量来自 Asctrend 家族实现约定。
本迁移版按源码结构重建 `WPR` 组合、趋势翻转与箭头位置。
