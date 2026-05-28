# 1108 Blau Ergodic

## 策略概述

该策略是对 MT5 EA `1108_Exp_BlauErgodic` 的 Backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为 Blau Ergodic 振荡器及其信号线关系。

## 核心逻辑

1. 计算价格动量及其绝对值
2. 对动量与绝对动量分别进行三层 EMA 平滑
3. 用平滑动量除以平滑绝对动量，得到主线 `main`
4. 再对主线做一次 EMA 平滑，得到信号线 `signal`
5. 默认采用 `twist` 模式：直方图拐头向上做多、拐头向下做空
6. 持仓后同时使用固定 `SL / TP`，若出现反向信号则平仓反手

## 主要参数

- `mode`
- `signal_bar`
- `xlength`
- `xlength1`
- `xlength2`
- `xlength3`
- `xlength4`
- `stop_loss_points`
- `take_profit_points`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 迁移说明

- MT5 原版依赖自定义指标 `BlauErgodic.ex5`
- 当前 Backtrader 版本按源码默认参数重写了指标主线、信号线与三种入场模式
- 平滑方式当前按源码默认值 `EMA` 实现
