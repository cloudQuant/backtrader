# 0200 XFisher Org V1

## 策略概述

该策略是对 MT5 EA `0200_Exp_XFisher_org_v1` 的 backtrader 迁移版本。
原 EA 依赖外部 `XFisher_org_v1` 指标，在柱线收盘后根据主线与信号线的交叉方向进行开仓，并在指标状态反转时平仓或反手。
当前版本使用 `XAUUSD_M15.csv` 回测，并在 Python 中直接重建了一个近似的 `XFisher` 计算流程。

## 核心逻辑

1. 使用最近 `flength` 根 K 线的最高价/最低价对当前收盘价做归一化
2. 对归一化结果进行 Fisher Transform 变换
3. 再用 EMA 近似原版 `SmoothAlgorithms.mqh` 中的平滑主线
4. 使用上一根主线值作为信号线
5. 当主线上穿信号线时做多，下穿信号线时做空
6. 当持仓方向与当前指标状态相反时平仓；若同时满足反向交叉则直接反手
7. 保留原 EA 默认的固定止损 / 止盈点数参数，用 bar 内高低点触达近似处理离场

## 主要参数

- `flength`
- `ma_length`
- `lot`
- `stop_loss_points`
- `take_profit_points`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `839`
- Net P&L: `-389.50`
- Win Rate: `37.54%`
- Profit Factor: `0.99`
- Max Drawdown: `3.24%`

## 对齐说明

- 原 MT5 EA 使用 `iCustom(..., "XFisher_org_v1", ...)` 调外部指标，并依赖 `SmoothAlgorithms.mqh` 中的 `JJMA` 平滑实现
- 当前 backtrader 版本为了保证样例可独立运行，采用 Fisher Transform + EMA 平滑近似原始主线
- 因缺少原 `JJMA` 精确实现与 MT5 同步执行环境，回测结果应视为“逻辑等价迁移样例”，不是逐 tick 数值完全复刻
