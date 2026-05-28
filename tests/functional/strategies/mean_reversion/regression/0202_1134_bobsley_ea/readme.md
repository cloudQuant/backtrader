# 1134 Bobsley_EA

## 策略概述

该策略是对 MT5 `Bobsley_EA` 的 Backtrader 迁移版本。

原 EA 使用 `SMA + Stochastic` 的方向与超买超卖位置来开仓，只保留单笔仓位，并由固定 `SL/TP` 负责出场。

## 交易逻辑

- 做多：`MA` 连续上行，价格位于 `MA` 上方，随机指标上升且当前值低于超卖阈值
- 做空：`MA` 连续下行，价格位于 `MA` 下方，随机指标下降且当前值高于超买阈值
- 仅在当前无持仓时允许开仓
- 若可用资金不足阈值则不交易

## 风控逻辑

- 固定 `SL/TP`
- 手数按源码中的 `Money_M()` 逻辑根据可用现金估算并限制在 `[0.1, 15]`

## 文件

- `strategy_bobsley_ea.py` - 数据加载、SMA/Stochastic 信号与交易实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```

## 回测结果

- 数据：`XAUUSD_M15.csv`
- 区间：`2025-12-03 01:15:00` 到 `2026-03-10 09:00:00`
- 参数：`take_profit=0.007`、`stop_loss=0.0035`、`ma_period=76`、`stoch_oversold=30`、`stoch_overbought=70`、`lot=5.0`
- 信号次数：`0`
- 已平仓交易：`0`
- TradeAnalyzer 统计交易：`0`
- 胜率：`0.00%`
- 期初资金：`100000.00`
- 期末现金：`100000.00`
- 期末权益：`100000.00`
- 净收益：`0.00`
- 最大回撤：`0.00%`
- SQN：`0.00`

说明：当前样本区间内未触发 `SMA + Stochastic` 入场条件，样本结束时无未平仓头寸，`open_position_size=0`、`open_position_price=0.0`。
