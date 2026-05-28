# 1282 XMA Range Bands

## 策略概述

该策略是对 MT5 EA `1282_Exp_XMA_Range_Bands` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为对价格做 `XMA` 平滑，并以平滑后的 K 线实体/振幅范围构造带状通道；价格越出通道后重新回到边界内时产生交易信号。

## 核心逻辑

1. 对输入价格做主平滑，得到通道中线
2. 计算每根 K 线的 `high-low` 幅度
3. 对幅度做二次平滑，形成带宽
4. 上下轨分别为 `mid ± deviation * smoothed_range`
5. 当价格越出边界后回到边界内时开仓或反手

## 主要参数

- `ma_method1`
- `length1`
- `phase1`
- `ma_method2`
- `length2`
- `phase2`
- `deviation`
- `ipc`
- `signal_bar`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `48`
- Net P&L: `15,919.10`
- Win Rate: `47.92%`
- Profit Factor: `2.99`
- Max Drawdown: `5.75%`
