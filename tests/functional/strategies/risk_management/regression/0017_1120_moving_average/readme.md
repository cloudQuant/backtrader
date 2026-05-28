# 1120 Moving Average

## 策略概述

该策略是对 MT5 标准示例 `Moving Average` EA 的 Backtrader 迁移版本。

原 EA 使用单根 `SMA` 与价格实体穿越作为开平仓依据，并使用基于可用保证金与连续亏损数的动态手数管理。

## 交易逻辑

- 当价格实体从上向下穿越均线时做空
- 当价格实体从下向上穿越均线时做多
- 若已有持仓，则在出现反向穿越时平仓
- 同时只允许一笔持仓

## 资金管理

- 初始手数按 `cash * maximum_risk / margin_per_lot` 计算
- 若最近存在连续亏损，则按 `decrease_factor` 缩减仓位
- 最终按 `volume_step / min_volume / max_volume` 约束手数

## 文件

- `strategy_moving_average.py` - 数据加载、均线信号与动态手数实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```

## 回测结果

- 数据：`XAUUSD_M15.csv`
- 区间：`2025-12-03 01:15:00` 到 `2026-03-10 09:00:00`
- 参数：`maximum_risk=0.02`、`decrease_factor=3.0`、`moving_period=12`、`moving_shift=6`
- 信号次数：`484`
- 已平仓交易：`484`
- TradeAnalyzer 统计交易：`484`
- 胜率：`25.00%`
- 期初资金：`100000.00`
- 期末现金：`4091.91`
- 期末权益：`4091.91`
- 净收益：`-95908.09`
- 最大回撤：`98.58%`
- SQN：`-3.31`

说明：样本结束时无未平仓头寸，`open_position_size=0.0`、`open_position_price=0.0`。当前 `SMA` 实体穿越配合动态手数在该数据段表现很差，连续亏损后的仓位收缩仍不足以阻止净值大幅回撤。
