# 1292 Candles XSmoothed

## 策略概述

该策略是对 MT5 EA `1292_Exp_Candles_XSmoothed` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为跟踪 `Candles_Smoothed` 指标生成的平滑蜡烛高低点，并在实际收盘价突破对应阈值时入场或反手。

## 核心逻辑

1. 分别对 `open/high/low/close` 做独立平滑，构造平滑蜡烛
2. 读取平滑蜡烛的高点和低点作为突破参考
3. 当实际收盘价高于 `smooth_high + level * point` 时做多
4. 当实际收盘价低于 `smooth_low - level * point` 时做空
5. 反向突破出现时平原方向仓位并反手

## 主要参数

- `ma_method`
- `ma_length`
- `ma_phase`
- `level`
- `signal_bar`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `321`
- Net P&L: `+7,551.10`
- Win Rate: `35.51%`
- Profit Factor: `1.18`
- Max Drawdown: `6.08%`
