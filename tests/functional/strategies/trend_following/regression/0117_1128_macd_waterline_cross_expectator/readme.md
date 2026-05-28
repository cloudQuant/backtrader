# 1128 MACDWaterlineCrossExpectator

## 策略概述

该策略是对 MT5 `MACDWaterlineCrossExpectator` 的 Backtrader 迁移版本。

原 EA 在 `MACD` 信号线穿越零轴时开仓，并用固定止损和按风险收益比推导的止盈进行风控。

## 交易逻辑

- 当 `MACD signal` 从负值上穿 0 且内部状态允许时做多
- 当 `MACD signal` 从正值下穿 0 且内部状态允许时做空
- 内部 `flag` 在多空之间切换，避免同方向连续重复开仓
- 若出现反向信号，则按单仓位模型进行反手

## 风控逻辑

- 固定 `stop_loss`
- `take_profit = stop_loss * risk_benefit_ratio`
- 固定手数 `size`

## 文件

- `strategy_macd_waterline_cross_expectator.py` - 数据加载、MACD 信号与交易实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```

## 回测结果

- 数据：`XAUUSD_M15.csv`
- 区间：`2025-12-03 01:15:00` 到 `2026-03-10 09:00:00`
- 参数：`fast_ema_period=12`、`slow_ema_period=26`、`signal_period=9`、`stop_loss=300`、`size=0.1`、`risk_benefit_ratio=3`
- 信号次数：`141`
- 已平仓交易：`141`
- TradeAnalyzer 统计交易：`141`
- 胜率：`38.30%`
- 期初资金：`100000.00`
- 期末现金：`99713.50`
- 期末权益：`99713.50`
- 净收益：`-286.50`
- 最大回撤：`1.88%`
- SQN：`-0.17`

说明：样本结束时无未平仓头寸，`open_position_size=0.0`、`open_position_price=0.0`。
