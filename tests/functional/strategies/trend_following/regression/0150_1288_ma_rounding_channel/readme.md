# 1288 MA Rounding Channel

## 策略概述

该策略是对 MT5 EA `1288_Exp_MA_Rounding_Channel` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为构造圆整化的移动平均基线，并在基线保持不变时叠加 ATR 通道；价格突破通道上轨或下轨时产生交易信号。

## 核心逻辑

1. 计算平滑价格均线 `base_ma`
2. 按 `ma_round` 阈值决定是否更新圆整后的基线 `base`
3. 当基线保持不变时，使用 `ATR * atr_factor` 构造上下通道
4. 收盘价突破上轨时做多，突破下轨时做空
5. 当当前柱没有通道时，回看最近一个有效通道用于离场判断

## 主要参数

- `xma_method`
- `xlength`
- `xphase`
- `ipc`
- `ma_round`
- `atr_period`
- `atr_factor`
- `chan_continuity`
- `signal_bar`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `223`
- Net P&L: `12,678.90`
- Win Rate: `42.15%`
- Profit Factor: `1.41`
- Max Drawdown: `3.30%`
