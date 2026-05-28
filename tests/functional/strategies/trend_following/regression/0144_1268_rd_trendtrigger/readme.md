# 1268 RD-TrendTrigger

## 策略概述

该策略是对 MT5 EA `1268_Exp_RD-TrendTrigger` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为计算 `Trend Trigger Factor` 风格振荡器，并按默认 `twist` 模式在振荡器方向翻转时交易。

## 核心逻辑

1. 计算最近与更早窗口的高低点结构
2. 生成 `TTF` 振荡器
3. 对 `TTF` 做平滑，得到 `RD-TrendTrigger`
4. 默认 `twist` 模式下，在振荡器方向翻转时开仓或反手
5. 同时保留 `disposition` 模式，支持按 `HighLevel/LowLevel` 阈值回归交易

## 主要参数

- `mode`
- `regress`
- `t3_length`
- `t3_phase`
- `high_level`
- `low_level`
- `signal_bar`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `758`
- Net P&L: `-873.20`
- Win Rate: `48.55%`
- Profit Factor: `0.97`
- Max Drawdown: `4.18%`
