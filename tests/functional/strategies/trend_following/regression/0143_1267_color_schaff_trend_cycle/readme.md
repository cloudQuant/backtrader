# 1267 ColorSchaffTrendCycle

## 策略概述

该策略是对 MT5 EA `1267_Exp_ColorSchaffTrendCycle` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为计算 Schaff Trend Cycle 风格振荡器，并按颜色缓冲区进入超强多头/超强空头状态时交易。

## 核心逻辑

1. 计算快慢均线差值形成 `MACD` 风格序列
2. 对该序列做两层随机归一化与平滑，得到 `ColorSchaffTrendCycle`
3. 根据振荡器区间与斜率变化生成颜色状态
4. EA 读取颜色缓冲区，在极强多头/空头状态切换时开仓或反手

## 主要参数

- `xma_method`
- `fast_xma`
- `slow_xma`
- `xphase`
- `applied_price`
- `cycle`
- `high_level`
- `low_level`
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
