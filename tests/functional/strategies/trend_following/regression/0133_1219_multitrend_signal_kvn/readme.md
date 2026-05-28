# 1219 MultiTrend_Signal_KVN

## 策略概述

该策略是对 MT5 EA `1219_Exp_MultiTrend_Signal_KVN` 的 Backtrader 迁移版本。
原 EA 使用 `MultiTrend_Signal_KVN` 指标在图表上绘制买卖箭头，并依据最近一次箭头方向决定是否反手开仓。

## 核心逻辑

1. 将 `M15` 数据重采样到指标周期 `H4`
2. 计算 `ADX`
3. 用 `SSP = ceil(Kperiod / ADX)` 得到自适应窗口
4. 以 `smin / smax` 阈值生成买卖箭头 buffer
5. 在新箭头出现时，向后搜索最近一次箭头方向，只在方向发生切换时开仓

## 主要参数

- `indicator_minutes`
- `k`
- `kstop`
- `kperiod`
- `per_adx`
- `signal_bar`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 说明

原 EA 读取两个箭头 buffer，并通过向后扫描历史箭头确定 `LastTrend`。
本迁移版保留了该判定结构，而不是简单地对同类箭头重复开仓。
