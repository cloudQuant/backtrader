# 0777 CandelsHighOpen

## 策略概述

该策略是对 MT5 EA `0777_CandelsHighOpen` 的 Backtrader 迁移版本。
当前版本依据原指标文档保留了核心结构：

- 依据最近四根已完成 K 线的 `high` 与 `open` 单调关系生成方向信号
- 支持 `reverse_signals`
- 使用固定 `StopLoss / TakeProfit`
- 使用 `Parabolic SAR` 进行 trailing stop 管理

## 核心逻辑

1. 忽略当前未完成柱，检查最近四根已完成 K 线
2. 若 `high` 与 `open` 均连续抬高，则生成做多信号
3. 若 `high` 与 `open` 均连续走低，则生成做空信号
4. 反向参数开启时，对信号方向取反
5. 入场后使用固定 `SL/TP` 与 `PSAR` 跟踪止损管理仓位

## 主要参数

- `reverse_signals`
- `stop_level`
- `take_level`
- `trailing_step`
- `trailing_maximum`
- `size`

## 对齐说明

- 原 EA 依赖 `SignalCandelsHighOpen` 信号模块与 `Candels High Open` 指标；当前版本根据原指标文档中明确公开的买卖条件重建核心信号
- 原始 MQL5 向导版本支持挂单参数，但默认 `Signal_PriceLevel=0`，当前回测按市价执行近似默认行为
- 原版使用 `MoneyFixedRisk`，当前版本使用固定下单量 `0.1` 手近似执行

## 运行方式

```bash
python run.py
```

## 当前回测结果

已完成一次可运行验证，结果如下：

- 数据区间：`2025-12-03 01:15:00` ~ `2026-03-10 09:00:00`
- K线数量：`6129`
- 最终权益：`101454.50`
- 净收益：`1454.50`
- 总收益率：`1.45%`
- 总交易数：`504`
- 胜率：`52.58%`
- 盈利因子：`1.09`
- 最大回撤：`1.91%`
- Sharpe：`4.32`
- SQN：`0.55`

在当前 `XAUUSD_M15` 数据窗口下，基于最近已完成 K 线 `high/open` 单调关系的信号能够稳定触发并完成回测，验证了该策略在 Backtrader 中的可运行性。
