# 1259 MUV_NorDIFF_Cloud

## 策略概述

该策略是对 MT5 EA `1259_Exp_MUV_NorDIFF_Cloud` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为读取 `MUV_NorDIFF_Cloud` 的买卖彩色点信号并进行开平仓。

## 核心逻辑

1. 计算 SMA/EMA 型动量差值
2. 将差值归一化到 `[-100, 100]`
3. 当任一归一化结果到达 `+100` 时给出买点
4. 当任一归一化结果到达 `-100` 时给出卖点
5. 若当前柱无反向平仓信号，则回溯最近反向点位补平仓

## 主要参数

- `ma_period`
- `momentum`
- `kperiod`
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
