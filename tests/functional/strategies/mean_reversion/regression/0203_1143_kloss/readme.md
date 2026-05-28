# 1143 Kloss

## 策略概述

该策略是对 MT5 EA `Kloss` 的 Backtrader 迁移版本。

原 EA 组合使用 `MA`、`CCI` 和 `Stochastic`：当 `CCI` 与 `Stochastic` 处在超卖区且价格高于均线时做多；当 `CCI` 与 `Stochastic` 处在超买区且价格低于均线时做空。

## 交易逻辑

- 多头条件：`CCI < -CCIDiffer` 且 `StochasticMain < 50 - StDiffer` 且 `close[p_shift] > MA[ma_shift]`
- 空头条件：`CCI > CCIDiffer` 且 `StochasticMain > 50 + StDiffer` 且 `close[p_shift] < MA[ma_shift]`
- 若 `rev_close=true`，反向信号会平掉当前持仓

## 风控逻辑

- 支持固定 `SL/TP`
- `lots=0` 时按 `maximum_risk` 估算手数
- `mw_mode=true` 时按原 EA 语义模拟“开仓后再设置 SL/TP”

## 文件

- `strategy_kloss.py` - 数据加载、MA/CCI/Stochastic 组合信号与风控实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```

## 回测结果

- 数据：`XAUUSD_M15.csv`
- 区间：`2025-12-03 01:15:00` 到 `2026-03-10 09:00:00`
- 参数：`lots=0.1`、`maximum_risk=0.05`、`stop_loss=550`、`take_profit=550`、`rev_close=true`、`ma_period=1`、`ma_method=lwma`、`ma_price=typical`、`ma_shift=5`、`p_shift=1`、`cci_period=10`、`cci_price=weighted`、`cci_differ=120`、`st_k_period=5`、`st_d_period=3`、`st_s_period=3`、`st_method=sma`、`st_differ=20`、`common_shift=1`、`mw_mode=true`
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

说明：本样本区间内未触发有效 `MA + CCI + Stochastic` 组合入场信号，样本结束时无未平仓头寸，`open_position_size=0.0`、`open_position_price=0.0`。
