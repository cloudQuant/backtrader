# 1220 ColorTrend_CF

## 策略概述

该策略是对 MT5 EA `1220_Exp_ColorTrend_CF` 的 Backtrader 迁移版本。
原 EA 使用 `ColorTrend_CF` 指标，在趋势带颜色切换时执行反手交易。

## 核心逻辑

1. 将 `M15` 数据重采样到指标周期 `H4`
2. 对重采样后的收盘价序列计算相邻价差
3. 维护正向与反向延续因子窗口
4. 重建 `UpperBuffer / LowerBuffer`
5. 当 `UpperBuffer` 与 `LowerBuffer` 发生交叉时触发买卖

## 主要参数

- `indicator_minutes`
- `cf_period`
- `signal_bar`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 说明

原 EA 只读取指标前两个 buffer 并检测其交叉。
本迁移版按原始 Continuation Factor 递推逻辑重建两条曲线后执行等价交易规则。
