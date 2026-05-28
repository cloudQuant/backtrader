# 1186 20/200 Pips EA

## 策略概述

该策略是对 MT5 EA `1186_20_200_点_-_简单可盈利_EA` 的 Backtrader 迁移版本。
原始 EA 为单品种、固定时刻触发的简单价差策略：在指定交易小时读取 `H1` 周期两根历史 K 线的开盘价，若二者价差超过阈值，则按方向开仓，并设置固定止盈止损。

## 核心逻辑

1. 将基础 `M15` 数据重采样为 `H1`
2. 在 `trade_time_hour` 对应的整点，仅处理一次信号
3. 若 `Open[t1] > Open[t2] + delta * point`，则开空
4. 若 `Open[t1] + delta * point < Open[t2]`，则开多
5. 入场后使用固定止盈 `take_profit_points` 与固定止损 `stop_loss_points`
6. 每个交易小时只触发一次，持仓期间仅由止盈/止损退出

## 主要参数

- `take_profit_points`
- `stop_loss_points`
- `trade_time_hour`
- `t1`
- `t2`
- `delta_points`
- `lot`
- `point`
- `price_digits`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 对齐说明

- 原 EA 使用 `CopyOpen(_Symbol, PERIOD_H1, ...)`，迁移版通过对统一 `M15` 数据重采样得到 `H1` 信号数据
- 原 EA 以 `TradeTime` 小时作为每日允许开仓时段，并用 `cantrade` 限制同一天只开一次仓；迁移版以 `H1` 信号时间戳去重，保持每个交易整点只评估一次
- 原 EA 未显式实现反向信号平仓；迁移版也保持为持仓后仅依赖固定止盈/止损退出
- 当前统一验证环境为 `XAUUSD_M15`，而原文档主要说明该策略最初面向 `EURUSD H1`

## 当前回测结果

- 待运行 `python run.py` 后补充
