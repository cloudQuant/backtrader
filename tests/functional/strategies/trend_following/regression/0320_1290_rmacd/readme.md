# 1290 RMACD

## 策略概述

该策略是对 MT5 EA `1290_Exp_RMACD` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为对 `RVI` 与 `TRVI` 之差形成的 `RMACD` 柱状线及其平滑信号线进行判定，并在默认 `MACDdisposition` 模式下根据二者交叉信号入场或反手。

## 核心逻辑

1. 计算快速 `RVI`
2. 计算慢速 `TRVI` 及其信号线
3. 构造 `RMACD = RVI - TRVI_signal`
4. 对 `RMACD` 再做信号线平滑
5. 根据模式选择零轴突破、柱状线拐点、信号线拐点或 `RMACD/Signal` 交叉产生交易信号

## 主要参数

- `mode`
- `fast_rvi`
- `slow_trvi`
- `volume_type`
- `signal_method`
- `signal_xma`
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
