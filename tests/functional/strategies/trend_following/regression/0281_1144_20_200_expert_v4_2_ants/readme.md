# 1144 20_200 expert_v4.2_AntS

## 策略概述

该策略是对 MT5 EA `20_200 expert_v4.2_AntS` 的 Backtrader 迁移版本。

原 EA 根据两根不同位移柱线的开盘价差判断价格上升或下降，并在固定入场时刻开仓；如果上一笔后账户余额下降，则使用倍增系数扩大下一笔手数。持仓也受最大生存时间限制。

## 交易逻辑

- 读取 `t1` 与 `t2` 位移柱线的开盘价
- 若 `open[t2] - open[t1] > Delta_L * point`，则在 `trade_time` 小时做多
- 若 `open[t1] - open[t2] > Delta_S * point`，则在 `trade_time` 小时做空
- 仅在无持仓时开新仓

## 风控逻辑

- 多空分别使用独立的 `SL/TP`
- 若检测到上一笔后账户余额下降，则下一笔按 `big_lot_size` 放大手数
- `auto_lot=true` 时根据当前权益估算基础手数
- 持仓超过 `max_open_time` 小时后强制平仓

## 文件

- `strategy_20_200_expert_v4_2_ants.py` - 数据加载、位移开盘价差入场与动态手数实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```

## 回测结果

- 数据：`XAUUSD_M15.csv`
- 区间：`2025-12-03 01:15:00` 到 `2026-03-10 09:00:00`
- 参数：`t1=6`、`t2=2`、`delta_l=6`、`delta_s=21`、`take_profit_l=390`、`stop_loss_l=1470`、`take_profit_s=320`、`stop_loss_s=2670`、`lots=0.1`、`auto_lot=true`、`big_lot_size=6.0`、`one_mult=true`、`trade_time=14`、`max_open_time=504`
- 信号次数：`106`
- 已平仓交易：`106`
- TradeAnalyzer 统计交易：`106`
- 胜率：`60.38%`
- 期初资金：`100000.00`
- 期末现金：`31829.37`
- 期末权益：`31829.37`
- 净收益：`-68170.63`
- 最大回撤：`73.64%`
- SQN：`-1.64`

说明：样本结束时无未平仓头寸，`open_position_size=0.0`、`open_position_price=0.0`。
