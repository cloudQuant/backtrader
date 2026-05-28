# 1000 ColorHMA

## 策略概述

该示例是 MT5 EA `Exp_ColorHMA` 的 Backtrader 迁移版本。

原 EA 基于 `ColorHMA` 指标的方向反转进行交易：在柱线收盘时，如果 HMA 先下行后上拐则做多，先上行后下拐则做空。

## 交易逻辑

- 按本地 `ColorHMA` 指标源码重建 Hull Moving Average：
  - `LWMA(period/2)`
  - `LWMA(period)`
  - `HMA = LWMA(sqrt(period), 2 * LWMA(period/2) - LWMA(period))`
- 使用最近三根已完成指标值判断方向反转：
  - `v1 < v2` 且 `v0 > v1` 时开多并平空
  - `v1 > v2` 且 `v0 < v1` 时开空并平多
- 默认使用 `H8` 信号周期

## 风控逻辑

- 固定 `stop_loss_points`
- 固定 `take_profit_points`
- 固定手数 `lot`
- 反向信号到来时先平仓再反手

## 文件

- `strategy_colorhma.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
