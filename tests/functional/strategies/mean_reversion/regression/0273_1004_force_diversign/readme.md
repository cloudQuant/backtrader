# 1004 Force DiverSign

## 策略概述

该示例是 MT5 EA `Exp_Force_DiverSign` 的 Backtrader 迁移版本。

原 EA 基于 `Force_DiverSign` 指标的买卖箭头交易。指标结合双 Force Index 平滑、三根 K 线组合，以及 ATR 偏移位置来输出多空信号。

## 交易逻辑

- 计算两条不同周期的 Force Index EMA 序列
- 检测源码里的三柱形态条件与双序列拐点/背离条件
- 满足卖出条件时产生卖箭头，满足买入条件时产生买箭头
- 买箭头开多并平空，卖箭头开空并平多
- 默认使用 `H4` 信号周期

## 风控逻辑

- 固定 `stop_loss_points`
- 固定 `take_profit_points`
- 固定手数 `lot`
- 反向信号到来时先平仓再反手

## 文件

- `strategy_force_diversign.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
