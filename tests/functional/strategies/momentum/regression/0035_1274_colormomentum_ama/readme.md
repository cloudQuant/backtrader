# 1274 ColorMomentum AMA

## 策略概述

该策略是对 MT5 EA `1274_Exp_ColorMomentum_AMA` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为先计算价格动量，再用自适应移动平均平滑，最后根据平滑动量方向翻转交易。

## 核心逻辑

1. 计算 `Momentum(price, ALength)`
2. 对动量序列做 `AMA` 平滑
3. EA 读取指标的 `IndMomentum` 缓冲区
4. 当平滑动量由下降转上升或由上升转下降时开仓或反手

## 主要参数

- `alength`
- `ama_period`
- `fast_ma_period`
- `slow_ma_period`
- `ipc`
- `g`
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
