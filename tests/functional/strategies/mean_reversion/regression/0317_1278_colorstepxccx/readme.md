# 1278 ColorStepXCCX

## 策略概述

该策略是对 MT5 EA `1278_Exp_ColorStepXCCX` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为将价格相对平滑中轴的偏离做二次平滑后，构造快慢两条阶梯线；当两条线相对强弱翻转时触发交易。

## 核心逻辑

1. 对价格做主平滑得到 `xma`
2. 计算偏离 `upccx=price-xma` 与绝对偏离 `dnccx=abs(price-xma)`
3. 对二者做二次平滑生成 `xccx`
4. 基于 `StepSizeFast/StepSizeSlow` 生成快慢两条 step 线
5. 当快线与慢线翻转时开仓或反手

## 主要参数

- `dsmooth_method`
- `dperiod`
- `dphase`
- `msmooth_method`
- `mperiod`
- `mphase`
- `ipc`
- `step_size_fast`
- `step_size_slow`
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
