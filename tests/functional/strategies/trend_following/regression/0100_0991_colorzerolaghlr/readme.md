# 0991 ColorZerolagHLR

## 策略概述

该示例是 MT5 EA `Exp_ColorZerolagHLR` 的 Backtrader 迁移版本。

原 EA 基于 `ColorZerolagHLR` 的快慢线交叉在已完成柱上触发信号，并用固定 `SL/TP` 管理持仓。

## 指标重建

- `HLR(period) = 100 * ((high + low) / 2 - LL(period)) / (HH(period) - LL(period))`
- 五组 `HLR` 按固定权重聚合为 `FastTrend`
- `SlowTrend = FastTrend / smoothing + SlowTrend[-1] * ((smoothing - 1) / smoothing)`
- 默认使用 `H4` 信号周期
- 为保持源码一致性，第三路聚合沿用源码中的 `Factor2 * HLR3`

## 交易逻辑

- 按源码判定：当上一根已完成柱 `fast > slow` 且最近一根已完成柱 `fast < slow` 时做多并平空
- 当上一根已完成柱 `fast < slow` 且最近一根已完成柱 `fast > slow` 时做空并平多
- 使用固定 `SL/TP`

## 文件

- `strategy_colorzerolaghlr.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
