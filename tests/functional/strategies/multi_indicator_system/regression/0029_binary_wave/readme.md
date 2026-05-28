# 1299 BinaryWave

## 策略概述

该策略是对 MT5 EA `1299_Exp_BinaryWave` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为多指标方向投票后形成积分波形，并在零轴突破时入场或反手。

## 核心逻辑

1. 分别计算价格相对均线、MACD 斜率、OsMA、CCI、Momentum、RSI、DI 方向
2. 将各指标按权重映射为 `+1 / -1 / 0` 的方向分数
3. 对总分进行平滑，形成 `BinaryWave`
4. 当波形突破零轴时做多或做空
5. 反向信号出现时平仓并反手

## 主要参数

- `mode`
- `signal_bar`
- `weight_ma`
- `weight_macd`
- `weight_osma`
- `weight_cci`
- `weight_mom`
- `weight_rsi`
- `weight_adx`
- `ma_period`
- `fast_macd`
- `slow_macd`
- `signal_macd`
- `smooth_period`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `502`
- Net P&L: `+13,048`
- Win Rate: `41.24%`
- Profit Factor: `1.35`
- Max Drawdown: `5.10%`
