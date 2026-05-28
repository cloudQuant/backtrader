# 0962 MomentumCandleSign

## 策略概述

该示例是 MT5 EA `Exp_MomentumCandleSign` 的 Backtrader 迁移版本。

原 EA 基于 `Momentum(open)` 与 `Momentum(close)` 的交叉点位开平仓，并配合固定 `SL/TP` 管理持仓。

## 指标重建

- 指标源码完整，不依赖缺失的 `SmoothAlgorithms.mqh`
- 分别对 `open` 与 `close` 计算内置 `Momentum`
- 当 `Momentum(open/close)` 发生交叉时，在 `low - ATR * 3 / 8` 或 `high + ATR * 3 / 8` 位置生成信号点
- 默认使用 `H12` 信号周期

## 交易逻辑

- 出现买点时做多并平空
- 出现卖点时做空并平多
- 使用固定 `SL/TP`

## 文件

- `strategy_momentumcandlesign.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
