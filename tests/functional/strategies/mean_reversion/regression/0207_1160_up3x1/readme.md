# 1160 up3x1

## 策略概述

该策略是对 MT5 EA `1160_up3x1` 的 Backtrader 迁移版本。

原 EA 使用三条移动平均线的相对位置与交叉关系作为入场信号，并为持仓设置固定 `SL/TP` 与可选 trailing stop。

## 交易逻辑

- 当快速均线向上穿越中间均线，且快速与中间均线都位于慢速均线下方时做多
- 当快速均线向下穿越中间均线，且快速与中间均线都位于慢速均线上方时做空
- 开仓后按固定点数设置 `StopLoss` 和 `TakeProfit`
- 若启用 `TrailingStop`，则按固定点距推进止损

## 资金管理

- `lots > 0` 时使用固定手数
- `lots = 0` 时按 `cash * maximum_risk / 1000` 估算手数
- 若启用 `decrease_factor`，则在连续亏损后递减新开仓手数

## 文件

- `strategy_up3x1.py` - 数据加载、三均线与风控实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```

## 回测结果

- 数据：`XAUUSD_M15.csv`
- 区间：`2025-12-03 01:15:00` 到 `2026-03-10 09:00:00`
- 参数：`lots=0.1`、`take_profit=150`、`stop_loss=100`、`trailing_stop=100`、`fast_period=24`、`fast_shift=6`、`middle_period=60`、`middle_shift=6`、`slow_period=120`、`slow_shift=6`
- 信号次数：`68`
- 已平仓交易：`68`
- TradeAnalyzer 统计交易：`68`
- 胜率：`41.18%`
- 期初资金：`100000.00`
- 期末现金：`98744.40`
- 期末权益：`98744.40`
- 净收益：`-1255.60`
- 最大回撤：`1.33%`
- SQN：`-1.84`

说明：样本结束时无未平仓头寸，`open_position_size=0.0`、`open_position_price=0.0`。
