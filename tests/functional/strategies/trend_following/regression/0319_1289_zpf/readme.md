# 1289 ZPF

## 策略概述

该策略是对 MT5 EA `1289_Exp_ZPF` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为对平滑价格快慢线差乘以平滑成交量构造 `ZPF` 云层，并在云层颜色翻转时入场或反手。

## 核心逻辑

1. 选择输入价格序列并计算快线平滑值 `x1ma`
2. 对同一价格序列计算慢线平滑值 `x2ma`
3. 对成交量做同周期平滑得到 `xvol`
4. 构造 `zpf = xvol * (x1ma - x2ma) / 2`
5. 当 `zpf` 正负翻转时执行开仓、平仓或反手

## 主要参数

- `xma_method`
- `xlength`
- `xphase`
- `ipc`
- `volume_type`
- `signal_bar`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `293`
- Net P&L: `-622.00`
- Win Rate: `51.54%`
- Profit Factor: `0.94`
- Max Drawdown: `2.27%`
