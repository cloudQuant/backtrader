# 1287 LinearRegSlopeV2

## 策略概述

该策略是对 MT5 EA `1287_Exp_LinearRegSlopeV2` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为对平滑价格序列做线性回归斜率预测，并与触发线比较；当两条缓冲区的相对强弱翻转时开仓或反手。

## 核心逻辑

1. 对输入价格先做平滑处理
2. 在滚动窗口内计算线性回归斜率 `Slope`
3. 计算预测值 `reg_slope = intercept + slope * trig_shift`
4. 根据 `trigger_shift` 构造 `trigger = 2 * reg_slope - reg_slope[-shift]`
5. 当 `trigger/reg_slope` 的相对大小翻转时开平仓

## 主要参数

- `sl_method`
- `sl_length`
- `sl_phase`
- `ipc`
- `trigger_shift`
- `signal_bar`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `393`
- Net P&L: `-4,247.90`
- Win Rate: `49.62%`
- Profit Factor: `0.72`
- Max Drawdown: `4.77%`
