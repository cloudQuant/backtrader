# 1162 TrendCapture

## 策略概述

该策略是对 MT5 EA `1162_TrendCapture` 的 Backtrader 迁移版本。

原 EA 结合 `Parabolic SAR` 与 `ADX` 过滤判断入场方向，同时根据上一笔已平仓交易的盈亏结果限制下一次允许的交易方向。

## 交易逻辑

- 当 `close > SAR` 且 `ADX < ADXLevel` 时产生多头候选信号
- 当 `close < SAR` 且 `ADX < ADXLevel` 时产生空头候选信号
- 若上一笔交易盈利，则仅允许沿上一笔方向继续开仓
- 若上一笔交易亏损，则仅允许在上一笔相反方向开仓
- 开仓后设置固定 `StopLoss` 与 `TakeProfit`

## 风控逻辑

- `lots = 0` 时按 `cash * maximum_risk / 1000` 估算手数
- 若启用 `BreakEven`，当浮盈达到阈值后将止损推至开仓价

## 文件

- `strategy_trendcapture.py` - 数据加载、SAR/ADX 逻辑与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```

## 回测结果

- 数据：`XAUUSD_M15.csv`
- 区间：`2025-12-03 01:15:00` 到 `2026-03-10 09:00:00`
- 参数：`lots=0.1`、`stop_loss=1800`、`take_profit=500`、`sar_step=0.02`、`sar_max=0.2`、`adx_period=14`、`adx_level=20`、`shift=1`、`break_even=50`
- 信号次数：`1747`
- 已平仓交易：`375`
- TradeAnalyzer 统计交易：`375`
- 胜率：`65.87%`
- 期初资金：`100000.00`
- 期末现金：`98790.40`
- 期末权益：`98790.40`
- 净收益：`-1209.60`
- 最大回撤：`2.73%`
- SQN：`-0.52`

说明：样本结束时无未平仓头寸，`open_position_size=0.0`、`open_position_price=0.0`。
