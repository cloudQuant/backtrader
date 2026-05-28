# 1159 up3x1_Krohabor_D

## 策略概述

该策略是对 MT5 EA `1159_up3x1_Krohabor_D` 的 Backtrader 迁移版本。

原 EA 是 `up3x1` 的更严格版本：除了快速均线与中间均线的交叉外，还要求最近两根相关均线值在整个交叉前后都位于慢速均线同一侧。

## 交易逻辑

- 当快速均线上穿中间均线，且最近两根快速/中间均线都位于慢速均线上方时做多
- 当快速均线下穿中间均线，且最近两根快速/中间均线都位于慢速均线下方时做空
- 开仓后按固定点数设置 `StopLoss` 和 `TakeProfit`
- 若启用 `TrailingStop`，则按固定点距推进止损

## 资金管理

- `lots > 0` 时使用固定手数
- `lots = 0` 时按 `cash * maximum_risk / 1000` 估算手数
- 若启用 `decrease_factor`，则在连续亏损后递减新开仓手数

## 文件

- `strategy_up3x1_krohabor_d.py` - 数据加载、三均线严格确认与风控实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```

## 回测结果

- 数据：`XAUUSD_M15.csv`
- 区间：`2025-12-03 01:15:00` 到 `2026-03-10 09:00:00`
- 参数：`lots=0.1`、`take_profit=50`、`stop_loss=1100`、`trailing_stop=100`、`fast_period=24`、`fast_shift=6`、`middle_period=60`、`middle_shift=6`、`slow_period=120`、`slow_shift=6`
- 信号次数：`35`
- 已平仓交易：`35`
- TradeAnalyzer 统计交易：`35`
- 胜率：`54.29%`
- 期初资金：`100000.00`
- 期末现金：`100170.20`
- 期末权益：`100170.20`
- 净收益：`170.20`
- 最大回撤：`0.45%`
- SQN：`0.41`

说明：样本结束时无未平仓头寸，`open_position_size=0.0`、`open_position_price=0.0`。
