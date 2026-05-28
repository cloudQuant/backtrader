# 0959 Dots

## 策略概述

该示例是 MT5 EA `Exp_Dots` 的 Backtrader 迁移版本。

原 EA 基于 `Dots` 指标信号点颜色翻转开平仓，并配合固定 `SL/TP` 管理持仓。

## 指标重建

- 指标源码完整，不依赖缺失的 `SmoothAlgorithms.mqh`
- 按源码重建 `Dots` 非线性加权平滑与颜色索引 `0/1`
- 当颜色从 `1 -> 0` 时视为买入翻转，从 `0 -> 1` 时视为卖出翻转
- 默认使用 `H4` 信号周期

## 交易逻辑

- 颜色翻转到买入色时做多并平空
- 颜色翻转到卖出色时做空并平多
- 使用固定 `SL/TP`

## 文件

- `strategy_dots.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
