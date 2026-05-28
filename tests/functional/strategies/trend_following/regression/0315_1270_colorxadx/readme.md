# 1270 ColorXADX

## 策略概述

该策略是对 MT5 EA `1270_Exp_ColorXADX` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为以平滑后的 `+DI/-DI` 交叉判断方向，再用平滑后的 `ADX` 强度过滤开仓。

## 核心逻辑

1. 计算 `+DI`、`-DI` 与 `ADX`
2. 对三条线再做一层平滑，模拟 `ColorXADX`
3. 当 `+DI/-DI` 关系翻转时产生方向信号
4. 仅在 `ADX > ExtraHighLevel` 时允许开仓
5. 平仓不受 `ADX` 过滤约束

## 主要参数

- `xma_method`
- `adx_period`
- `adx_phase`
- `extra_high_level`
- `signal_bar`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `14`
- Net P&L: `347.50`
- Win Rate: `57.14%`
- Profit Factor: `1.95`
- Max Drawdown: `0.21%`
