# 1137 JPAlonso-modoki

## 策略概述

该策略是对 MT5 EA `JPAlonso-modoki` 的 Backtrader 迁移版本。

原 EA 基于 `Envelopes(200, deviation=0.35)` 的自定义投票逻辑开仓，并且仅在**无持仓**且达到指定起始时间后才允许入场；已有持仓主要由固定 `SL/TP` 管理。

## 交易逻辑

- 计算 `Envelopes(200, 0.35)` 上下轨与中线
- 多头投票：`close <= lower` 或 `mid < close < upper`
- 空头投票：`close >= upper` 或 `lower < close < mid`
- 当某一侧投票达到开仓阈值且另一侧未达到阈值时开仓
- 若已有仓位，则不再重复开仓
- 仅在 `2012-10-08 10:55:00` 之后允许执行交易逻辑

## 风控逻辑

- 固定 `SL/TP`
- 单次仅保留一笔仓位
- 无额外 trailing

## 文件

- `strategy_jpalonso_modoki.py` - 数据加载、Envelopes 投票逻辑与交易实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```

## 回测结果

- 数据：`XAUUSD_M15.csv`
- 区间：`2025-12-03 01:15:00` 到 `2026-03-10 09:00:00`
- 参数：`signal_threshold_open=10`、`signal_stop_level=77.0`、`signal_take_level=127.0`、`envelopes_period=200`、`envelopes_deviation=0.35`、`lots=5.0`
- 信号次数：`5218`
- 已平仓交易：`706`
- TradeAnalyzer 统计交易：`706`
- 胜率：`47.59%`
- 期初资金：`100000.00`
- 期末现金：`590.00`
- 期末权益：`590.00`
- 净收益：`-99410.00`
- 最大回撤：`102.20%`
- SQN：`-1.33`

说明：样本结束时无未平仓头寸，`open_position_size=0.0`、`open_position_price=0.0`。由于固定 `lots=5.0` 较大，后段出现大量 `Margin` 拒单，导致信号次数显著高于实际成交次数。
