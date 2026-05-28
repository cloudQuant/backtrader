# 1280 3XMA Ishimoku

## 策略概述

该策略是对 MT5 EA `1280_Exp_3XMA_Ishimoku` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为构造三条不同参数的 `XMA_Ishimoku` 线，其中快速线相对另外两条形成的云层位置决定交易信号。

## 核心逻辑

1. 分别计算三条 `XMA_Ishimoku` 线
2. 使用中速线和慢速线形成上下云边界
3. 快速线位于云层上方视为多头外扩，位于云层下方视为空头外扩
4. 当快速线从云外重新回到云边界内时开仓或反手

## 主要参数

- `up_period1/dn_period1`
- `up_period2/dn_period2`
- `up_period3/dn_period3`
- `xma1_method`
- `xma2_method`
- `xma3_method`
- `xlength1`
- `xlength2`
- `xlength3`
- `xphase`
- `signal_bar`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `106`
- Net P&L: `8,087.80`
- Win Rate: `44.34%`
- Profit Factor: `1.62`
- Max Drawdown: `4.39%`
