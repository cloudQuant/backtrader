# 1140 EA_MALR

## 策略概述

该策略是对 MT5 EA `EA_MALR` 的 Backtrader 迁移版本。

原 EA 基于 `MALR` 指标的外层通道线 `MALRHH/MALRLL` 触发交易，并支持反向翻仓、亏损后均价加仓、可选净值驱动手数放大和尾随止损。

## 交易逻辑

- 用 `MALR = 3 * LWMA - 2 * SMA` 构建中心线
- 以 `close - MALR` 的标准差生成上下通道与外层通道 `MALRHH/MALRLL`
- 当价格相对 `MALRHH` 发生源码定义的交叉时开空
- 当价格相对 `MALRLL` 发生源码定义的交叉时开多
- 若启用 `position_overturn`，反向信号到来时先平仓再按倍数反向开仓
- 若启用 `use_averaging`，同向持仓在浮亏达到阈值后按记录基础手数继续加仓

## 风控逻辑

- 固定 `SL/TP`
- 可选 `trail_stoploss`
- 可选 `use_increase` 按净值/回撤参数放大初始手数

## 文件

- `strategy_ea_malr.py` - 数据加载、MALR 指标与交易状态机实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```

## 回测结果

- 数据：`XAUUSD_M15.csv`
- 区间：`2025-12-03 01:15:00` 到 `2026-03-10 09:00:00`
- 参数：`lot=0.1`、`sl=2550`、`tp=2578`、`use_averaging=false`、`loss_for_averaging=500`、`position_overturn=true`、`koff_multiplication=2.0`、`use_increase=true`、`max_drawdown=5000`、`trail_stoploss=false`
- 信号次数：`71`
- 已平仓交易：`71`
- TradeAnalyzer 统计交易：`71`
- 胜率：`46.48%`
- 期初资金：`100000.00`
- 期末现金：`103025.99`
- 期末权益：`103025.99`
- 净收益：`3025.99`
- 最大回撤：`46.06%`
- SQN：`0.07`

说明：当前配置下未启用均价加仓，样本结束时无未平仓头寸，`open_position_size=0.0`、`open_position_price=0.0`。
