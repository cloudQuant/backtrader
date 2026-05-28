# 1286 UltraWPR

## 策略概述

该策略是对 MT5 EA `1286_Exp_UltraWPR` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为在同一 `WPR` 序列上构造多组不同平滑长度，比较它们相邻柱的上升/下降个数，形成 `Bulls/Bears` 两条强弱线，并在颜色翻转时交易。

## 核心逻辑

1. 计算基础 `Williams %R`
2. 用递增平滑长度生成多组 `WPR` 平滑值
3. 统计这些平滑值相对上一柱是上升还是下降
4. 对上升计数和下降计数分别平滑，得到 `bulls` 与 `bears`
5. 当 `bulls/bears` 相对大小翻转时开仓或反手

## 主要参数

- `wpr_period`
- `w_method`
- `start_length`
- `w_phase`
- `xstep`
- `xsteps_total`
- `smooth_method`
- `smooth_length`
- `smooth_phase`
- `signal_bar`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `2`
- Net P&L: `-45.10`
- Win Rate: `0.00%`
- Profit Factor: `0.00`
- Max Drawdown: `0.05%`
