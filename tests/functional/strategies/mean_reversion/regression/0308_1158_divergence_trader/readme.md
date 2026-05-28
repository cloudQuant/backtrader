# 1158 发散交易

## 策略概述

该策略是对 MT5 EA `发散交易` 的 Backtrader 迁移版本。

原 EA 使用两条基于指定价格源的简单均线，依据发散值是否落入允许区间来触发多空入场，同时支持同向加仓、trailing、`BreakEven` 和账户级篮子止盈止损。

## 交易逻辑

- 以配置的 `Fast_Price` 与 `Slow_Price` 计算快慢 SMA
- 发散值由最近均线差值决定，并与 `DVBuySell` / `DVStayOut` 阈值比较
- 当发散值位于正向区间时做多
- 当发散值位于负向区间时做空
- `MultyOpen=true` 时允许在同向已持仓基础上继续加仓，前提是不超过 `MaxVolume`

## 风控逻辑

- 开仓后设置固定 `StopLoss` 与 `TakeProfit`
- 若启用 `Trailing`，则按固定点距推进止损
- 若启用 `BreakEven`，则浮盈达到阈值后把止损推至开仓价
- 若启用 `BasketProfitON/BasketLossON`，则当账户级盈亏触发阈值时直接平仓

## 文件

- `strategy_divergence_trader.py` - 数据加载、发散信号和风控实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```

## 回测结果

- 数据：`XAUUSD_M15.csv`
- 区间：`2025-12-03 01:15:00` 到 `2026-03-10 09:00:00`
- 参数：`lots=0.1`、`multy_open=false`、`max_volume=0.5`、`stop_loss=550`、`take_profit=550`、`trailing=0`、`break_even=0`、`fast_period=7`、`fast_price=1`、`slow_period=88`、`slow_price=1`、`dv_buy_sell=0.0011`、`dv_stay_out=0.0079`
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

说明：本样本区间内未触发有效发散入场信号，样本结束时无未平仓头寸，`open_position_size=0.0`、`open_position_price=0.0`。
