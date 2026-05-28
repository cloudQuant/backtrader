# 0193 AO 执行者

## 策略概述

该样例是对 MT5 EA `0193_AO_执行者` 的 Backtrader 迁移版。
根据源码说明与关键字检索结果，EA 的主逻辑是 Awesome Oscillator (`AO`) 的拐点反转信号：

- 买入：`AO[0] > AO[1]` 且 `AO[1] < AO[2]`，并且 `AO[0]` 仍低于负的最小偏移
- 卖出：`AO[0] < AO[1]` 且 `AO[1] > AO[2]`，并且 `AO[0]` 仍高于正的最小偏移
- 持有多单时，当前一个已收盘 AO 变为正值则离场
- 持有空单时，当前一个已收盘 AO 变为负值则离场

## 迁移思路

1. 读取 `XAUUSD_M15.csv` 并保持 `M15` 原周期运行
2. 近似重建源码在新 bar 初始 tick 上读取的 `AO[0]`，同时将 `AO[1]` / `AO[2]` 对齐到上一、上二根已收盘 bar
3. 按源码默认参数保留 `StopLoss=50`、`TakeProfit=50`、`TrailingStop=5`、`TrailingStep=5`
4. 保留固定手数 / 风险百分比二选一的资金管理入口，其中 `risk=1.0` 表示 `1%`
5. 使用单仓位近似处理源码在净持/对冲账户下都可运行的逻辑

## 主要参数

- `stop_loss_points`
- `take_profit_points`
- `trailing_stop_points`
- `trailing_step_points`
- `lot_or_risk`
- `volume_or_risk`
- `minimum_indent`
- `point`
- `lot_step`
- `lot_min`
- `lot_max`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 对齐说明

- 当前迁移基于 `readme` 与源码关键字检索提取的活跃逻辑重建，未逐行做完整反编译式映射
- 原 EA 支持净持与对冲账户；当前 Backtrader 样例使用单仓位近似表达核心信号与风控路径
- 当前回测结果：`533` 笔成交，净收益 `+10754.00`，胜率 `49.34%`，Profit Factor `1.08`，最大回撤 `15.36%`
