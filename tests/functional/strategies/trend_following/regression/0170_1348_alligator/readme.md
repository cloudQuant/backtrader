# 1348 Alligator

## 策略概述

该策略是对 MT5 EA `1348_MQL5_向导_-_基于Alligator(鳄鱼)指标交叉线的交易信号` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑基于 Williams Alligator 的三条平滑均线：Jaw、Teeth、Lips。

## 核心逻辑

1. 计算 Alligator 的 `Jaw / Teeth / Lips`
2. 当快线与中慢线形成多头排列并向上发散时做多
3. 当快线与中慢线形成空头排列并向下发散时做空
4. 线组重新收敛或反向时平仓/反手

## 主要参数

- `jaw_period`
- `jaw_shift`
- `teeth_period`
- `teeth_shift`
- `lips_period`
- `lips_shift`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 对齐说明

- 当前版本保留了 Alligator 三线结构与交叉/发散信号框架
- 细节以本仓库 `strategy_*.py` 的可运行实现为准
