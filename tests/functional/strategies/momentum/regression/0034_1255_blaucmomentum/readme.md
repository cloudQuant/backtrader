# 1255 BlauCMomentum

## 策略概述

该策略是对 MT5 EA `1255_Exp_BlauCMomentum` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为跟踪 `BlauCMomentum` 的零轴突破或方向翻转信号。

## 核心逻辑

1. 计算平滑后的动量值 `BlauCMomentum`
2. `breakdown` 模式按零轴突破触发
3. `twist` 模式按动量方向翻转触发
4. 默认 `twist` 模式，反向信号同时作为平仓条件

## 主要参数

- `mode`
- `xma_method`
- `xlength`
- `xlength1`
- `xlength2`
- `xlength3`
- `xphase`
- `ipc1`
- `ipc2`
- `signal_bar`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `0`
- Net P&L: `0.00`
- Win Rate: `0.00%`
- Profit Factor: `N/A`
- Max Drawdown: `0.00%`
