# 0194 Starter

## 策略概述

该样例是对 MT5 EA `0194_Starter` 的 Backtrader 迁移版。
根据源码检索结果，EA 的活跃逻辑围绕四个核心部件展开：

1. `CCI` 穿越阈值
2. `MA` 当前值与前一值的差额过滤
3. 按可用资金风险百分比计算仓位
4. 连续亏损后的减仓与追踪止损

## 迁移思路

1. 读取 `XAUUSD_M15.csv` 并保持 `M15` 原周期运行
2. 近似重建源码在新 bar 初始 tick 上读取的 `CCI(14)` 与 `MA(120)` 当前值，并将 `CCI previous` 对齐到上一根已收盘 bar
3. 当 `MA(current) - MA(previous) > 0.001` 且 `CCI` 从低于 `-100` 向上穿越时，触发买入
4. 当 `MA(current) - MA(previous) < -0.001` 且 `CCI` 从高于 `100` 向下穿越时，触发卖出
5. 仿照源码，以 `最大风险百分比 / 单手保证金` 计算基础仓位
6. 若近期历史中连续亏损次数大于 1，则按 `decrease_factor` 扣减仓位
7. 按源码默认值保留 `TrailingStop=5` 与 `TrailingStep=5`

## 主要参数

- `maximum_risk`
- `decrease_factor`
- `history_days`
- `stop_loss_points`
- `trailing_stop_points`
- `trailing_step_points`
- `cci_period`
- `cci_level`
- `ma_period`
- `ma_delta`
- `point`
- `lot_step`
- `lot_min`
- `lot_max`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 对齐说明

- 由于 `starter.mq5` 文件包含空字节编码，当前迁移是基于源码检索提取出的活跃逻辑重建，而不是逐行直读后的机械翻译
- 已确认源码存在 `TradeSizeOptimized`、`OpenBuy`、`OpenSell` 与 `Trailing` 函数，并使用 `CCI + MA delta + 风险仓位` 作为主逻辑
- 当前实现已修复 `build_signal_frame()` 中的 `pandas.NA` 比较报错；默认参数回测结果为 `49` 笔成交，净收益 `+11382.11`，胜率 `55.10%`，Profit Factor `1.10`，最大回撤 `31.01%`
