# 1300 Bollinger Band Squeeze

## 策略概述

该策略是对 MT5 EA `1300_Exp_BBSqueeze` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为 Bollinger Band 与 Keltner Channel 的波动压缩识别，并结合动量方向入场。

## 核心逻辑

1. 计算 Bollinger Bands 与 Keltner Channel
2. 当布林带收缩到 Keltner 通道内时，视为 squeeze 压缩阶段
3. 使用动量值判断突破方向
4. 压缩结束且动量向上时做多，向下时做空
5. 信号反转时平仓/反手

## 主要参数

- `bb_period`
- `bb_dev`
- `kc_period`
- `kc_mult`
- `mom_period`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `309`
- Net P&L: `+6,196`
- Win Rate: `40.8%`
- Profit Factor: `1.27`
- Max Drawdown: `5.19%`
