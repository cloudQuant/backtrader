# 0989 Instantaneous TrendFilter

## 策略概述

该示例是 MT5 EA `Exp_Instantaneous_TrendFilter` 的 Backtrader 迁移版本。

原 EA 在 `Instantaneous_TrendFilter` 指标的触发线与趋势线交叉时开平仓，并配合固定 `SL/TP` 管理持仓。

## 指标重建

- 指标源码完整，不依赖缺失的 `SmoothAlgorithms.mqh`
- 使用 `Alpha` 推导 5 个递推系数
- 主线 `trend` 在预热后按原始递推公式更新
- 触发线 `trigger = 2 * trend - trend[-2]`
- 默认使用 `H4` 信号周期

## 交易逻辑

- 若上一根 `trigger > trend` 且当前 `trigger < trend`，则做多并平空
- 若上一根 `trigger < trend` 且当前 `trigger > trend`，则做空并平多
- 使用固定 `SL/TP`

## 文件

- `strategy_instantaneous_trendfilter.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
