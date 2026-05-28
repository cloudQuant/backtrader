# 0972 ColorZerolagDeMarker

## 策略概述

该示例是 MT5 EA `Exp_ColorZerolagDeMarker` 的 Backtrader 迁移版本。

原 EA 基于 `ColorZerolagDeMarker` 快慢线交叉开平仓，并配合固定 `SL/TP` 管理持仓。

## 指标重建

- 指标源码完整，不依赖缺失的 `SmoothAlgorithms.mqh`
- 使用五路内置 `DeMarker` 按权重聚合为快速趋势线
- 慢线按源码的 `FastTrend / smoothing + prev_slow * smoothConst` 递推
- 保留源码中第三路仍使用 `Factor2 * DeMarker3` 的实现细节
- 默认使用 `H3` 信号周期

## 交易逻辑

- 上一根 `fast > slow` 且当前 `fast < slow` 时做多并平空
- 上一根 `fast < slow` 且当前 `fast > slow` 时做空并平多
- 使用固定 `SL/TP`

## 文件

- `strategy_colorzerolagdemarker.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
