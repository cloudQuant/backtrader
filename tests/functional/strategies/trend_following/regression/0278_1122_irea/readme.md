# 1122 IREA

## 策略概述

该策略是对 MT5 `IREA` 的 Backtrader 迁移版本。

原 EA 使用 `InverseReaction` 指标识别异常单根柱形冲击，并在下一根新柱确认时按冲击方向做反向交易。

## 交易逻辑

- 计算 `price_change = close - open`
- 计算 `Dynamic Confidence Level = coefficient * SMA(abs(price_change), ma_period)`
- 当最新收盘柱的 `abs(price_change)` 高于动态阈值，且位于 `min_criteria` 与 `max_criteria` 区间内，并且前一根柱没有重复信号时触发入场
- 若 `price_change < 0` 则做多
- 若 `price_change > 0` 则做空
- 同时只允许一笔持仓

## 风控逻辑

- 固定 `stop_loss`
- 固定 `take_profit`
- 固定手数 `trade_volume`

## 文件

- `strategy_irea.py` - 数据加载、`InverseReaction` 指标与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```

## 回测结果

- 数据：`XAUUSD_M15.csv`
- 区间：`2025-12-03 01:15:00` 到 `2026-03-10 09:00:00`
- 参数：`stop_loss=1000`、`take_profit=250`、`trade_volume=1.0`、`min_criteria=300`、`max_criteria=2000`、`coefficient=1.618`、`ma_period=3`
- 信号次数：`717`
- 已平仓交易：`717`
- TradeAnalyzer 统计交易：`717`
- 胜率：`58.72%`
- 期初资金：`100000.00`
- 期末现金：`86605.00`
- 期末权益：`86605.00`
- 净收益：`-13395.00`
- 最大回撤：`30.82%`
- SQN：`-0.47`

说明：样本结束时无未平仓头寸，`open_position_size=0.0`、`open_position_price=0.0`。该参数组合下触发频率很高，虽然胜率高于 50%，但盈亏比不足，导致总体净值回撤。
