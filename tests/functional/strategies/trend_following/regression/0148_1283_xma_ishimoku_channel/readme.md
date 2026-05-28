# 1283 XMA Ishimoku Channel

## 策略概述

该策略是对 MT5 EA `1283_Exp_XMA_Ishimoku_Channel` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为在最近区间高低点中值上做 `XMA` 平滑，构造上下百分比通道，并依据价格突破后回到通道内的行为触发交易。

## 核心逻辑

1. 统计最近 `up_period` 和 `dn_period` 的高低点
2. 取高低点中值作为 `Ishimoku` 中轴原始值
3. 对中轴做 `XMA` 平滑得到通道中心线
4. 按 `up_percent / dn_percent` 构造上下边界
5. 当价格越出边界后重新回到通道内时开仓或反手

## 主要参数

- `up_period`
- `dn_period`
- `up_mode`
- `dn_mode`
- `xma_method`
- `xlength`
- `xphase`
- `up_percent`
- `dn_percent`
- `signal_bar`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `23`
- Net P&L: `9,884.60`
- Win Rate: `52.17%`
- Profit Factor: `2.14`
- Max Drawdown: `4.50%`
