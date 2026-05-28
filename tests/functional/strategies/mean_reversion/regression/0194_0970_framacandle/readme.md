# 0970 FrAMACandle

## 策略概述

该示例是 MT5 EA `Exp_FrAMACandle` 的 Backtrader 迁移版本。

原 EA 基于 `FrAMACandle` 蜡烛颜色变化开平仓，并配合固定 `SL/TP` 管理持仓。

## 指标重建

- 指标源码完整，不依赖缺失的 `SmoothAlgorithms.mqh`
- 分别对 `open/high/low/close` 应用内置 `FrAMA`
- 按源码重建平滑蜡烛并生成颜色索引：`0` 空头、`1` 中性、`2` 多头
- 默认使用 `H4` 信号周期

## 交易逻辑

- 上一根颜色为 `2` 且当前颜色小于 `2` 时做多并平空
- 上一根颜色为 `0` 且当前颜色大于 `0` 时做空并平多
- 使用固定 `SL/TP`

## 文件

- `strategy_framacandle.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
