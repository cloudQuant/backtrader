# 0973 ColorSchaffDeMarkerTrendCycle

## 策略概述

该示例是 MT5 EA `Exp_ColorSchaffDeMarkerTrendCycle` 的 Backtrader 迁移版本。

原 EA 基于 `ColorSchaffDeMarkerTrendCycle` 颜色区间变化开平仓：从强正区离开时做多并平空，从强负区离开时做空并平多。

## 指标重建

- 指标源码完整，不依赖缺失的 `SmoothAlgorithms.mqh`
- 使用两路内置 `DeMarker` 差值生成 `MACD`
- 保留 Schaff 双阶段区间归一化和平滑语义
- 颜色索引按源码的强弱区与升降方向分为 `0..7`
- 默认使用 `H4` 信号周期

## 交易逻辑

- 上一根颜色大于 `5` 且当前颜色小于 `6` 时做多并平空
- 上一根颜色小于 `2` 且当前颜色大于 `1` 时做空并平多
- 使用固定 `SL/TP`

## 文件

- `strategy_colorschaffdemarkertrendcycle.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
