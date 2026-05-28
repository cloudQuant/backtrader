# 1295 Color BB Candles

## 策略概述

该策略是对 MT5 EA `1295_Exp_ColorBBCandles` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为根据价格突破多层布林带区间所对应的颜色状态进行入场、反手与离场。

## 核心逻辑

1. 计算价格序列的中轨均线与标准差
2. 生成 5 层上轨与 5 层下轨阈值
3. 将价格所处位置映射为 `0..10` 的颜色状态，其中 `5` 为中性
4. 状态从中性/下方切入上方区间时做多
5. 状态从中性/上方切入下方区间时做空，回到中性时平仓

## 主要参数

- `period`
- `deviation1`
- `deviation2`
- `deviation3`
- `deviation4`
- `deviation5`
- `ma_method`
- `applied_price`
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
