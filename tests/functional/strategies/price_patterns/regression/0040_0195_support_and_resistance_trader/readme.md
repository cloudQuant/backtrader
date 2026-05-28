# 0195 Support and Resistance Trader

## 策略概述

该样例是对 MT5 EA `0195_Support_and_Resistance_Trader` 的 Backtrader 迁移版。
EA 会扫描最近一段已收盘 K 线的收盘价，将其按三位小数离散化后统计重复次数，把重复次数超过阈值的价格视作支撑/阻力候选水平；随后再用两条 SMA 的相对位置做方向过滤。

## 迁移思路

1. 读取 `XAUUSD_M15.csv` 并保持 `M15` 原周期运行
2. 近似重建源码在新 bar 初始 tick 上读取的 `MA(25)` 与 `MA(30)` 当前值
3. 扫描最近 `period` 个已收盘 bar 的 `close`，按 `3` 位小数聚类并统计出现次数
4. 当某个价格水平出现次数超过 `resistance` 且与当前价格距离小于 `0.0005` 时，将其视作临近支撑/阻力
5. 若 `MA(25) > MA(30)` 且当前价略高于临近支撑，则买入
6. 若 `MA(25) < MA(30)` 且当前价略低于临近阻力，则卖出
7. 止损和止盈分别沿用源码默认 `30` / `100` 点

## 主要参数

- `lot`
- `stop_loss_points`
- `take_profit_points`
- `ma_period1`
- `ma_period2`
- `resistance`
- `cluster_period`
- `xau_cluster_period`
- `price_decimals`
- `near_threshold`
- `point`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 对齐说明

- 原 EA 在 `XAUUSD` 上会把聚类扫描窗口从 `500` 根缩短到 `100` 根，当前迁移版保留了该特判
- 原码注释宣称使用更复杂的趋势/波动率条件，但活跃逻辑实际只使用了 `MA(25)` 与 `MA(30)` 的相对大小
- 原 EA 的 `margin` 变量在下单前未被赋值，存在实现缺陷；当前版本只保留核心信号与风控路径
- 当前回测结果：默认参数下 `0` 笔成交，期末权益 `100000.00`，最大回撤 `0.00%`
