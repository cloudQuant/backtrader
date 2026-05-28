# 1163 gpfTCPivotLimit

## 策略概述

该策略是对 MT5 EA `1163_gpfTCPivotLimit` 的 Backtrader 迁移版本。

原 EA 使用前一交易日的日线枢轴位和多档支撑/阻力位定义多空触发层级，在最近两根已完成 K 线围绕指定支撑/阻力位形成反转结构后，以市价开仓，并按对应层级设置 `SL/TP`。

## 交易逻辑

- 先用前一交易日 `high/low/close` 计算 `Pivot`、`Support1-3`、`Resist1-3`
- 按 `target_profit` 选择当前使用的买入触发位 `b_level` 或卖出触发位 `s_level`
- 当前两根已完成 K 线满足“前一根向下试探并站回支撑位”的结构时做多
- 当前两根已完成 K 线满足“前一根向上试探并跌回阻力位”的结构时做空
- 若启用 `is_trade_day`，则在 `23:00` 直接平掉当日持仓

## 风控逻辑

- 每个 `target_profit` 档位都有对应的 `SL/TP`
- 若启用 `mod_sl`，到达首目标位后将止损推到开仓价附近
- `lots = 0` 时按 `cash * max_risk / 1000` 估算手数
- 若连续亏损超过 1 笔，则按 `decrease_factor` 递减新开仓手数

## 文件

- `strategy_gpftcpivotlimit.py` - 数据加载、枢轴层级与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```

## 回测结果

- 数据：`XAUUSD_M15.csv`
- 区间：`2025-12-03 01:15:00` 到 `2026-03-10 09:00:00`
- 参数：`lots=0.1`、`target_profit=5`、`is_trade_day=false`、`mod_sl=false`
- 信号次数：`67`
- 已平仓交易：`16`
- TradeAnalyzer 统计交易：`16`
- 胜率：`18.75%`
- 期初资金：`100000.00`
- 期末现金：`100826.58`
- 期末权益：`100826.58`
- 净收益：`826.58`
- 最大回撤：`4.04%`
- SQN：`0.14`

说明：样本结束时无未平仓头寸，`open_position_size=0.0`、`open_position_price=0.0`。
