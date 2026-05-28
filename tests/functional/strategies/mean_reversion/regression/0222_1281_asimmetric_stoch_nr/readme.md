# 1281 AsimmetricStochNR

## 策略概述

该策略是对 MT5 EA `1281_Exp_AsimmetricStochNR` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为构造带噪声抑制和超买/超卖自适应长短周期切换的随机指标，并在主随机线与信号线交叉时交易。

## 核心逻辑

1. 计算非对称随机指标 `stoch`
2. 在超买区使用一组长短窗口，在超卖区切换另一组窗口
3. 用平滑方法生成 `signal`
4. 当 `stoch` 与 `signal` 交叉时开仓或反手

## 主要参数

- `kperiod_short`
- `kperiod_long`
- `dmethod`
- `dperiod`
- `dphase`
- `slowing`
- `price_field`
- `sens`
- `overbought`
- `oversold`
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
