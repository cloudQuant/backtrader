# 1277 ColorJVariation

## 策略概述

该策略是对 MT5 EA `1277_Exp_ColorJVariation` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为对价格做三层残差移动平均分解，再经一层平滑得到 `JVariation` 振荡器，并根据其颜色翻转交易。

## 核心逻辑

1. 对价格做第一层移动平均 `ma1`
2. 对残差 `price-ma1` 做第二层移动平均 `ma2`
3. 对更深残差 `price-ma1-ma2` 做第三层移动平均 `ma3`
4. 对 `ma3` 再做平滑得到 `JVariation`
5. 当指标由下降转上升或由上升转下降时开仓或反手

## 主要参数

- `period_`
- `ma_method_`
- `jlength_`
- `jphase_`
- `signal_bar`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `690`
- Net P&L: `-193.80`
- Win Rate: `46.38%`
- Profit Factor: `0.99`
- Max Drawdown: `2.74%`
