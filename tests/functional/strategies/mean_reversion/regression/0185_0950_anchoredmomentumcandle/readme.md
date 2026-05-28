# 0950 AnchoredMomentumCandle

## 策略概述

该示例是 MT5 EA `Exp_AnchoredMomentumCandle` 的 Backtrader 迁移版本。

原 EA 基于 `AnchoredMomentumCandle` 指标颜色切换开平仓，并配合固定 `SL/TP` 管理持仓。

## 指标重建

- `AnchoredMomentum` 以 `Momentum = 100 * (EMA / SMA - 1)` 计算锚定动量
- 对 `open/high/low/close` 四个价格序列分别计算动量并组合为彩色蜡烛
- 颜色索引与原始 EA 一致：`2/1/0`
- 默认使用 `H4` 信号周期

## 交易逻辑

- 颜色切换到 `2` 时做多并平空
- 颜色切换到 `0` 时做空并平多
- 使用固定 `SL/TP`

## 文件

- `strategy_anchoredmomentumcandle.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
