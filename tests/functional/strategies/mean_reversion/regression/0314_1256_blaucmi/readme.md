# 1256 BlauCMI

## 策略概述

该策略是对 MT5 EA `1256_Exp_BlauCMI` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为跟踪 `BlauCMI` 振荡器的方向翻转来开平仓。

## 核心逻辑

1. 计算价格动量与绝对动量
2. 对两者进行三级平滑，得到归一化的 `BlauCMI` 振荡值
3. 当振荡器由下转上时做多，由上转下时做空
4. 反向转折同时作为持仓平仓信号

## 主要参数

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
