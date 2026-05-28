# 1005 FineTuningMA

## 策略概述

该示例是 MT5 EA `Exp_FineTuningMA` 的 Backtrader 迁移版本。

原 EA 基于 `FineTuningMA` 单线方向反转生成交易信号：若均线先向下后转向上则做多，先向上后转向下则做空。

## 交易逻辑

- 按源码中的三段幂函数权重重建 `FineTuningMA`
- 使用最近三根指标值判断方向反转：
  - `v1 < v2` 且 `v0 > v1` 时开多并平空
  - `v1 > v2` 且 `v0 < v1` 时开空并平多
- 默认使用 `H4` 信号周期

## 风控逻辑

- 固定 `stop_loss_points`
- 固定 `take_profit_points`
- 固定手数 `lot`
- 反向信号到来时先平仓再反手

## 文件

- `strategy_finetuningma.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
